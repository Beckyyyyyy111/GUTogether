#include <errno.h>
#include <stdbool.h>
#include <stddef.h>

#include <zephyr/device.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/kernel.h>

#include "led.h"

static const struct gpio_dt_spec leds[] = {
	GPIO_DT_SPEC_GET(DT_ALIAS(led0), gpios),
	GPIO_DT_SPEC_GET(DT_ALIAS(led1), gpios),
	GPIO_DT_SPEC_GET(DT_ALIAS(led2), gpios),
	GPIO_DT_SPEC_GET(DT_ALIAS(led3), gpios),
};

static bool leds_initialized;

static int led_index_from_number(uint8_t led_number, size_t *index)
{
	if ((led_number == 0U) || (led_number > ARRAY_SIZE(leds))) {
		return -EINVAL;
	}

	*index = led_number - 1U;
	return 0;
}

static int led_init(void)
{
	if (leds_initialized) {
		return 0;
	}

	for (size_t i = 0; i < ARRAY_SIZE(leds); ++i) {
		if (!gpio_is_ready_dt(&leds[i])) {
			return -ENODEV;
		}

		int ret = gpio_pin_configure_dt(&leds[i], GPIO_OUTPUT_INACTIVE);
		if (ret < 0) {
			return ret;
		}
	}

	leds_initialized = true;
	return 0;
}

int Led(uint8_t led_number, led_state_t state)
{
	size_t index;
	int ret = led_init();

	if (ret < 0) {
		return ret;
	}

	ret = led_index_from_number(led_number, &index);
	if (ret < 0) {
		return ret;
	}

	return gpio_pin_set_dt(&leds[index], state == start);
}

int Led_Set_Only(uint8_t led_number, led_state_t state)
{
	int ret = led_init();

	if (ret < 0) {
		return ret;
	}

	for (uint8_t current_led = 1U; current_led <= ARRAY_SIZE(leds); ++current_led) {
		ret = Led(current_led, (current_led == led_number) ? state : stop);
		if (ret < 0) {
			return ret;
		}
	}

	return 0;
}

int Led_Set_All(led_state_t state)
{
	int ret = led_init();

	if (ret < 0) {
		return ret;
	}

	for (uint8_t led_number = 1U; led_number <= ARRAY_SIZE(leds); ++led_number) {
		ret = Led(led_number, state);
		if (ret < 0) {
			return ret;
		}
	}

	return 0;
}

void Led_Blink_Forever(uint8_t led_number, uint32_t on_ms, uint32_t off_ms)
{
	while (1) {
		(void)Led_Set_Only(led_number, start);
		k_sleep(K_MSEC(on_ms));
		(void)Led_Set_Only(led_number, stop);
		k_sleep(K_MSEC(off_ms));
	}
}
