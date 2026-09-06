#ifndef LED_H
#define LED_H

#include <stdint.h>

typedef enum {
    stop = 0,
    start = 1,
} led_state_t;

int Led(uint8_t led_number, led_state_t state);
int Led_Blink(uint8_t led_number, uint32_t duration_ms);

#endif /* LED_H */
