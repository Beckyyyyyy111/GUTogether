#include <errno.h>
#include <string.h>

#include <ff.h>
#include <zephyr/fs/fs.h>
#include <zephyr/kernel.h>
#include <zephyr/storage/disk_access.h>

#include "led.h"
#include "SD.h"

#define SD_DISK_NAME "SD"
#define SD_MOUNT_POINT "/SD:"
#define SD_HELLO_PATH SD_MOUNT_POINT "/hello.txt"
#define SD_STATUS_BLINK_MS 150

static const char hello_text[] =
    "Hello from OpenGUTv1.\r\n"
    "This file was written by the firmware to verify SD card access.\r\n";

static int sd_ready;
static FATFS fat_fs;
static struct fs_mount_t sd_mount = {
    .type = FS_FATFS,
    .mnt_point = SD_MOUNT_POINT,
    .fs_data = &fat_fs,
    .storage_dev = (void *)SD_DISK_NAME,
    .flags = FS_MOUNT_FLAG_USE_DISK_ACCESS,
};

static int set_all_leds(led_state_t state)
{
    for (uint8_t led_number = 1U; led_number <= 4U; ++led_number) {
        int ret = Led(led_number, state);
        if (ret < 0) {
            return ret;
        }
    }

    return 0;
}

static int blink_status_once(void)
{
    int ret = set_all_leds(start);

    if (ret < 0) {
        return ret;
    }

    k_sleep(K_MSEC(SD_STATUS_BLINK_MS));

    ret = set_all_leds(stop);
    if (ret < 0) {
        return ret;
    }

    k_sleep(K_MSEC(SD_STATUS_BLINK_MS));

    return 0;
}

int SD_Init(void)
{
    struct fs_statvfs stat;
    int ret;

    if (sd_ready == 1) {
        return 0;
    }

    ret = disk_access_init(SD_DISK_NAME);
    if (ret < 0) {
        return SD_INIT_ERR_DISK_ACCESS;
    }

    ret = fs_mount(&sd_mount);
    if ((ret < 0) && (ret != -EBUSY)) {
        return SD_INIT_ERR_MOUNT;
    }

    ret = fs_statvfs(SD_MOUNT_POINT, &stat);
    if (ret < 0) {
        return SD_INIT_ERR_STATVFS;
    }

    sd_ready = 1;
    return 0;
}

int SD_Write_Hello_File(void)
{
    struct fs_file_t file;
    int ret = SD_Init();

    if (ret < 0) {
        return ret;
    }

    fs_file_t_init(&file);

    ret = fs_open(&file, SD_HELLO_PATH, FS_O_CREATE | FS_O_WRITE | FS_O_TRUNC);
    if (ret < 0) {
        return ret;
    }

    ret = fs_write(&file, hello_text, strlen(hello_text));
    if (ret < 0) {
        (void)fs_close(&file);
        return ret;
    }

    if ((size_t)ret != strlen(hello_text)) {
        (void)fs_close(&file);
        return -ENOSPC;
    }

    ret = fs_sync(&file);
    if (ret < 0) {
        (void)fs_close(&file);
        return ret;
    }

    ret = fs_close(&file);
    if (ret < 0) {
        return ret;
    }

    return 0;
}

int SD_Write_Hello_File_With_Led_Status(void)
{
    int ret;

    for (uint8_t i = 0U; i < 3U; ++i) {
        ret = blink_status_once();
        if (ret < 0) {
            return ret;
        }
    }

    ret = SD_Write_Hello_File();
    if (ret < 0) {
        return ret;
    }

    return set_all_leds(start);
}

int SD_Read_File(const char *path, char *buffer, size_t buffer_size)
{
    struct fs_file_t file;
    int ret = SD_Init();

    if (ret < 0) {
        return ret;
    }

    if ((path == NULL) || (buffer == NULL) || (buffer_size == 0U)) {
        return -EINVAL;
    }

    fs_file_t_init(&file);

    ret = fs_open(&file, path, FS_O_READ);
    if (ret < 0) {
        return ret;
    }

    ret = fs_read(&file, buffer, buffer_size - 1U);
    if (ret < 0) {
        (void)fs_close(&file);
        return ret;
    }

    buffer[ret] = '\0';

    if (fs_close(&file) < 0) {
        return -EIO;
    }

    return ret;
}
