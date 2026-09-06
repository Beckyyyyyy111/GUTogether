#include <errno.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include <zephyr/audio/dmic.h>
#include <zephyr/device.h>
#include <zephyr/drivers/i2s.h>
#include <zephyr/fs/fs.h>
#include <zephyr/kernel.h>

#include "PDM.h"
#include "SD.h"

#define PDM_SAMPLE_WIDTH 16U
#define PDM_STEREO_CHANNELS 2U
#define PDM_READ_TIMEOUT_MS 1000
#define PDM_BLOCKS_PER_SECOND 10U
#define PDM_BYTES_PER_SAMPLE sizeof(int16_t)
#define PDM_BLOCK_SIZE(sample_rate, channels) \
	(PDM_BYTES_PER_SAMPLE * (channels) * ((sample_rate) / PDM_BLOCKS_PER_SECOND))
#define PDM_BLOCK_COUNT 4U
#define PDM_LOOPBACK_TIMEOUT_MS 2000
#define PDM_LOOPBACK_OUTPUT_CHANNELS 2U
#define PDM_MIN_SAMPLE_RATE 8000U
#define PDM_MAX_SAMPLE_RATE 16000U

K_MEM_SLAB_DEFINE_STATIC(loopback_tx_slab,
			 PDM_BLOCK_SIZE(PDM_MAX_SAMPLE_RATE, PDM_STEREO_CHANNELS),
			 PDM_BLOCK_COUNT,
			 4);

K_MEM_SLAB_DEFINE_STATIC(pdm_mem_slab,
			 PDM_BLOCK_SIZE(PDM_MAX_SAMPLE_RATE, PDM_STEREO_CHANNELS),
			 PDM_BLOCK_COUNT,
			 4);

static const struct device *loopback_i2s_dev;
static bool loopback_i2s_initialized;

struct wav_header {
	char riff[4];
	uint32_t overall_size;
	char wave[4];
	char fmt_chunk_marker[4];
	uint32_t length_of_fmt;
	uint16_t format_type;
	uint16_t channels;
	uint32_t sample_rate;
	uint32_t byterate;
	uint16_t block_align;
	uint16_t bits_per_sample;
	char data_chunk_header[4];
	uint32_t data_size;
};

static void create_wav_header(struct wav_header *header,
			      uint16_t channels,
			      uint32_t sample_rate,
			      uint32_t pcm_data_size)
{
	memcpy(header->riff, "RIFF", sizeof(header->riff));
	header->overall_size = pcm_data_size + 36U;
	memcpy(header->wave, "WAVE", sizeof(header->wave));
	memcpy(header->fmt_chunk_marker, "fmt ", sizeof(header->fmt_chunk_marker));
	header->length_of_fmt = 16U;
	header->format_type = 1U;
	header->channels = channels;
	header->sample_rate = sample_rate;
	header->byterate = sample_rate * channels * (PDM_SAMPLE_WIDTH / 8U);
	header->block_align = channels * (PDM_SAMPLE_WIDTH / 8U);
	header->bits_per_sample = PDM_SAMPLE_WIDTH;
	memcpy(header->data_chunk_header, "data", sizeof(header->data_chunk_header));
	header->data_size = pcm_data_size;
}

static int write_wav_header(struct fs_file_t *file,
			    uint16_t channels,
			    uint32_t sample_rate,
			    uint32_t pcm_data_size)
{
	struct wav_header header;
	ssize_t written;

	create_wav_header(&header, channels, sample_rate, pcm_data_size);

	written = fs_write(file, &header, sizeof(header));
	if (written < 0) {
		return (int)written;
	}

	if ((size_t)written != sizeof(header)) {
		return -ENOSPC;
	}

	return 0;
}

static int finalize_wav_file(struct fs_file_t *file,
			     uint16_t channels,
			     uint32_t sample_rate,
			     uint32_t pcm_data_size)
{
	int ret = fs_seek(file, 0, FS_SEEK_SET);
	if (ret < 0) {
		return ret;
	}

	ret = write_wav_header(file, channels, sample_rate, pcm_data_size);
	if (ret < 0) {
		return ret;
	}

	ret = fs_seek(file, 0, FS_SEEK_END);
	if (ret < 0) {
		return ret;
	}

	return fs_sync(file);
}

static int loopback_i2s_init(void)
{
	if (loopback_i2s_initialized) {
		return 0;
	}

	loopback_i2s_dev = DEVICE_DT_GET(DT_ALIAS(i2s_tx));
	if (!device_is_ready(loopback_i2s_dev)) {
		return -ENODEV;
	}

	loopback_i2s_initialized = true;
	return 0;
}

static int loopback_i2s_configure(uint32_t sample_rate)
{
	struct i2s_config i2s_cfg = {
		.word_size = PDM_SAMPLE_WIDTH,
		.channels = PDM_LOOPBACK_OUTPUT_CHANNELS,
		.format = I2S_FMT_DATA_FORMAT_I2S,
		.frame_clk_freq = sample_rate,
		.block_size = PDM_BLOCK_SIZE(sample_rate, PDM_STEREO_CHANNELS),
		.timeout = PDM_LOOPBACK_TIMEOUT_MS,
		.options = I2S_OPT_FRAME_CLK_MASTER | I2S_OPT_BIT_CLK_MASTER,
		.mem_slab = &loopback_tx_slab,
	};

	return i2s_configure(loopback_i2s_dev, I2S_DIR_TX, &i2s_cfg);
}

