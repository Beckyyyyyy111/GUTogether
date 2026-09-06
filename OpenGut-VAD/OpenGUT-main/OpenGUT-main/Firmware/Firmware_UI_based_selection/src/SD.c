#include <errno.h>

#include <ff.h>
#include <zephyr/fs/fs.h>
#include <zephyr/storage/disk_access.h>

#include "SD.h"

#define SD_DISK_NAME "SD"
#define SD_MOUNT_POINT "/SD:"

static int sd_ready;
static FATFS fat_fs;
static struct fs_mount_t sd_mount = {
	.type = FS_FATFS,
	.mnt_point = SD_MOUNT_POINT,
	.fs_data = &fat_fs,
	.storage_dev = (void *)SD_DISK_NAME,
	.flags = FS_MOUNT_FLAG_USE_DISK_ACCESS,
};

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

int SD_Read_File(const char *path, char *buffer, size_t buffer_size)
{
	struct fs_file_t file;
	ssize_t bytes_read;
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

	bytes_read = fs_read(&file, buffer, buffer_size - 1U);
	if (bytes_read < 0) {
		(void)fs_close(&file);
		return (int)bytes_read;
	}

	buffer[bytes_read] = '\0';

	ret = fs_close(&file);
	if (ret < 0) {
		return ret;
	}

	return (int)bytes_read;
}
