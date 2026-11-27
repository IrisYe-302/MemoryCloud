// AI-assisted ESP-IDF scaffold. Single display owner; network/serial producers pass snapshots.
#include "status_model.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "esp_timer.h"
#include "esp_log.h"
#include <stdio.h>
#include <string.h>

static QueueHandle_t snapshots;

static void status_input(void *arg)
{
#if CONFIG_MEMORY_DEMO
    const char *samples[] = {
        "{\"version\":1,\"queued\":0,\"printer_online\":true,\"simulated\":true,\"state\":\"idle\",\"job\":\"\"}",
        "{\"version\":1,\"queued\":2,\"printer_online\":false,\"simulated\":true,\"state\":\"queued\",\"job\":\"demo-1\"}",
        "{\"version\":1,\"queued\":1,\"printer_online\":true,\"simulated\":true,\"state\":\"sending\",\"job\":\"demo-1\"}",
        "{\"version\":1,\"queued\":0,\"printer_online\":true,\"simulated\":true,\"state\":\"printed\",\"job\":\"demo-1\"}",
        "{\"version\":1,\"queued\":0,\"printer_online\":false,\"simulated\":true,\"state\":\"uncertain\",\"job\":\"demo-2\"}"
    };
    for (;;) {
        for (unsigned i=0; i<sizeof(samples)/sizeof(samples[0]); ++i) {
            memory_status_t status;
            if (memory_status_parse(samples[i],esp_timer_get_time(),&status)) xQueueOverwrite(snapshots,&status);
            vTaskDelay(pdMS_TO_TICKS(4000));
        }
        // Deliberately exercise stale status rather than showing a false 'ready'.
        vTaskDelay(pdMS_TO_TICKS((CONFIG_MEMORY_STALE_SECONDS+2)*1000));
    }
#else
    char line[512];
    size_t used=0;
    bool overflow=false;
    for (;;) {
        int ch=getchar();
        if(ch==EOF){clearerr(stdin);vTaskDelay(pdMS_TO_TICKS(20));continue;}
        if(ch=='\n'){
            line[used]='\0';
            memory_status_t status;
            if(!overflow && memory_status_parse(line,esp_timer_get_time(),&status)) xQueueOverwrite(snapshots,&status);
            else ESP_LOGW("status","Rejected invalid or oversized message");
            used=0;overflow=false;
        } else if(used<sizeof(line)-1) line[used++]=(char)ch;
        else overflow=true;
    }
#endif
}

void app_main(void)
{
    snapshots=xQueueCreate(1,sizeof(memory_status_t));
    configASSERT(snapshots);
    memory_display_init();
    configASSERT(xTaskCreate(status_input,"status_input",4096,NULL,4,NULL)==pdPASS);
    memory_status_t status={0};
    bool had_status=false, last_fresh=false;
    memory_display_render(&status,false);
    for (;;) {
        bool changed=xQueueReceive(snapshots,&status,pdMS_TO_TICKS(1000))==pdTRUE;
        had_status |= changed;
        bool fresh=had_status && esp_timer_get_time()-status.received_us < (int64_t)CONFIG_MEMORY_STALE_SECONDS*1000000;
        if(changed || fresh!=last_fresh) memory_display_render(&status,fresh);
        last_fresh=fresh;
    }
}
