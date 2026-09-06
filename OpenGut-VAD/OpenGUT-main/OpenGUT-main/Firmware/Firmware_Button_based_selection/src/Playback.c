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

#define PLAYBACK_DEFAULT_WAV_FILE_PATH "/SD:/loud.wav"
#define PLAYBACK_SAMPLE_NO 64U
#define PLAYBACK_OUTPUT_CHANNELS 2U
#define PLAYBACK_WORD_SIZE 16U
#define PLAYBACK_SINE_SAMPLE_RATE 44100U
#define PLAYBACK_SINE_ATTENUATION 1U
#define PLAYBACK_BLOCK_FRAMES 1024U
#define PLAYBACK_BLOCK_COUNT 4U
#define PLAYBACK_BYTES_PER_SAMPLE sizeof(int16_t)
#define PLAYBACK_BLOCK_SIZE \
    (PLAYBACK_BLOCK_FRAMES * PLAYBACK_OUTPUT_CHANNELS * PLAYBACK_BYTES_PER_SAMPLE)

static int16_t sine_data[PLAYBACK_SAMPLE_NO] = {
      3211,   6392,   9511,  12539,  15446,  18204,  20787,  23169,
     25329,  27244,  28897,  30272,  31356,  32137,  32609,  32767,
     32609,  32137,  31356,  30272,  28897,  27244,  25329,  23169,
     20787,  18204,  15446,  12539,   9511,   6392,   3211,      0,
     -3212,  -6393,  -9512, -12540, -15447, -18205, -20788, -23170,
    -25330, -27245, -28898, -30273, -31357, -32138, -32610, -32767,
    -32610, -32138, -31357, -30273, -28898, -27245, -25330, -23170,
    -20788, -18205, -15447, -12540,  -9512,  -6393,  -3212,     -1,
};

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

static void playback_fill_sine_block(int16_t *tx_block, uint32_t start_frame)
{
    for (size_t frame = 0; frame < PLAYBACK_BLOCK_FRAMES; ++frame) {
        size_t left_index = (start_frame + frame) % ARRAY_SIZE(sine_data);
        size_t right_index = (left_index + (ARRAY_SIZE(sine_data) / 4U)) % ARRAY_SIZE(sine_data);

        tx_block[2U * frame] = sine_data[left_index] / (1 << PLAYBACK_SINE_ATTENUATION);
        tx_block[(2U * frame) + 1U] = sine_data[right_index] / (1 << PLAYBACK_SINE_ATTENUATION);
    }
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

int Playback_Play_Sine(uint32_t duration_seconds)
{
    uint32_t total_frames;
    uint32_t frames_generated = 0U;
    uint32_t start_frame = 0U;
    uint32_t queued_blocks = 0U;
    bool started = false;
    int ret = Playback_Init();

    if (ret < 0) {
        return ret;
    }

    if (duration_seconds == 0U) {
        return -EINVAL;
    }

    ret = playback_configure(PLAYBACK_SINE_SAMPLE_RATE);
    if (ret < 0) {
        return ret;
    }

    total_frames = duration_seconds * PLAYBACK_SINE_SAMPLE_RATE;

    while (frames_generated < total_frames) {
        void *tx_block = NULL;
        uint32_t frames_this_block = MIN(PLAYBACK_BLOCK_FRAMES, total_frames - frames_generated);

        ret = k_mem_slab_alloc(&playback_tx_slab, &tx_block, K_FOREVER);
        if (ret < 0) {
            (void)i2s_trigger(playback_i2s_dev, I2S_DIR_TX, I2S_TRIGGER_DROP);
            return ret;
        }

        playback_fill_sine_block((int16_t *)tx_block, start_frame);
        if (frames_this_block < PLAYBACK_BLOCK_FRAMES) {
            int16_t *samples = (int16_t *)tx_block;

            for (uint32_t frame = frames_this_block; frame < PLAYBACK_BLOCK_FRAMES; ++frame) {
                samples[2U * frame] = 0;
                samples[(2U * frame) + 1U] = 0;
            }
        }

        ret = playback_queue_block(tx_block, &started, &queued_blocks);
        if (ret < 0) {
            (void)i2s_trigger(playback_i2s_dev, I2S_DIR_TX, I2S_TRIGGER_DROP);
            return ret;
        }

        frames_generated += frames_this_block;
        start_frame = (start_frame + frames_this_block) % ARRAY_SIZE(sine_data);
    }

    return playback_finish(started, queued_blocks);
}

int Playback_Play_Wav(const char *file_path, uint32_t duration_seconds)
{
    struct fs_file_t file;
    struct wav_info info;
    uint32_t data_remaining;
    uint32_t max_frames;
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
    ret = fs_open(&file,
                  (file_path != NULL) ? file_path : PLAYBACK_DEFAULT_WAV_FILE_PATH,
                  FS_O_READ);
    if (ret < 0) {
        return ret;
    }

    ret = wav_parse_header(&file, &info);
    if (ret < 0) {
        (void)fs_close(&file);
        return ret;
    }

    ret = playback_configure(info.sample_rate);
    if (ret < 0) {
        (void)fs_close(&file);
        return ret;
    }

    data_remaining = info.data_size;
    max_frames = duration_seconds * info.sample_rate;

    if ((duration_seconds != 0U) &&
        (max_frames < (data_remaining / (info.channels * PLAYBACK_BYTES_PER_SAMPLE)))) {
        data_remaining = max_frames * info.channels * PLAYBACK_BYTES_PER_SAMPLE;
    }

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
