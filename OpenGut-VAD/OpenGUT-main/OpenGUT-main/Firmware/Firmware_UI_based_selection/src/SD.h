#ifndef SD_H
#define SD_H

#include <stddef.h>

#define SD_INIT_ERR_DISK_ACCESS (-1001)
#define SD_INIT_ERR_MOUNT       (-1002)
#define SD_INIT_ERR_STATVFS     (-1003)

int SD_Init(void);
int SD_Read_File(const char *path, char *buffer, size_t buffer_size);

#endif /* SD_H */
