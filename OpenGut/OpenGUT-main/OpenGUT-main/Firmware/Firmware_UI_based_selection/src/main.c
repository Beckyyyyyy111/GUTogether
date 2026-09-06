#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>

#include <zephyr/kernel.h>
#include <zephyr/sys/util.h>

#include "PDM.h"
#include "Playback.h"
#include "app_config.h"
#include "led.h"

#define STARTUP_HOLD_MS 3000U
#define STATUS_BLINK_ON_MS 150U
#define STATUS_BLINK_OFF_MS 150U

typedef struct {
	uint32_t duration_ms;
	int64_t started_at;
} timed_stop_context_t;

static volatile bool blink_active;
static volatile uint8_t blinking_led;
K_THREAD_STACK_DEFINE(status_blink_stack, 512);
static struct k_thread status_blink_thread;

static void status_blink_thread_entry(void *arg1, void *arg2, void *arg3)
{
	ARG_UNUSED(arg1);
	ARG_UNUSED(arg2);
	ARG_UNUSED(arg3);

	while (1) {
		if (blink_active) {
			(void)Led_Set_Only(blinking_led, start);
			k_sleep(K_MSEC(STATUS_BLINK_ON_MS));
			(void)Led_Set_Only(blinking_led, stop);
			k_sleep(K_MSEC(STATUS_BLINK_OFF_MS));
		} else {
			k_sleep(K_MSEC(20));
		}
	}
}

static void status_blink_start(uint8_t led_number)
{
	blinking_led = led_number;
	blink_active = true;
}

static void status_blink_stop(void)
{
	blink_active = false;
	k_sleep(K_MSEC(STATUS_BLINK_OFF_MS));
}

static bool timed_stop_requested(void *context)
{
	timed_stop_context_t *timed_context = context;

	if (timed_context == NULL) {
		return false;
	}

	return (k_uptime_get() - timed_context->started_at) >= timed_context->duration_ms;
}

static int run_loopback_mode(const app_config_t *config)
{
	timed_stop_context_t context = {
		.duration_ms = config->loopback_duration_ms,
		.started_at = k_uptime_get(),
	};

	status_blink_start(2U);
	return PDM_Live_Monitor_Until(config->sampling_rate,
				      timed_stop_requested,
				      &context);
}

static int run_playback_mode(const app_config_t *config)
{
	char file_path[80];

	(void)snprintf(file_path, sizeof(file_path), "/SD:/%s", config->audio_file_name);
	status_blink_start(3U);
	return Playback_Play_Wav(file_path, config->sampling_rate);
}

static int run_record_mode(const app_config_t *config)
{
	timed_stop_context_t context = {
		.duration_ms = (uint64_t)config->recording_duration_seconds * 1000U,
		.started_at = k_uptime_get(),
	};
	char file_path[80];

	(void)snprintf(file_path, sizeof(file_path), "/SD:/%s", config->recording_file_name);
	status_blink_start(1U);
	return PDM_Record_Stereo_Wav_Until(file_path,
					   config->sampling_rate,
					   timed_stop_requested,
					   &context);
}

static int run_configured_operation(const app_config_t *config)
{
	switch (config->mode) {
	case APP_MODE_RECORD:
		return run_record_mode(config);
	case APP_MODE_PLAYBACK:
		return run_playback_mode(config);
	case APP_MODE_LOOPBACK:
		return run_loopback_mode(config);
	default:
		return -EINVAL;
	}
}

int main(void)
{
	app_config_t config;
	int ret;

	(void)k_thread_create(&status_blink_thread,
			      status_blink_stack,
			      K_THREAD_STACK_SIZEOF(status_blink_stack),
			      status_blink_thread_entry,
			      NULL,
			      NULL,
			      NULL,
			      K_LOWEST_APPLICATION_THREAD_PRIO,
			      0,
			      K_NO_WAIT);

	ret = Led_Set_All(start);
	if (ret < 0) {
		Led_Blink_Forever(4U, STATUS_BLINK_ON_MS, STATUS_BLINK_OFF_MS);
	}

	k_sleep(K_MSEC(STARTUP_HOLD_MS));

	ret = App_Config_Load(&config);
	if (ret < 0) {
		Led_Blink_Forever(4U, STATUS_BLINK_ON_MS, STATUS_BLINK_OFF_MS);
	}

	ret = run_configured_operation(&config);
	status_blink_stop();
	if (ret < 0) {
		Led_Blink_Forever(4U, STATUS_BLINK_ON_MS, STATUS_BLINK_OFF_MS);
	}

	ret = Led_Set_All(start);
	if (ret < 0) {
		Led_Blink_Forever(4U, STATUS_BLINK_ON_MS, STATUS_BLINK_OFF_MS);
	}

	while (1) {
		k_sleep(K_SECONDS(1));
	}

	return 0;
}
