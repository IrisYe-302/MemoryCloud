#pragma once
void network_start(void);

#include <stdbool.h>
#include <stdint.h>
bool network_target(uint8_t target[6]);

void setup_emit(const char *json);
bool setup_printer_scan(void);
void setup_printer_select(const uint8_t address[6]);
