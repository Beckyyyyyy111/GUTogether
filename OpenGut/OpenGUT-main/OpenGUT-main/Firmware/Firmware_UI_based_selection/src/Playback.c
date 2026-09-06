#include <errno.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include <zephyr/device.h>
#include <zephyr/drivers/i2s.h>
#include <zephyr/fs/fs.h>
#include <zephyr/kernel.h>
#include <zephyr/sys/util.h>

#include "Playback.h"
#include "SD.h"

#define PLAYBACK_OUTPUT_CHANNELS 2U
#define PLAYBACK_WORD_SIZE 16U
#define PLAYBACK_BLOCK_FRAMES 1024U
#define PLAYBACK_BLOCK_COUNT 4U
#define PLAYBACK_BYTES_PER_SAMPLE sizeof(int16_t)
#define PLAYBACK_BLOCK_SIZE \
	(PLAYBACK_BLOCK_FRAMES * PLAYBACK_OUTPUT_CHANNELS * PLAYBACK_BYTES_PER_SAMPLE)

K_MEM_SLAB_DEFINE_STATIC(playback_tx_slab,
			 PLAYBACK_BLOCK_SIZE,
			 PLAYBACK_BLOCK_COUNT,
			 4);

static const struct device *playback_i2s_dev;
static bool playback_initialized;
static int16_t wav_read_buffer[PLAYBACK_BLOCK_FRAMES * PLAYBACK_OUTPUT_CHANNELS];

struct wav_chunk_header {
	char id[4];
	uint32_t size;
};

struct wav_fmt_chunk {
	uint16_t format_type;
	uint16_t channels;
	uint32_t sample_rate;
	uint32_t byterate;
	uint16_t block_align;
	uint16_t bits_per_sample;
};

struct wav_info {
	uint16_t channels;
	uint32_t sample_rate;
	uint16_t bits_per_sample;
	uint32_t data_size;
};

static int playback_configure(uint32_t sample_rate)
{
	struct i2s_config i2s_cfg = {
		.word_size = PLAYBACK_WORD_SIZE,
		.channels = PLAYBACK_OUTPUT_CHANNELS,
		.format = I2S_FMT_DATA_FORMAT_I2S,
		.frame_clk_freq = sample_rate,
		.block_size = PLAYBACK_BLOCK_SIZE,
		.timeout = 2000,
		.options = I2S_OPT_FRAME_CLK_MASTER | I2S_OPT_BIT_CLK_MASTER,
		.mem_slab = &playback_tx_slab,
	};

	return i2s_configure(playback_i2s_dev, I2S_DIR_TX, &i2s_cfg);
}

static int playback_queue_block(void *tx_block, bool *started, uint32_t *queued_blocks)
{
	int ret = i2s_write(playback_i2s_dev, tx_block, PLAYBACK_BLOCK_SIZE);

	if (ret < 0) {
		k_mem_slab_free(&playback_tx_slab, tx_block);
		return ret;
	}

	*queued_blocks += 1U;
	if (!(*started) && (*queued_blocks >= 2U)) {
		ret = i2s_trigger(playback_i2s_dev, I2S_DIR_TX, I2S_TRIGGER_START);
		if (ret < 0) {
			return ret;
		}

		*started = true;
	}

	return 0;
}

static int playback_finish(bool started, uint32_t queued_blocks)
{
	int ret;

	if (!started && (queued_blocks == 0U)) {
		return 0;
	}

	if (!started) {
		ret = i2s_trigger(playback_i2s_dev, I2S_DIR_TX, I2S_TRIGGER_START);
		if (ret < 0) {
			(void)i2s_trigger(playback_i2s_dev, I2S_DIR_TX, I2S_TRIGGER_DROP);
			return ret;
		}
	}

	ret = i2s_trigger(playback_i2s_dev, I2S_DIR_TX, I2S_TRIGGER_DRAIN);
	if (ret < 0) {
		(void)i2s_trigger(playback_i2s_dev, I2S_DIR_TX, I2S_TRIGGER_DROP);
		return ret;
	}

	return 0;
}

static int wav_skip_bytes(struct fs_file_t *file, uint32_t size)
{
	if (size == 0U) {
		return 0;
	}

	return fs_seek(file, (off_t)size, FS_SEEK_CUR);
}

