// Console backend until the actual display controller, voltage and pinout are verified.
#include "status_model.h"
#include "esp_log.h"

void memory_display_init(void)
{
    ESP_LOGI("display", "Console backend: no display or LED GPIO configured");
}

void memory_display_render(const memory_status_t *status, bool fresh)
{
    if (!fresh) {
        ESP_LOGW("display", "MEMORY CLOUD | Server: no fresh data | Printer: unknown");
        return;
    }
    ESP_LOGI("display", "MEMORY CLOUD%s | Printer: %s | Queue: %u | %s | Job: %.8s",
        status->simulated ? " [SIMULATED]" : "", status->printer_online ? "online" : "offline",
        status->queued, status->state, status->job);
}
