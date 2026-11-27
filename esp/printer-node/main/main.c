/* Memory Cloud BLE discovery and explicit console-triggered print test. */
#include <string.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include "cJSON.h"
#include "printer.h"
#include "network.h"
#include "esp_system.h"
#include "esp_log.h"
#include "nvs_flash.h"
#include "nimble/nimble_port.h"
#include "nimble/nimble_port_freertos.h"
#include "host/ble_hs.h"
#include "host/util/util.h"

static const char *TAG = "PRINTER_TEST";
/* NimBLE stores the bytes of a Bluetooth address least-significant first. */
static uint8_t target[6];
static struct { uint16_t start, end; } services[32];
static unsigned service_count, service_index;
static uint16_t connection_handle;
static uint8_t own_type;
static uint16_t control, notify, data, notify_end;
static bool connecting, completed;
static atomic_bool setup_scanning, host_ready, target_ready;
static int gap_event(struct ble_gap_event *event, void *arg);
static void discover_next(void);

static void stop_test(const char *reason)
{
    ESP_LOGI(TAG, "%s", reason);
    completed = true;
    int rc = ble_gap_terminate(connection_handle, BLE_ERR_REM_USER_CONN_TERM);
    if (rc) ESP_LOGW(TAG, "Disconnect request rc=%d", rc);
}

static int characteristic_found(uint16_t conn, const struct ble_gatt_error *error,
                                const struct ble_gatt_chr *chr, void *arg)
{
    if (error->status == 0) {
        if(notify && !notify_end && chr->def_handle>notify) notify_end=chr->def_handle-1;
        uint16_t id=ble_uuid_u16(&chr->uuid.u);
        if(id==0xae01 && (chr->properties&4)) control=chr->val_handle;
        if(id==0xae02 && (chr->properties&16)) notify=chr->val_handle;
        if(id==0xae03 && (chr->properties&4)) data=chr->val_handle;
        char uuid[BLE_UUID_STR_LEN];
        ble_uuid_to_str(&chr->uuid.u, uuid);
        ESP_LOGI(TAG, "  CHARACTERISTIC %s value_handle=%u properties=0x%02x", uuid, chr->val_handle, chr->properties);
        return 0;
    }
    if (error->status != BLE_HS_EDONE) {
        ESP_LOGE(TAG, "Characteristic discovery failed: %d", error->status);
        stop_test("TEST INCOMPLETE. Reset board to retry.");
        return 0;
    }
    service_index++;
    discover_next();
    return 0;
}

static void discover_next(void)
{
    if (service_index >= service_count) {
        printer_prepare(connection_handle,control,notify,data,notify_end);
        return;
    }
    ESP_LOGI(TAG, "Inspecting service handles %u..%u",services[service_index].start,services[service_index].end);
    int rc=ble_gattc_disc_all_chrs(connection_handle,services[service_index].start,
                                 services[service_index].end,characteristic_found,NULL);
    if (rc) {
        ESP_LOGE(TAG,"Could not start characteristic discovery: %d",rc);
        stop_test("TEST INCOMPLETE.");
    }
}

static int service_found(uint16_t conn, const struct ble_gatt_error *error,
                         const struct ble_gatt_svc *svc, void *arg)
{
    if (error->status == 0) {
        char uuid[BLE_UUID_STR_LEN];
        ble_uuid_to_str(&svc->uuid.u,uuid);
        ESP_LOGI(TAG,"SERVICE %s handles=%u..%u",uuid,svc->start_handle,svc->end_handle);
        if (service_count >= 32) {
            stop_test("Too many services; TEST INCOMPLETE.");
            return BLE_HS_ENOMEM;
        }
        services[service_count].start=svc->start_handle;
        services[service_count++].end=svc->end_handle;
        return 0;
    }
    if (error->status != BLE_HS_EDONE) {
        ESP_LOGE(TAG,"Service discovery failed: %d",error->status);
        stop_test("TEST INCOMPLETE.");
        return 0;
    }
    discover_next();
    return 0;
}

static int mtu_exchanged(uint16_t conn, const struct ble_gatt_error *error, uint16_t mtu, void *arg)
{
    ESP_LOGI(TAG,"MTU exchange status=%d mtu=%u",error->status,mtu);
    int rc=ble_gattc_disc_all_svcs(conn,service_found,NULL);
    if(rc) stop_test("Service discovery could not start.");
    return 0;
}