static int loopback_queue_block(void *tx_block,
				size_t block_size,
				bool *started,
				uint32_t *queued_blocks)
{
	int ret = i2s_write(loopback_i2s_dev, tx_block, block_size);

	if (ret < 0) {
		k_mem_slab_free(&loopback_tx_slab, tx_block);
		return ret;
	}

	*queued_blocks += 1U;
	if (!(*started) && (*queued_blocks >= 2U)) {
		ret = i2s_trigger(loopback_i2s_dev, I2S_DIR_TX, I2S_TRIGGER_START);
		if (ret < 0) {
			return ret;
		}

		*started = true;
	}

	return 0;
}

static int loopback_finish(bool started, uint32_t queued_blocks)
{
	int ret;

	if (!started && (queued_blocks == 0U)) {
		return 0;
	}

	if (!started) {
		ret = i2s_trigger(loopback_i2s_dev, I2S_DIR_TX, I2S_TRIGGER_START);
		if (ret < 0) {
			(void)i2s_trigger(loopback_i2s_dev, I2S_DIR_TX, I2S_TRIGGER_DROP);
			return ret;
		}
	}

	ret = i2s_trigger(loopback_i2s_dev, I2S_DIR_TX, I2S_TRIGGER_DRAIN);
	if (ret < 0) {
		(void)i2s_trigger(loopback_i2s_dev, I2S_DIR_TX, I2S_TRIGGER_DROP);
		return ret;
	}

	return 0;
}

static int pdm_validate_sample_rate(uint32_t sample_rate)
{
	if ((sample_rate == PDM_MIN_SAMPLE_RATE) ||
	    (sample_rate == PDM_MAX_SAMPLE_RATE)) {
		return 0;
	}

	return -EINVAL;
}

int PDM_Record_Stereo_Wav_Until(const char *file_path,
				uint32_t sample_rate,
				pdm_stop_cb_t stop_cb,
				void *context)
{
	const struct device *dmic_dev = DEVICE_DT_GET(DT_NODELABEL(pdm0));
	struct fs_file_t file;
	struct pcm_stream_cfg stream = {
		.pcm_width = PDM_SAMPLE_WIDTH,
		.mem_slab = &pdm_mem_slab,
	};
	struct dmic_cfg cfg = {
		.io = {
			.min_pdm_clk_freq = 1000000,
			.max_pdm_clk_freq = 3500000,
			.min_pdm_clk_dc = 40,
			.max_pdm_clk_dc = 60,
		},
		.streams = &stream,
		.channel = {
			.req_num_streams = 1,
			.req_num_chan = PDM_STEREO_CHANNELS,
			.req_chan_map_lo = dmic_build_channel_map(0, 0, PDM_CHAN_LEFT) |
					   dmic_build_channel_map(1, 0, PDM_CHAN_RIGHT),
		},
	};
	uint32_t total_pcm_size = 0U;
	size_t block_size = PDM_BLOCK_SIZE(sample_rate, PDM_STEREO_CHANNELS);
	int ret;

	ret = pdm_validate_sample_rate(sample_rate);
	if (ret < 0) {
		return ret;
	}

	if ((file_path == NULL) || !device_is_ready(dmic_dev)) {
		return -ENODEV;
	}

	ret = SD_Init();
	if (ret < 0) {
		return ret;
	}

	fs_file_t_init(&file);
	ret = fs_open(&file, file_path, FS_O_CREATE | FS_O_WRITE | FS_O_TRUNC);
	if (ret < 0) {
		return ret;
	}

	ret = write_wav_header(&file, PDM_STEREO_CHANNELS, sample_rate, 0U);
	if (ret < 0) {
		(void)fs_close(&file);
		return ret;
	}

	stream.pcm_rate = sample_rate;
	stream.block_size = block_size;

	ret = dmic_configure(dmic_dev, &cfg);
	if (ret < 0) {
		(void)fs_close(&file);
		return ret;
	}

	ret = dmic_trigger(dmic_dev, DMIC_TRIGGER_START);
	if (ret < 0) {
		(void)fs_close(&file);
		return ret;
	}

	while (1) {
		void *buffer = NULL;
		uint32_t size = 0U;
		ssize_t written;

		if ((stop_cb != NULL) && stop_cb(context)) {
			break;
		}

		ret = dmic_read(dmic_dev, 0, &buffer, &size, PDM_READ_TIMEOUT_MS);
		if (ret < 0) {
			(void)dmic_trigger(dmic_dev, DMIC_TRIGGER_STOP);
			(void)fs_close(&file);
			return ret;
		}

		written = fs_write(&file, buffer, size);
		if (written < 0) {
			k_mem_slab_free(&pdm_mem_slab, buffer);
			(void)dmic_trigger(dmic_dev, DMIC_TRIGGER_STOP);
			(void)fs_close(&file);
			return (int)written;
		}

		if ((uint32_t)written != size) {
			k_mem_slab_free(&pdm_mem_slab, buffer);
			(void)dmic_trigger(dmic_dev, DMIC_TRIGGER_STOP);
			(void)fs_close(&file);
			return -ENOSPC;
		}

		total_pcm_size += size;
		k_mem_slab_free(&pdm_mem_slab, buffer);
	}

	ret = dmic_trigger(dmic_dev, DMIC_TRIGGER_STOP);
	if (ret < 0) {
		(void)fs_close(&file);
		return ret;
	}

	ret = finalize_wav_file(&file, PDM_STEREO_CHANNELS, sample_rate, total_pcm_size);
	if (ret < 0) {
		(void)fs_close(&file);
		return ret;
	}

	return fs_close(&file);
}

