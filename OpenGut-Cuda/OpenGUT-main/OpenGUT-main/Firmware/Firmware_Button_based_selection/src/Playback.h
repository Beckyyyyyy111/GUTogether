#ifndef PLAYBACK_H
#define PLAYBACK_H

#include <stdint.h>

int Playback_Init(void);
int Playback_Play_Sine(uint32_t duration_seconds);
int Playback_Play_Wav(const char *file_path, uint32_t duration_seconds);

#endif /* PLAYBACK_H */
