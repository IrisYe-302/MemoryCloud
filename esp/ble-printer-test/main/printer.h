#pragma once
#include "host/ble_hs.h"
void printer_prepare(uint16_t conn, uint16_t control, uint16_t notify, uint16_t data, uint16_t notify_end);
void printer_notification(struct ble_gap_event *event);
void printer_disconnected(void);
