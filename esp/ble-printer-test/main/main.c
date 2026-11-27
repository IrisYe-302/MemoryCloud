/* Memory Cloud BLE discovery and explicit console-triggered print test. */
#include <string.h>
#include <stdio.h>
#include "sdkconfig.h"
#include "printer.h"
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
        if (connecting || memcmp(event->disc.addr.val,target,6)!=0) return 0;
        ESP_LOGI(TAG,"FOUND configured MXW01 target RSSI=%d address_type=%u",event->disc.rssi,event->disc.addr.type);
        connecting=true;
        int rc=ble_gap_disc_cancel();
        if (!rc) rc=ble_gap_connect(own_type,&event->disc.addr,30000,NULL,gap_event,NULL);
        if (rc) ESP_LOGE(TAG,"Connection could not start: %d. Reset to retry.",rc);
        return 0;
    case BLE_GAP_EVENT_DISC_COMPLETE:
        if (!connecting) ESP_LOGW(TAG,"SCAN FINISHED: target not found. Power printer on, disconnect phone/Pi Bluetooth, then reset ESP.");
        return 0;
    case BLE_GAP_EVENT_CONNECT:
        if (event->connect.status) {
            ESP_LOGE(TAG,"BLE connection failed: %d. Reset board to retry.",event->connect.status);
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
        printer_disconnected();
        ESP_LOGI(TAG,"Disconnected reason=%d; completed=%s",event->disconnect.reason,completed?"yes":"no");
        return 0;
    default:
        return 0;
    }
}

static void synced(void)
{
    int rc=ble_hs_util_ensure_addr(0);
    if (!rc) rc=ble_hs_id_infer_auto(0,&own_type);
    if (rc) { ESP_LOGE(TAG,"Address setup failed: %d",rc); return; }
    struct ble_gap_disc_params scan={0};
    scan.passive=0;
    scan.filter_duplicates=1;
    ESP_LOGI(TAG,"Scanning BLE for the configured printer for 30 seconds. No nearby device list spam.");
    rc=ble_gap_disc(own_type,30000,&scan,gap_event,NULL);
    if (rc) ESP_LOGE(TAG,"Scan start failed: %d",rc);
}
static void reset(int reason) { ESP_LOGE(TAG,"BLE host reset: %d",reason); }
static void host_task(void *arg) { nimble_port_run(); nimble_port_freertos_deinit(); }

void app_main(void)
{
    unsigned address[6];
    const char *configured = CONFIG_MEMORY_TEST_PRINTER_ADDRESS;
    if (strlen(configured) != 17 || sscanf(configured,"%2x:%2x:%2x:%2x:%2x:%2x",
        &address[0],&address[1],&address[2],&address[3],&address[4],&address[5]) != 6) {
        ESP_LOGE(TAG,"Set a Bluetooth printer address in menuconfig → Memory Cloud BLE test");
        return;
    }
    for (unsigned i=0;i<6;i++) target[5-i]=(uint8_t)address[i];
    ESP_LOGI(TAG,"Memory Cloud ESP32-S3 BLE test — console-triggered print test, no Wi-Fi, no LCD GPIO.");
    /* Preserve existing NVS; report initialization errors instead of erasing it. */
    ESP_ERROR_CHECK(nvs_flash_init());
    ESP_ERROR_CHECK(nimble_port_init());
    ESP_ERROR_CHECK(ble_att_set_preferred_mtu(128));
    ble_hs_cfg.sync_cb=synced;
    ble_hs_cfg.reset_cb=reset;
    nimble_port_freertos_init(host_task);
}
