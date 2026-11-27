#pragma once
#include <stdbool.h>
#include <stdint.h>

typedef struct {
    unsigned queued;
    bool printer_online;
    bool simulated;
    char state[16];
    char job[37];
    int64_t received_us;
} memory_status_t;

bool memory_status_parse(const char *json, int64_t now_us, memory_status_t *out);
void memory_display_init(void);
void memory_display_render(const memory_status_t *status, bool fresh);
