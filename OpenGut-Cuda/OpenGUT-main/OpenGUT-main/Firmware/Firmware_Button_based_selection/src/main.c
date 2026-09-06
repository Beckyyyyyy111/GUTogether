#include <stdint.h>
#include <stdbool.h>
#include <errno.h>

#include <zephyr/kernel.h>
#include <mdk/nrf52840.h>

#include "PDM.h"
#include "Playback.h"
#include "led.h"
#include "swicthes.h"

#define STARTUP_LED_ON_MS 500U
#define ERROR_BLINK_ON_MS 150U
#define ERROR_BLINK_OFF_MS 250U
#define STATUS_BLINK_ON_MS 150U
#define STATUS_BLINK_OFF_MS 150U
#define MODE_FLASH_COUNT 3U
#define MODE_FLASH_ON_MS 150U
#define MODE_FLASH_OFF_MS 150U
#define SW1_SHORT_PRESS 1U
#define SW1_LONG_PRESS 2U
#define SW1_LONG_PRESS_MS 700U
#define SWITCH_POLL_MS 20U
#define VDD_OUTPUT_TARGET (UICR_REGOUT0_VOUT_3V0 << UICR_REGOUT0_VOUT_Pos)

typedef enum {
    MODE_RECORD_STEREO = 0,
    MODE_LIVE_MONITOR,
    MODE_PLAY_LOUD,
    MODE_PLAY_MEDIUM,
    MODE_COUNT,
} app_mode_t;

static volatile bool blink_active;
static volatile uint8_t blinking_led;
K_THREAD_STACK_DEFINE(status_blink_stack, 512);
static struct k_thread status_blink_thread;

static void nvmc_wait_ready(void)
{
    while (NRF_NVMC->READY == NVMC_READY_READY_Busy) {
    }
}

static int configure_vdd_output_3v0(void)
{
    uint32_t regout0 = NRF_UICR->REGOUT0;
    uint32_t current_vdd = regout0 & UICR_REGOUT0_VOUT_Msk;

    if (current_vdd == VDD_OUTPUT_TARGET) {
        return 0;
    }

    /*
     * UICR writes can only clear bits from 1 to 0. Moving from a lower
     * voltage code to 3.0 V would require erasing the full UICR page, which
     * we avoid here because it can affect unrelated configuration.
     */
    if ((current_vdd & VDD_OUTPUT_TARGET) != VDD_OUTPUT_TARGET) {
        return -ENOTSUP;
    }

    nvmc_wait_ready();
    NRF_NVMC->CONFIG = NVMC_CONFIG_WEN_Wen << NVMC_CONFIG_WEN_Pos;
    nvmc_wait_ready();

    NRF_UICR->REGOUT0 = (regout0 & ~UICR_REGOUT0_VOUT_Msk) | VDD_OUTPUT_TARGET;
    nvmc_wait_ready();

    NRF_NVMC->CONFIG = NVMC_CONFIG_WEN_Ren << NVMC_CONFIG_WEN_Pos;
    nvmc_wait_ready();

    NVIC_SystemReset();
    return 0;
}

static int led_set_only(uint8_t led_number, led_state_t state)
{
    for (uint8_t current_led = 1U; current_led <= 4U; ++current_led) {
        int ret = Led(current_led,
                      (current_led == led_number) ? state : stop);
        if (ret < 0) {
            return ret;
        }
    }

    return 0;
}

static int set_all_leds(led_state_t state)
{
    for (uint8_t led_number = 1U; led_number <= 4U; ++led_number) {
        int ret = Led(led_number, state);
        if (ret < 0) {
            return ret;
        }
    }

    return 0;
}

static void status_blink_thread_entry(void *arg1, void *arg2, void *arg3)
{
    ARG_UNUSED(arg1);
    ARG_UNUSED(arg2);
    ARG_UNUSED(arg3);

    while (1) {
        if (blink_active) {
            (void)led_set_only(blinking_led, start);
            k_sleep(K_MSEC(STATUS_BLINK_ON_MS));
            (void)led_set_only(blinking_led, stop);
            k_sleep(K_MSEC(STATUS_BLINK_OFF_MS));
        } else {
            k_sleep(K_MSEC(SWITCH_POLL_MS));
        }
    }
}

static void status_blink_start(uint8_t led_number)
{
    blinking_led = led_number;
    blink_active = true;
}

static int status_blink_stop_and_show_mode(uint8_t led_number)
{
    blink_active = false;

    /*
     * Let the blink thread finish any in-flight off transition before
     * leaving the completion indication latched on.
     */
    k_sleep(K_MSEC(STATUS_BLINK_OFF_MS));

    blinking_led = led_number;
    return led_set_only(led_number, start);
}

static int show_selected_mode(app_mode_t mode)
{
    blinking_led = (uint8_t)mode + 1U;
    return led_set_only(blinking_led, start);
}

static int flash_selected_mode(app_mode_t mode, uint32_t flash_count)
{
    uint8_t led_number = (uint8_t)mode + 1U;

    for (uint32_t flash = 0U; flash < flash_count; ++flash) {
        int ret = Led(led_number, start);
        if (ret < 0) {
            return ret;
        }

        k_sleep(K_MSEC(MODE_FLASH_ON_MS));

        ret = Led(led_number, stop);
        if (ret < 0) {
            return ret;
        }

        k_sleep(K_MSEC(MODE_FLASH_OFF_MS));
    }

    return show_selected_mode(mode);
}

