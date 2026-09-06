#ifndef LED_H
#define LED_H

#include <stdint.h>

typedef enum {
	stop = 0,
	start = 1,
} led_state_t;

int Led(uint8_t led_number, led_state_t state);
int Led_Set_Only(uint8_t led_number, led_state_t state);
int Led_Set_All(led_state_t state);
void Led_Blink_Forever(uint8_t led_number, uint32_t on_ms, uint32_t off_ms);

#endif /* LED_H */
