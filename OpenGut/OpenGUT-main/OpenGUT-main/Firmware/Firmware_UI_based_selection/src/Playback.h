#ifndef PLAYBACK_H
#define PLAYBACK_H

#include <stdint.h>

int Playback_Init(void);
int Playback_Play_Wav(const char *file_path, uint32_t sample_rate_hint);

#endif /* PLAYBACK_H */
