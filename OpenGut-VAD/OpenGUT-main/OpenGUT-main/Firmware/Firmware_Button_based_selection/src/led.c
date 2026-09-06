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

int Led_Blink(uint8_t led_number, uint32_t duration_ms)
{
    int ret = Led(led_number, start);

    if (ret < 0) {
        return ret;
    }

    k_sleep(K_MSEC(duration_ms));

    return Led(led_number, stop);
}