static void wait_for_switch_release(uint8_t switch_number)
{
    while (Switch_Is_Down(switch_number)) {
        k_sleep(K_MSEC(SWITCH_POLL_MS));
    }
}

static uint8_t read_sw1_action(void)
{
    uint32_t pressed_ms = 0U;

    while (Switch_Is_Down(1U)) {
        k_sleep(K_MSEC(SWITCH_POLL_MS));
        pressed_ms += SWITCH_POLL_MS;
    }

    return (pressed_ms >= SW1_LONG_PRESS_MS) ? SW1_LONG_PRESS : SW1_SHORT_PRESS;
}

static app_mode_t next_mode(app_mode_t mode)
{
    return (app_mode_t)(((uint32_t)mode + 1U) % MODE_COUNT);
}

static app_mode_t previous_mode(app_mode_t mode)
{
    return (app_mode_t)(((uint32_t)mode + MODE_COUNT - 1U) % MODE_COUNT);
}

static bool live_monitor_stop_requested(void *context)
{
    ARG_UNUSED(context);
    return Switch_Pressed(2U);
}

static bool record_stop_requested(void *context)
{
    ARG_UNUSED(context);
    return Switch_Pressed(2U);
}

static int run_record_mode(void)
{
    int ret;

    Switches_Clear_All();
    wait_for_switch_release(2U);

    status_blink_start(1U);
    ret = PDM_Record_Stereo_Wav_Until(record_stop_requested, NULL);
    if (ret < 0) {
        return ret;
    }

    ret = status_blink_stop_and_show_mode(1U);
    if (ret < 0) {
        return ret;
    }

    return flash_selected_mode(MODE_RECORD_STEREO, MODE_FLASH_COUNT);
}

static int run_live_monitor_mode(void)
{
    int ret;

    Switches_Clear_All();
    wait_for_switch_release(2U);

    status_blink_start(2U);
    ret = PDM_Live_Monitor_Until(live_monitor_stop_requested, NULL);
    if (ret < 0) {
        return ret;
    }

    return status_blink_stop_and_show_mode(2U);
}

static int run_playback_mode(app_mode_t mode, const char *file_path)
{
    int ret;
    uint8_t led_number = (uint8_t)mode + 1U;

    Switches_Clear_All();
    wait_for_switch_release(2U);

    status_blink_start(led_number);
    ret = Playback_Play_Wav(file_path, 0U);
    if (ret < 0) {
        return ret;
    }

    ret = status_blink_stop_and_show_mode(led_number);
    if (ret < 0) {
        return ret;
    }

    return flash_selected_mode(mode, MODE_FLASH_COUNT);
}

static void fatal_error_loop(uint8_t led_number)
{
    while (1) {
        (void)Led(led_number, start);
        k_sleep(K_MSEC(ERROR_BLINK_ON_MS));
        (void)Led(led_number, stop);
        k_sleep(K_MSEC(ERROR_BLINK_OFF_MS));
    }
}

int main(void)
{
    int ret;
    app_mode_t mode = MODE_RECORD_STEREO;

    ret = configure_vdd_output_3v0();
    if (ret < 0) {
        return ret;
    }

    (void)k_thread_create(&status_blink_thread,
                          status_blink_stack,
                          K_THREAD_STACK_SIZEOF(status_blink_stack),
                          status_blink_thread_entry,
                          NULL,
                          NULL,
                          NULL,
                          K_LOWEST_APPLICATION_THREAD_PRIO,
                          0,
                          K_NO_WAIT);

    ret = set_all_leds(start);

    if (ret < 0) {
        return ret;
    }

    k_sleep(K_MSEC(STARTUP_LED_ON_MS));

    ret = set_all_leds(stop);
    if (ret < 0) {
        return ret;
    }

    ret = Switches_Init();
    if (ret < 0) {
        fatal_error_loop(1U);
    }

    Switches_Clear_All();

    while (1) {
        ret = show_selected_mode(mode);
        if (ret < 0) {
            fatal_error_loop((uint8_t)mode + 1U);
        }

        if (Switch_Pressed(2U)) {
            wait_for_switch_release(2U);

            switch (mode) {
            case MODE_RECORD_STEREO:
                ret = run_record_mode();
                break;
            case MODE_LIVE_MONITOR:
                ret = run_live_monitor_mode();
                break;
            case MODE_PLAY_LOUD:
                ret = run_playback_mode(mode, "/SD:/loud.wav");
                break;
            case MODE_PLAY_MEDIUM:
                ret = run_playback_mode(mode, "/SD:/medium.wav");
                break;
            default:
                ret = -EINVAL;
                break;
            }

            if (ret < 0) {
                fatal_error_loop((uint8_t)mode + 1U);
            }

            Switches_Clear_All();
            continue;
        }

        if (Switch_Pressed(1U)) {
            uint8_t action;

            action = read_sw1_action();
            mode = (action == SW1_LONG_PRESS) ? previous_mode(mode) : next_mode(mode);
            Switches_Clear_All();
        }

        k_sleep(K_MSEC(SWITCH_POLL_MS));
    }
}
