#ifndef APP_CONFIG_H
#define APP_CONFIG_H

#include <stdint.h>

typedef enum {
	APP_MODE_RECORD = 0,
	APP_MODE_PLAYBACK,
	APP_MODE_LOOPBACK,
} app_mode_t;

typedef struct {
	app_mode_t mode;
	uint32_t sampling_rate;
	uint32_t loopback_duration_ms;
	uint32_t recording_duration_seconds;
	char audio_file_name[64];
	char recording_file_name[64];
} app_config_t;

int App_Config_Load(app_config_t *config);

#endif /* APP_CONFIG_H */
