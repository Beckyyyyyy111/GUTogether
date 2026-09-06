#ifndef PDM_H
#define PDM_H

#include <stdint.h>
#include <stdbool.h>

typedef enum {
    PDM_MIC_LEFT = 0,
    PDM_MIC_RIGHT = 1,
} pdm_mic_t;

typedef bool (*pdm_stop_cb_t)(void *context);

int PDM_Record_Wav(pdm_mic_t mic, uint32_t duration_seconds);
int PDM_Record_Stereo_Wav(uint32_t duration_seconds);
int PDM_Record_Stereo_Wav_Until(pdm_stop_cb_t stop_cb, void *context);
int PDM_Live_Monitor(uint32_t duration_seconds);
int PDM_Live_Monitor_Until(pdm_stop_cb_t stop_cb, void *context);

#endif /* PDM_H */
