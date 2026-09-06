#ifndef PDM_H
#define PDM_H

#include <stdbool.h>
#include <stdint.h>

typedef bool (*pdm_stop_cb_t)(void *context);

int PDM_Record_Stereo_Wav_Until(const char *file_path,
				uint32_t sample_rate,
				pdm_stop_cb_t stop_cb,
				void *context);
int PDM_Live_Monitor_Until(uint32_t sample_rate,
			   pdm_stop_cb_t stop_cb,
			   void *context);

#endif /* PDM_H */