static int gap_event(struct ble_gap_event *event, void *arg)
{
    switch (event->type) {
    case BLE_GAP_EVENT_DISC:
        if(atomic_load(&setup_scanning)) {
            struct ble_hs_adv_fields fields={0};
            if(!ble_hs_adv_parse_fields(&fields,event->disc.data,event->disc.length_data) && fields.name_len==5 && !memcmp(fields.name,"MXW01",5)) {
                char address[18];const uint8_t *a=event->disc.addr.val;
                snprintf(address,sizeof address,"%02X:%02X:%02X:%02X:%02X:%02X",a[5],a[4],a[3],a[2],a[1],a[0]);
                cJSON *o=cJSON_CreateObject();cJSON_AddStringToObject(o,"event","printer");cJSON_AddStringToObject(o,"name","MXW01");cJSON_AddStringToObject(o,"address",address);cJSON_AddNumberToObject(o,"rssi",event->disc.rssi);
                char *line=cJSON_PrintUnformatted(o);if(line){setup_emit(line);free(line);}cJSON_Delete(o);
            }
            return 0;
        }
        if (connecting || memcmp(event->disc.addr.val,target,6)!=0) return 0;
        ESP_LOGI(TAG,"FOUND configured printer RSSI=%d address_type=%u",event->disc.rssi,event->disc.addr.type);
        connecting=true;
        int rc=ble_gap_disc_cancel();
        if (!rc) rc=ble_gap_connect(own_type,&event->disc.addr,30000,NULL,gap_event,NULL);
        if (rc) {connecting=false;ESP_LOGE(TAG,"Connection could not start: %d; will retry.",rc);}
        return 0;
    case BLE_GAP_EVENT_DISC_COMPLETE:
        if(atomic_exchange(&setup_scanning,false)) setup_emit("{\"event\":\"printers_done\"}");
        return 0;
    case BLE_GAP_EVENT_CONNECT:
        if (event->connect.status) {
            ESP_LOGE(TAG,"BLE connection failed: %d. Restarting.",event->connect.status);
            connecting=false;
            return 0;
        }
        connection_handle=event->connect.conn_handle;
        ESP_LOGI(TAG,"CONNECTED via BLE. Discovering services...");
        rc=ble_gattc_exchange_mtu(connection_handle,mtu_exchanged,NULL);
        if (rc) { ESP_LOGE(TAG,"Service discovery start failed: %d",rc); stop_test("TEST INCOMPLETE."); }
        return 0;
    case BLE_GAP_EVENT_NOTIFY_RX:
        printer_notification(event); return 0;
    case BLE_GAP_EVENT_DISCONNECT:
        printer_disconnected();connecting=false;service_count=service_index=0;control=notify=data=notify_end=0;
        ESP_LOGI(TAG,"Disconnected reason=%d; completed=%s",event->disconnect.reason,completed?"yes":"no");
        return 0;
    default:
        return 0;
    }
}

bool setup_printer_scan(void) {
    if(!atomic_load(&host_ready) || connecting || printer_connected()) return false;
    ble_gap_disc_cancel();atomic_store(&setup_scanning,true);
    struct ble_gap_disc_params scan={0};scan.filter_duplicates=1;
    if(ble_gap_disc(own_type,6000,&scan,gap_event,NULL)){atomic_store(&setup_scanning,false);return false;}
    return true;
}
void setup_printer_select(const uint8_t address[6]) {
    ble_gap_disc_cancel();atomic_store(&setup_scanning,false);
    memcpy(target,address,6);atomic_store(&target_ready,true);
}
static void configured_scan(void *arg)
{
    int rc=ble_hs_util_ensure_addr(0);
    if(!rc)rc=ble_hs_id_infer_auto(0,&own_type);
    if(rc){vTaskDelete(NULL);return;}
    atomic_store(&host_ready,true);
    for(;;){
        if(!atomic_load(&target_ready) && network_target(target))atomic_store(&target_ready,true);
        if(atomic_load(&target_ready) && !atomic_load(&setup_scanning) && !connecting && !printer_connected() && !ble_gap_disc_active()){
            struct ble_gap_disc_params scan={0};scan.filter_duplicates=1;
            ble_gap_disc(own_type,6000,&scan,gap_event,NULL);
        }
        vTaskDelay(pdMS_TO_TICKS(500));
    }
}
static void synced(void) { configASSERT(xTaskCreate(configured_scan,"scan",4096,NULL,4,NULL)==pdPASS); }
static void reset(int reason) { ESP_LOGE(TAG,"BLE host reset: %d",reason); }
static void host_task(void *arg) { nimble_port_run(); nimble_port_freertos_deinit(); }

void app_main(void)
{
    ESP_LOGI(TAG,"Memory Cloud ESP32-S3 BLE test — authenticated Wi-Fi queue worker; no LCD GPIO.");
    /* Preserve existing NVS; report initialization errors instead of erasing it. */
    ESP_ERROR_CHECK(nvs_flash_init());
    ESP_ERROR_CHECK(nimble_port_init());
    ESP_ERROR_CHECK(ble_att_set_preferred_mtu(128));
    ble_hs_cfg.sync_cb=synced;
    ble_hs_cfg.reset_cb=reset;
    esp_log_level_set("NimBLE",ESP_LOG_WARN);
    nimble_port_freertos_init(host_task);
    network_start();
}
