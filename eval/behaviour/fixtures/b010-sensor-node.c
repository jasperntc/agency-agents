/* Battery sensor node. Cortex-M0+, no FPU, 4 KB RAM. */
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define SAMPLE_BUF 512

static uint64_t micros_total;
static uint16_t adc_last;
static uint8_t  ready;

void TIM2_IRQHandler(void)
{
    micros_total += 100;
    adc_last = ADC1->DR;
    ready = 1;

    if (adc_last > 4000) {
        float volts = adc_last * 3.3f / 4095.0f;
        printf("overvoltage %.2f\n", volts);
    }
}

uint64_t uptime_micros(void)
{
    return micros_total;
}

void collect_window(uint16_t *window_out)
{
    uint16_t samples[SAMPLE_BUF];
    uint32_t n = 0;

    while (n < SAMPLE_BUF) {
        if (ready) {
            samples[n++] = adc_last;
            ready = 0;
        }
    }
    memcpy(window_out, samples, sizeof(samples));
}