static int wav_parse_header(struct fs_file_t *file, struct wav_info *info)
{
	struct {
		char riff[4];
		uint32_t overall_size;
		char wave[4];
	} header;
	bool fmt_found = false;
	bool data_found = false;
	ssize_t bytes_read;

	bytes_read = fs_read(file, &header, sizeof(header));
	if (bytes_read != (ssize_t)sizeof(header)) {
		return -EIO;
	}

	if ((memcmp(header.riff, "RIFF", 4) != 0) ||
	    (memcmp(header.wave, "WAVE", 4) != 0)) {
		return -EINVAL;
	}

	memset(info, 0, sizeof(*info));

	while (!data_found) {
		struct wav_chunk_header chunk;
		int ret;

		bytes_read = fs_read(file, &chunk, sizeof(chunk));
		if (bytes_read == 0) {
			break;
		}

		if (bytes_read != (ssize_t)sizeof(chunk)) {
			return -EIO;
		}

		if (memcmp(chunk.id, "fmt ", 4) == 0) {
			struct wav_fmt_chunk fmt_chunk = {0};
			size_t bytes_to_read = MIN((size_t)chunk.size, sizeof(fmt_chunk));

			bytes_read = fs_read(file, &fmt_chunk, bytes_to_read);
			if (bytes_read != (ssize_t)bytes_to_read) {
				return -EIO;
			}

			if (chunk.size > bytes_to_read) {
				ret = wav_skip_bytes(file, chunk.size - (uint32_t)bytes_to_read);
				if (ret < 0) {
					return ret;
				}
			}

			if (fmt_chunk.format_type != 1U) {
				return -ENOTSUP;
			}

			info->channels = fmt_chunk.channels;
			info->sample_rate = fmt_chunk.sample_rate;
			info->bits_per_sample = fmt_chunk.bits_per_sample;
			fmt_found = true;
		} else if (memcmp(chunk.id, "data", 4) == 0) {
			info->data_size = chunk.size;
			data_found = true;
			break;
		} else {
			ret = wav_skip_bytes(file, chunk.size);
			if (ret < 0) {
				return ret;
			}
		}

		if ((chunk.size & 0x1U) != 0U) {
			ret = wav_skip_bytes(file, 1U);
			if (ret < 0) {
				return ret;
			}
		}
	}

	if (!fmt_found || !data_found) {
		return -EINVAL;
	}

	if ((info->sample_rate == 0U) ||
	    (info->bits_per_sample != 16U) ||
	    ((info->channels != 1U) && (info->channels != 2U))) {
		return -ENOTSUP;
	}

	return 0;
}

static void playback_convert_wav_to_stereo(int16_t *tx_block,
					   const int16_t *input_samples,
					   size_t input_frames,
					   uint16_t input_channels)
{
	size_t frame;

	if (input_channels == 2U) {
		for (frame = 0; frame < input_frames; ++frame) {
			tx_block[2U * frame] = input_samples[2U * frame];
			tx_block[(2U * frame) + 1U] = input_samples[(2U * frame) + 1U];
		}
	} else {
		for (frame = 0; frame < input_frames; ++frame) {
			tx_block[2U * frame] = input_samples[frame];
			tx_block[(2U * frame) + 1U] = input_samples[frame];
		}
	}

	for (; frame < PLAYBACK_BLOCK_FRAMES; ++frame) {
		tx_block[2U * frame] = 0;
		tx_block[(2U * frame) + 1U] = 0;
	}
}

int Playback_Init(void)
{
	if (playback_initialized) {
		return 0;
	}

	playback_i2s_dev = DEVICE_DT_GET(DT_ALIAS(i2s_tx));
	if (!device_is_ready(playback_i2s_dev)) {
		return -ENODEV;
	}

	playback_initialized = true;
	return 0;
}

int Playback_Play_Wav(const char *file_path, uint32_t sample_rate_hint)
{
	struct fs_file_t file;
	struct wav_info info;
	uint32_t data_remaining;
	uint32_t queued_blocks = 0U;
	bool started = false;
	int ret = Playback_Init();

	if (ret < 0) {
		return ret;
	}

	ret = SD_Init();
	if (ret < 0) {
		return ret;
	}

	fs_file_t_init(&file);
	ret = fs_open(&file, file_path, FS_O_READ);
	if (ret < 0) {
		return ret;
	}

	ret = wav_parse_header(&file, &info);
	if (ret < 0) {
		(void)fs_close(&file);
		return ret;
	}

	ARG_UNUSED(sample_rate_hint);

	ret = playback_configure(info.sample_rate);
	if (ret < 0) {
		(void)fs_close(&file);
		return ret;
	}

	data_remaining = info.data_size;

	while (data_remaining > 0U) {
		void *tx_block = NULL;
		uint32_t bytes_per_input_frame = info.channels * PLAYBACK_BYTES_PER_SAMPLE;
		uint32_t frames_to_read = MIN(PLAYBACK_BLOCK_FRAMES, data_remaining / bytes_per_input_frame);
		size_t bytes_to_read = frames_to_read * bytes_per_input_frame;
		ssize_t bytes_read;

		ret = k_mem_slab_alloc(&playback_tx_slab, &tx_block, K_FOREVER);
		if (ret < 0) {
			(void)fs_close(&file);
			(void)i2s_trigger(playback_i2s_dev, I2S_DIR_TX, I2S_TRIGGER_DROP);
			return ret;
		}

		bytes_read = fs_read(&file, wav_read_buffer, bytes_to_read);
		if (bytes_read < 0) {
			k_mem_slab_free(&playback_tx_slab, tx_block);
			(void)fs_close(&file);
			(void)i2s_trigger(playback_i2s_dev, I2S_DIR_TX, I2S_TRIGGER_DROP);
			return (int)bytes_read;
		}

		if (bytes_read == 0) {
			k_mem_slab_free(&playback_tx_slab, tx_block);
			break;
		}

		frames_to_read = (uint32_t)bytes_read / bytes_per_input_frame;
		playback_convert_wav_to_stereo((int16_t *)tx_block,
					       wav_read_buffer,
					       frames_to_read,
					       info.channels);

		ret = playback_queue_block(tx_block, &started, &queued_blocks);
		if (ret < 0) {
			(void)fs_close(&file);
			(void)i2s_trigger(playback_i2s_dev, I2S_DIR_TX, I2S_TRIGGER_DROP);
			return ret;
		}

		data_remaining -= (uint32_t)bytes_read;
	}

	ret = playback_finish(started, queued_blocks);
	if (ret < 0) {
		(void)fs_close(&file);
		return ret;
	}

	return fs_close(&file);
}
