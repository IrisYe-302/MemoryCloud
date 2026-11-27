/* MXW01 protocol: https://github.com/jeremy46231/MXW01-catprinter/blob/main/PROTOCOL.md
 * Explicit console-triggered, single-attempt hardware test; never retries a job. */
#include "printer.h"
#include "transfer.h"
#include "network.h"
#include <stdio.h>
#include <string.h>
#include <stdatomic.h>
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
static const char *TAG="MXW01";
static uint16_t connection, control_handle, notify_handle, data_handle, cccd;
static atomic_bool connected;
static QueueHandle_t responses;
typedef struct { uint8_t command, length, payload[64]; } reply_t;
static uint8_t crc8(const uint8_t *p, size_t n) {
    uint8_t crc=0;
    while(n--) { crc^=*p++; for(int i=0;i<8;i++) crc=(crc&0x80)?(crc<<1)^7:crc<<1; }
    return crc;
}
static bool command(uint8_t cmd, const uint8_t *payload, size_t length) {
    uint8_t frame[20]={0x22,0x21,cmd,0,(uint8_t)length,0};
    if(length>12 || !atomic_load(&connected)) return false;
    memcpy(frame+6,payload,length); frame[6+length]=crc8(payload,length); frame[7+length]=0xff;
    int rc=ble_gattc_write_no_rsp_flat(connection,control_handle,frame,length+8);
    ESP_LOGI(TAG,"TX command %02x rc=%d",cmd,rc);
    return rc==0;
}
void printer_notification(struct ble_gap_event *event) {
    if(!responses || event->notify_rx.attr_handle!=notify_handle) return;
    uint8_t raw[80]; size_t n=OS_MBUF_PKTLEN(event->notify_rx.om);
    if(n>sizeof raw || os_mbuf_copydata(event->notify_rx.om,0,n,raw)) return;
    ESP_LOG_BUFFER_HEX_LEVEL(TAG,raw,n,ESP_LOG_INFO);
    if(n<7 || raw[0]!=0x22 || raw[1]!=0x21) return;
    size_t len=raw[4]|(raw[5]<<8);
    if(len>64) return;
    /* Compact MXW01 replies end in 00; older variants use FF or CRC+FF. */
    if(n!=len+7 && n!=len+8) return;
    if((n==len+7 && raw[n-1]!=0 && raw[n-1]!=0xff) ||
       (n==len+8 && (raw[n-1]!=0xff || raw[len+6]!=crc8(raw+6,len)))) {
        ESP_LOGW(TAG,"Rejected malformed response"); return;
    }
    reply_t reply={.command=raw[2],.length=len}; memcpy(reply.payload,raw+6,len);
    if(xQueueSend(responses,&reply,0)!=pdTRUE) ESP_LOGE(TAG,"Response queue full");
}
void printer_disconnected(void) { atomic_store(&connected,false); }
static bool await_reply(uint8_t cmd, reply_t *reply, unsigned ms) {
    TickType_t start=xTaskGetTickCount(), timeout=pdMS_TO_TICKS(ms);
    while(atomic_load(&connected) && xTaskGetTickCount()-start<timeout) {
        if(xQueueReceive(responses,reply,pdMS_TO_TICKS(100)) && reply->command==cmd) return true;
    }
    ESP_LOGE(TAG,"No response for %02x (timeout or disconnected)",cmd); return false;
}
static enum transfer_write send_data(const uint8_t *data,size_t size,void *context){
    if(!atomic_load(&connected))return TRANSFER_FAILED;
    int rc=ble_gattc_write_no_rsp_flat(connection,data_handle,data,size);
    if(!rc)return TRANSFER_ACCEPTED;
    if(rc==BLE_HS_ENOMEM || rc==BLE_HS_EAGAIN || rc==BLE_HS_EBUSY){
        ESP_LOGW(TAG,"BLE buffer busy rc=%d; backing off before retrying unaccepted packet",rc);
        return TRANSFER_RETRY;
    }
    ESP_LOGE(TAG,"Data write failed rc=%d; no print replay",rc);return TRANSFER_FAILED;
}
static void transfer_sleep(unsigned ms,void *context){vTaskDelay(pdMS_TO_TICKS(ms));}
static void transfer_log(size_t sent,size_t total,void *context){
    ESP_LOGI(TAG,"Raster progress: %u/%u bytes (%u/%u rows)",(unsigned)sent,(unsigned)total,(unsigned)(sent/48),(unsigned)(total/48));
}
bool printer_print(const uint8_t *bitmap, size_t size) {
    if(!bitmap || size%48 || size<4320 || size>48*4300) return false;
    if(ble_att_mtu(connection)<51) { ESP_LOGE(TAG,"ATT MTU too small for 48-byte raster rows"); return false; }
    reply_t r; uint8_t zero=0, intensity=0x5d, request[]={(size/48)&255,(size/48)>>8,0x30,0};
    xQueueReset(responses);
    if(!command(0xa1,&zero,1) || !await_reply(0xa1,&r,7000)) return false;
    if(r.length!=10) { ESP_LOGE(TAG,"Unrecognized status layout; refusing print"); return false; }
    ESP_LOGI(TAG,"State=%u supply=%u temperature=%u error=%u paper=%u",r.payload[0],r.payload[3],r.payload[4],r.payload[6],r.payload[9]);
    if(r.payload[9] || r.payload[0] || r.payload[6]) { ESP_LOGE(TAG,"Printer not ready or no paper; no image sent"); return false; }
    if(!command(0xa2,&intensity,1)) return false;
    vTaskDelay(pdMS_TO_TICKS(100));
    if(!command(0xa9,request,4) || !await_reply(0xa9,&r,7000) || !r.length || r.payload[0]) return false;
    ESP_LOGI(TAG,"Sending full raster: width=384 height=%u bytes=%u",(unsigned)(size/48),(unsigned)size);
    if(!transfer_image(bitmap,size,send_data,transfer_sleep,transfer_log,NULL)){
        ESP_LOGE(TAG,"Raster transfer incomplete; marking outcome uncertain, never replaying automatically");return false;
    }
    if(!command(0xad,&zero,1) || !await_reply(0xaa,&r,180000)) return false;
    uint8_t expected=crc8(bitmap,size);
    if(r.length!=3 || r.payload[0] || r.payload[1]!=expected || r.payload[2]!=expected) {
        ESP_LOGE(TAG,"Completion checksum mismatch or unknown layout; expected %02x",expected); return false;
    }
    ESP_LOGI(TAG,"PRINT COMPLETE with matching image checksum. Notification received. Check the paper to verify output.");
    return true;
}
static int subscribed(uint16_t conn,const struct ble_gatt_error *error,struct ble_gatt_attr *attr,void *arg) {
    if(error->status) { ESP_LOGE(TAG,"Subscribe failed %d",error->status); return 0; }
    atomic_store(&connected,true);
    ESP_LOGI(TAG,"Printer ready for queue jobs");
    return 0;
}
static int descriptor(uint16_t conn,const struct ble_gatt_error *error,uint16_t val,const struct ble_gatt_dsc *dsc,void *arg) {
    if(!error->status) { if(ble_uuid_u16(&dsc->uuid.u)==0x2902) cccd=dsc->handle; return 0; }
    if(error->status!=BLE_HS_EDONE || !cccd) { ESP_LOGE(TAG,"Missing notification descriptor"); return 0; }
    uint8_t enable[]={1,0};
    int rc=ble_gattc_write_flat(connection,cccd,enable,2,subscribed,NULL);
    if(rc) ESP_LOGE(TAG,"Subscribe start failed %d",rc);
    return 0;
}
void printer_prepare(uint16_t conn,uint16_t control,uint16_t notify,uint16_t data,uint16_t end) {
    if(!control||!notify||!data||end<=notify) { ESP_LOGE(TAG,"Required characteristics missing"); return; }
    connection=conn;control_handle=control;notify_handle=notify;data_handle=data;
    cccd=0;
    if(!responses)responses=xQueueCreate(16,sizeof(reply_t));
    if(!responses)return;
    xQueueReset(responses);
    int rc=ble_gattc_disc_all_dscs(conn,notify,end,descriptor,NULL);
    if(rc) ESP_LOGE(TAG,"Descriptor discovery start failed %d",rc);
}

bool printer_connected(void) { return atomic_load(&connected); }