int PDM_Live_Monitor_Until(uint32_t sample_rate,
			   pdm_stop_cb_t stop_cb,
			   void *context)
{
	const struct device *dmic_dev = DEVICE_DT_GET(DT_NODELABEL(pdm0));
	struct pcm_stream_cfg stream = {
		.pcm_width = PDM_SAMPLE_WIDTH,
		.mem_slab = &pdm_mem_slab,
	};
	struct dmic_cfg cfg = {
		.io = {
			.min_pdm_clk_freq = 1000000,
			.max_pdm_clk_freq = 3500000,
			.min_pdm_clk_dc = 40,
			.max_pdm_clk_dc = 60,
		},
		.streams = &stream,
		.channel = {
			.req_num_streams = 1,
			.req_num_chan = PDM_STEREO_CHANNELS,
			.req_chan_map_lo = dmic_build_channel_map(0, 0, PDM_CHAN_LEFT) |
					   dmic_build_channel_map(1, 0, PDM_CHAN_RIGHT),
		},
	};
	bool started = false;
	uint32_t queued_blocks = 0U;
	size_t block_size = PDM_BLOCK_SIZE(sample_rate, PDM_STEREO_CHANNELS);
	int ret;

	ret = pdm_validate_sample_rate(sample_rate);
	if (ret < 0) {
		return ret;
	}

	if (!device_is_ready(dmic_dev)) {
		return -ENODEV;
	}

	ret = loopback_i2s_init();
	if (ret < 0) {
		return ret;
	}

	ret = loopback_i2s_configure(sample_rate);
	if (ret < 0) {
		return ret;
	}

	stream.pcm_rate = sample_rate;
	stream.block_size = block_size;

	ret = dmic_configure(dmic_dev, &cfg);
	if (ret < 0) {
		return ret;
	}

	ret = dmic_trigger(dmic_dev, DMIC_TRIGGER_START);
	if (ret < 0) {
		return ret;
	}

	while (1) {
		void *capture_buffer = NULL;
		void *tx_block = NULL;
		uint32_t size = 0U;

		if ((stop_cb != NULL) && stop_cb(context)) {
			break;
		}

		ret = dmic_read(dmic_dev, 0, &capture_buffer, &size, PDM_READ_TIMEOUT_MS);
		if (ret < 0) {
			(void)dmic_trigger(dmic_dev, DMIC_TRIGGER_STOP);
			(void)i2s_trigger(loopback_i2s_dev, I2S_DIR_TX, I2S_TRIGGER_DROP);
			return ret;
		}

		if (size != block_size) {
			k_mem_slab_free(&pdm_mem_slab, capture_buffer);
			(void)dmic_trigger(dmic_dev, DMIC_TRIGGER_STOP);
			(void)i2s_trigger(loopback_i2s_dev, I2S_DIR_TX, I2S_TRIGGER_DROP);
			return -EIO;
		}

		ret = k_mem_slab_alloc(&loopback_tx_slab, &tx_block, K_FOREVER);
		if (ret < 0) {
			k_mem_slab_free(&pdm_mem_slab, capture_buffer);
			(void)dmic_trigger(dmic_dev, DMIC_TRIGGER_STOP);
			(void)i2s_trigger(loopback_i2s_dev, I2S_DIR_TX, I2S_TRIGGER_DROP);
			return ret;
		}

		memcpy(tx_block, capture_buffer, size);
		k_mem_slab_free(&pdm_mem_slab, capture_buffer);

		ret = loopback_queue_block(tx_block, block_size, &started, &queued_blocks);
		if (ret < 0) {
			(void)dmic_trigger(dmic_dev, DMIC_TRIGGER_STOP);
			(void)i2s_trigger(loopback_i2s_dev, I2S_DIR_TX, I2S_TRIGGER_DROP);
			return ret;
		}
	}

	ret = dmic_trigger(dmic_dev, DMIC_TRIGGER_STOP);
	if (ret < 0) {
		(void)i2s_trigger(loopback_i2s_dev, I2S_DIR_TX, I2S_TRIGGER_DROP);
		return ret;
	}

	return loopback_finish(started, queued_blocks);
}
