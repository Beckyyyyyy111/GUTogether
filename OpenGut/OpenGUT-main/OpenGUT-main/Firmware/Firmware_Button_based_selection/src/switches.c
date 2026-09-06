#include <errno.h>
#include <stdbool.h>
#include <stddef.h>

#include <zephyr/device.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/kernel.h>
#include <zephyr/sys/atomic.h>

#include "switches.h"

#define SWITCH_DEBOUNCE_MS 20

static const struct gpio_dt_spec switches[] = {
    GPIO_DT_SPEC_GET(DT_ALIAS(sw0), gpios),
    GPIO_DT_SPEC_GET(DT_ALIAS(sw1), gpios),
};

static bool switches_initialized;
static struct gpio_callback switch_callbacks[ARRAY_SIZE(switches)];
static atomic_t switch_events;
static uint32_t last_press_ms[ARRAY_SIZE(switches)];

static int switch_index_from_number(uint8_t switch_number, size_t *index)
{
    if ((switch_number == 0U) || (switch_number > ARRAY_SIZE(switches))) {
        return -EINVAL;
    }

    *index = switch_number - 1U;
    return 0;
}

static void switch_pressed_isr(const struct device *port,
                               struct gpio_callback *callback,
                               gpio_port_pins_t pins)
{
    uint32_t now = k_uptime_get_32();

    for (size_t i = 0; i < ARRAY_SIZE(switches); ++i) {
        if ((switches[i].port == port) &&
            ((pins & BIT(switches[i].pin)) != 0U) &&
            (callback == &switch_callbacks[i])) {
            if ((now - last_press_ms[i]) >= SWITCH_DEBOUNCE_MS) {
                last_press_ms[i] = now;
                atomic_or(&switch_events, BIT(i));
            }
            return;
        }
    }
}

int Switches_Init(void)
{
    if (switches_initialized) {
        return 0;
    }

    for (size_t i = 0; i < ARRAY_SIZE(switches); ++i) {
        if (!gpio_is_ready_dt(&switches[i])) {
            return -ENODEV;
        }

        int ret = gpio_pin_configure_dt(&switches[i], GPIO_INPUT);
        if (ret < 0) {
            return ret;
        }

        ret = gpio_pin_interrupt_configure_dt(&switches[i],
                                              GPIO_INT_EDGE_TO_ACTIVE);
        if (ret < 0) {
            return ret;
        }

        gpio_init_callback(&switch_callbacks[i],
                           switch_pressed_isr,
                           BIT(switches[i].pin));

        ret = gpio_add_callback(switches[i].port, &switch_callbacks[i]);
        if (ret < 0) {
            return ret;
        }
    }

    switches_initialized = true;
    return 0;
}

bool Switch_Pressed(uint8_t switch_number)
{
    size_t index;
    int ret = Switches_Init();
    atomic_val_t value;

    if (ret < 0) {
        return false;
    }

    ret = switch_index_from_number(switch_number, &index);
    if (ret < 0) {
        return false;
    }

    value = atomic_and(&switch_events, ~BIT(index));
    if ((value & BIT(index)) == 0) {
        return false;
    }

    return true;
}

bool Switch_Is_Down(uint8_t switch_number)
{
    size_t index;
    int ret = Switches_Init();
    int value;

    if (ret < 0) {
        return false;
    }

    ret = switch_index_from_number(switch_number, &index);
    if (ret < 0) {
        return false;
    }

    value = gpio_pin_get_dt(&switches[index]);
    if (value < 0) {
        return false;
    }

    return value != 0;
}

void Switches_Clear_All(void)
{
    (void)atomic_set(&switch_events, 0);
}
