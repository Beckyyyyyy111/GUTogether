#include <ctype.h>
#include <errno.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "SD.h"
#include "app_config.h"

#define CONFIG_PATH "/SD:/config.json"
#define CONFIG_BUFFER_SIZE 512

static void normalize_json(char *text)
{
	for (size_t i = 0; text[i] != '\0'; ++i) {
		text[i] = (char)tolower((unsigned char)text[i]);
	}
}

static int find_json_key(const char *json, const char *key, const char **value_start)
{
	char pattern[48];
	const char *match;

	(void)snprintf(pattern, sizeof(pattern), "\"%s\"", key);
	match = strstr(json, pattern);
	if (match == NULL) {
		return -ENOENT;
	}

	match = strchr(match + strlen(pattern), ':');
	if (match == NULL) {
		return -EINVAL;
	}

	++match;
	while ((*match != '\0') && isspace((unsigned char)*match)) {
		++match;
	}

	*value_start = match;
	return 0;
}

static int parse_json_bool(const char *json, const char *key, bool *value)
{
	const char *value_start;
	int ret = find_json_key(json, key, &value_start);

	if (ret < 0) {
		return ret;
	}

	if (strncmp(value_start, "true", 4) == 0) {
		*value = true;
		return 0;
	}

	if (strncmp(value_start, "false", 5) == 0) {
		*value = false;
		return 0;
	}

	return -EINVAL;
}

static int parse_json_u32(const char *json, const char *key, uint32_t *value)
{
	const char *value_start;
	unsigned long parsed_value;
	int ret = find_json_key(json, key, &value_start);

	if (ret < 0) {
		return ret;
	}

	if (!isdigit((unsigned char)*value_start)) {
		return -EINVAL;
	}

	parsed_value = strtoul(value_start, NULL, 10);
	*value = (uint32_t)parsed_value;
	return 0;
}

static int parse_json_string(const char *json, const char *key, char *buffer, size_t buffer_size)
{
	const char *value_start;
	const char *value_end;
	size_t value_length;
	int ret = find_json_key(json, key, &value_start);

	if (ret < 0) {
		return ret;
	}

	if (*value_start != '"') {
		return -EINVAL;
	}

	++value_start;
	value_end = strchr(value_start, '"');
	if (value_end == NULL) {
		return -EINVAL;
	}

	value_length = (size_t)(value_end - value_start);
	if (value_length >= buffer_size) {
		return -ENOSPC;
	}

	memcpy(buffer, value_start, value_length);
	buffer[value_length] = '\0';
	return 0;
}

static int parse_operation_mode(const char *json, app_mode_t *mode)
{
	bool recording = false;
	bool playback = false;
	bool loopback = false;
	int ret;

	ret = parse_json_bool(json, "recording", &recording);
	if (ret < 0) {
		return ret;
	}

	ret = parse_json_bool(json, "playback", &playback);
	if (ret < 0) {
		return ret;
	}

	ret = parse_json_bool(json, "loopback", &loopback);
	if (ret < 0) {
		return ret;
	}

	if ((recording ? 1 : 0) + (playback ? 1 : 0) + (loopback ? 1 : 0) != 1) {
		return -EINVAL;
	}

	if (recording) {
		*mode = APP_MODE_RECORD;
	} else if (playback) {
		*mode = APP_MODE_PLAYBACK;
	} else {
		*mode = APP_MODE_LOOPBACK;
	}

	return 0;
}

int App_Config_Load(app_config_t *config)
{
	char json[CONFIG_BUFFER_SIZE];
	int ret;

	if (config == NULL) {
		return -EINVAL;
	}

	memset(config, 0, sizeof(*config));

	ret = SD_Read_File(CONFIG_PATH, json, sizeof(json));
	if (ret < 0) {
		return ret;
	}

	normalize_json(json);

	ret = parse_operation_mode(json, &config->mode);
	if (ret < 0) {
		return ret;
	}

	ret = parse_json_u32(json, "sampling_rate", &config->sampling_rate);
	if (ret < 0) {
		return ret;
	}

	switch (config->mode) {
	case APP_MODE_LOOPBACK:
		return parse_json_u32(json, "duration", &config->loopback_duration_ms);
	case APP_MODE_PLAYBACK:
		return parse_json_string(json,
					 "audio_file_name",
					 config->audio_file_name,
					 sizeof(config->audio_file_name));
	case APP_MODE_RECORD:
		ret = parse_json_u32(json,
				     "recording_duration_seconds",
				     &config->recording_duration_seconds);
		if (ret < 0) {
			return ret;
		}

		return parse_json_string(json,
					 "file_name",
					 config->recording_file_name,
					 sizeof(config->recording_file_name));
	default:
		return -EINVAL;
	}
}
