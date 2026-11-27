#include "network.h"
#include "printer.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <stdatomic.h>
#include "esp_log.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "esp_http_client.h"
#include "esp_crt_bundle.h"
#include "esp_sntp.h"
#include "esp_system.h"
#include "nvs.h"
#include "cJSON.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/event_groups.h"
static const char *TAG="QUEUE";
static EventGroupHandle_t events;
static nvs_handle_t store;
static char base[192], token[96];
static uint8_t target[6];
static atomic_bool config_ready, wifi_configured;
void setup_emit(const char *json){printf("\nMCJSON:%s\n",json);fflush(stdout);}
bool network_target(uint8_t out[6]) { if(!atomic_load(&config_ready))return false;memcpy(out,target,6);return true; }
static void wifi_event(void *arg,esp_event_base_t event,int32_t id,void *data) {
    if(event==IP_EVENT) xEventGroupSetBits(events,1);
    else if(id==WIFI_EVENT_STA_START && atomic_load(&wifi_configured)) esp_wifi_connect();
    else if(id==WIFI_EVENT_STA_DISCONNECTED) { xEventGroupClearBits(events,1); if(atomic_load(&wifi_configured))esp_wifi_connect(); }
}
static bool field(cJSON *obj,const char *key,char *out,size_t cap) {
    cJSON *v=cJSON_GetObjectItemCaseSensitive(obj,key);
    if(!cJSON_IsString(v)||strlen(v->valuestring)>=cap) return false;
    strcpy(out,v->valuestring); return true;
}
static bool parse_address(const char *address,uint8_t out[6]) {
    unsigned v[6];char extra;
    if(strlen(address)!=17 || sscanf(address,"%2x:%2x:%2x:%2x:%2x:%2x%c",&v[0],&v[1],&v[2],&v[3],&v[4],&v[5],&extra)!=6)return false;
    for(int i=0;i<6;i++){out[5-i]=v[i];}
    return true;
}
static void setup_command(cJSON *o){
    const cJSON *c=cJSON_GetObjectItem(o,"command");if(!cJSON_IsString(c))return;
    if(!strcmp(c->valuestring,"hello")){setup_emit("{\"event\":\"ready\",\"version\":2}");}
    else if(!strcmp(c->valuestring,"scan_wifi")){
        if(esp_wifi_scan_start(NULL,true)!=ESP_OK){setup_emit("{\"event\":\"error\",\"message\":\"Wi-Fi scan failed. Retry.\"}");return;}
        uint16_t count=24;wifi_ap_record_t aps[24];esp_wifi_scan_get_ap_records(&count,aps);
        cJSON *r=cJSON_CreateObject(),*items=cJSON_AddArrayToObject(r,"networks");cJSON_AddStringToObject(r,"event","wifi");
        for(int i=0;i<count;i++){if(!aps[i].ssid[0] || aps[i].authmode==WIFI_AUTH_WPA2_ENTERPRISE)continue;cJSON *n=cJSON_CreateObject();cJSON_AddStringToObject(n,"ssid",(char*)aps[i].ssid);cJSON_AddBoolToObject(n,"open",aps[i].authmode==WIFI_AUTH_OPEN);cJSON_AddItemToArray(items,n);}
        char *line=cJSON_PrintUnformatted(r);if(line){setup_emit(line);free(line);}cJSON_Delete(r);
    }else if(!strcmp(c->valuestring,"scan_printers")){
        if(!setup_printer_scan())setup_emit("{\"event\":\"error\",\"message\":\"Cannot scan now. Reset the ESP and retry.\"}");
    }else if(!strcmp(c->valuestring,"test")){
        char addr[18];uint8_t a[6];
        if(!field(o,"address",addr,sizeof addr)||!parse_address(addr,a)){setup_emit("{\"event\":\"error\",\"message\":\"Select a printer first.\"}");return;}
        setup_printer_select(a);
        for(int i=0;i<100&&!printer_connected();i++)vTaskDelay(pdMS_TO_TICKS(300));
        if(!printer_connected()){setup_emit("{\"event\":\"error\",\"message\":\"Printer did not connect. Turn it on and disconnect the phone app. Reset to try another printer.\"}");return;}
        uint8_t bitmap[48*96]={0};
        for(int y=0;y<96;y++)for(int x=0;x<384;x++)if(y<3||y>92||x<3||x>380||(x+y)%32<2)bitmap[y*48+x/8]|=1<<(x%8);
        setup_emit(printer_print(bitmap,sizeof bitmap)?"{\"event\":\"test_done\"}":"{\"event\":\"error\",\"message\":\"Test not confirmed. Check the printer before retrying.\"}");
    }
}
static bool load_config(char *ssid,char *password) {
    char json[512]={0};size_t len=sizeof json;
    bool saved=nvs_get_str(store,"config",json,&len)==ESP_OK;
    if(saved) { cJSON *old=cJSON_Parse(json); saved=old && cJSON_IsString(cJSON_GetObjectItem(old,"address"));cJSON_Delete(old); }
    ESP_LOGI(TAG,"Setup window: send configuration over USB now (20 seconds if already configured).");
    if(!saved) ESP_LOGI(TAG,"Provisioning needed: waiting for configuration. Credentials are not echoed.");
    setup_emit("{\"event\":\"ready\",\"version\":2}");
    bool guided=false;
    char incoming[512];size_t used=0;TickType_t start=xTaskGetTickCount();
    while(guided || !saved || used || xTaskGetTickCount()-start<pdMS_TO_TICKS(20000)) {
        int ch=getchar();
        if(ch==EOF) { clearerr(stdin);vTaskDelay(pdMS_TO_TICKS(50));continue; }
        if(ch=='\n') {
            incoming[used]=0;
            cJSON *command=cJSON_Parse(incoming);
            if(command && cJSON_HasObjectItem(command,"command")){
                char pending_job[40];size_t n=sizeof pending_job;
                if(nvs_get_str(store,"job",pending_job,&n)==ESP_OK){setup_emit("{\"event\":\"error\",\"message\":\"Resolve the pending print before setup.\"}");cJSON_Delete(command);used=0;continue;}
                guided=true;setup_command(command);cJSON_Delete(command);used=0;continue;
            }
            cJSON_Delete(command);
            char pending[40];size_t pending_len=sizeof pending;
            if(nvs_get_str(store,"job",pending,&pending_len)==ESP_OK) {ESP_LOGE(TAG,"Resolve the pending job before replacing configuration");return false;}
            incoming[used]=0;strcpy(json,incoming);break; }
        if(used>=sizeof(incoming)-1) return false;
        if(ch!='\r') incoming[used++]=ch;
    }
    cJSON *obj=cJSON_Parse(json);
    char address[18];
    bool ok=obj && field(obj,"address",address,sizeof address) && field(obj,"url",base,sizeof base) && field(obj,"token",token,sizeof token) && field(obj,"ssid",ssid,33) && field(obj,"password",password,65)
      && strncmp(base,"https://",8)==0 && strlen(token)>=32 && ssid[0];
    if(ok) {
        unsigned values[6];char extra;
        ok=strlen(address)==17 && sscanf(address,"%2x:%2x:%2x:%2x:%2x:%2x%c",&values[0],&values[1],&values[2],&values[3],&values[4],&values[5],&extra)==6;
        if(ok) for(int i=0;i<6;i++) target[5-i]=values[i];
    }
    cJSON_Delete(obj);
    if(ok) ok=nvs_set_str(store,"config",json)==ESP_OK && nvs_commit(store)==ESP_OK;
    memset(json,0,sizeof json);memset(incoming,0,sizeof incoming);
    if(ok) {atomic_store(&config_ready,true);ESP_LOGI(TAG,"Configuration saved");setup_emit("{\"event\":\"saved\"}");}
    return ok;
}
typedef struct { char job[40]; } headers_t;
static esp_err_t http_event(esp_http_client_event_t *event) {
    headers_t *h=event->user_data;
    if(event->event_id==HTTP_EVENT_ON_HEADER && !strcasecmp(event->header_key,"X-Job-ID")) {
        if(strlen(event->header_value)==36) strcpy(h->job,event->header_value);
    }
    return ESP_OK;
}
static int request(const char *path,const char *body,uint8_t **bytes,size_t *size,char *job) {
    char url[320],auth[104]; headers_t h={0};
    snprintf(url,sizeof url,"%s%s",base,path);snprintf(auth,sizeof auth,"Bearer %s",token);
    esp_http_client_config_t cfg={.url=url,.crt_bundle_attach=esp_crt_bundle_attach,.timeout_ms=15000,.disable_auto_redirect=true,.event_handler=http_event,.user_data=&h,.buffer_size=2048};
    esp_http_client_handle_t client=esp_http_client_init(&cfg);
    if(!client) return -1;
    esp_http_client_set_method(client,HTTP_METHOD_POST);
    esp_http_client_set_header(client,"Authorization",auth);
    esp_http_client_set_header(client,"Content-Type","application/json");
    int code=-1;size_t length=strlen(body);
    if(esp_http_client_open(client,length)!=ESP_OK) goto done;
    if(esp_http_client_write(client,body,length)!=(int)length) goto done;
    int64_t content=esp_http_client_fetch_headers(client);
    code=esp_http_client_get_status_code(client);
    if(code==200 && bytes) {
        if(content<4320 || content>48*4300 || content%48 || strlen(h.job)!=36) { code=-1;goto done; }
        for(int i=0;i<36;i++) if(!((h.job[i]>='0'&&h.job[i]<='9')||(h.job[i]>='a'&&h.job[i]<='f')||h.job[i]=='-')) {code=-1;goto done;}
        *bytes=malloc(content);if(!*bytes) {code=-1;goto done;}
        size_t used=0;
        while(used<(size_t)content) {
            int n=esp_http_client_read(client,(char*)*bytes+used,content-used);
            if(n<=0) {free(*bytes);*bytes=NULL;code=-1;goto done;} used+=n;
        }
        *size=used;strcpy(job,h.job);
    }
done:
    esp_http_client_close(client);esp_http_client_cleanup(client);return code;
}
static bool save_result(const char *job,const char *state) {
    return nvs_set_str(store,"job",job)==ESP_OK && nvs_set_str(store,"result",state)==ESP_OK && nvs_commit(store)==ESP_OK;
}
static void heartbeat_task(void *arg) {
    for(;;){
        xEventGroupWaitBits(events,1,pdFALSE,pdTRUE,portMAX_DELAY);
        if(time(NULL)>=1760000000)request("/api/device/heartbeat",printer_connected()?"{\"printer_connected\":true}":"{\"printer_connected\":false}",NULL,NULL,NULL);
        vTaskDelay(pdMS_TO_TICKS(5000));
    }
}
static void queue_task(void *arg) {
    ESP_ERROR_CHECK(nvs_open("queue",NVS_READWRITE,&store));
    events=xEventGroupCreate();
    ESP_ERROR_CHECK(esp_netif_init());ESP_ERROR_CHECK(esp_event_loop_create_default());esp_netif_create_default_wifi_sta();
    wifi_init_config_t init=WIFI_INIT_CONFIG_DEFAULT();ESP_ERROR_CHECK(esp_wifi_init(&init));
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT,ESP_EVENT_ANY_ID,wifi_event,NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT,IP_EVENT_STA_GOT_IP,wifi_event,NULL));
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));ESP_ERROR_CHECK(esp_wifi_start());
    char ssid[33],password[65];
    if(!load_config(ssid,password)) {ESP_LOGE(TAG,"Invalid provisioning; reset and try again");vTaskDelete(NULL);return;}
    wifi_config_t wifi={0};strcpy((char*)wifi.sta.ssid,ssid);strcpy((char*)wifi.sta.password,password);
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA,&wifi));atomic_store(&wifi_configured,true);ESP_ERROR_CHECK(esp_wifi_connect());
    esp_sntp_setoperatingmode(SNTP_OPMODE_POLL);esp_sntp_setservername(0,"pool.ntp.org");esp_sntp_init();
    configASSERT(xTaskCreate(heartbeat_task,"heartbeat",8192,NULL,3,NULL)==pdPASS);
    ESP_LOGI(TAG,"Wi-Fi started; waiting for Internet and clock before verified HTTPS");
    for(;;) {
        xEventGroupWaitBits(events,1,pdFALSE,pdTRUE,portMAX_DELAY);
        if(time(NULL)<1760000000) {vTaskDelay(pdMS_TO_TICKS(2000));continue;}
        char job[40]={0},result[16]={0};size_t len=sizeof job;
        if(nvs_get_str(store,"job",job,&len)==ESP_OK && job[0]) {
            len=sizeof result;
            if(nvs_get_str(store,"result",result,&len)!=ESP_OK) strcpy(result,"uncertain");
            char path[100],body[64];snprintf(path,sizeof path,"/api/device/jobs/%s/result",job);snprintf(body,sizeof body,"{\"state\":\"%s\"}",result);
            if(request(path,body,NULL,NULL,NULL)==200) {
                nvs_erase_key(store,"job");nvs_erase_key(store,"result");ESP_ERROR_CHECK(nvs_commit(store));
                ESP_LOGI(TAG,"Server recorded result: %s",result);
            }
        } else if(printer_connected()) {
            uint8_t *bitmap=NULL;size_t size=0;
            int status=request("/api/device/claim","{}",&bitmap,&size,job);
            if(status==200 && bitmap) {
                if(save_result(job,"uncertain")) {
                    ESP_LOGI(TAG,"Printing queued photo, %u rows",(unsigned)(size/48));
                    bool ok=printer_print(bitmap,size);
                    if(ok && !save_result(job,"printed")) ESP_LOGE(TAG,"Could not persist completion; outcome uncertain");
                }
                free(bitmap);
            } else if(status==204) ESP_LOGI(TAG,"Queue idle");
            else ESP_LOGW(TAG,"Queue HTTP status=%d",status);
        } else {
            /* Reconnect through the already verified discovery path, never replaying a saved job. */
            ESP_LOGW(TAG,"Printer disconnected; scanning to reconnect");
        }
        vTaskDelay(pdMS_TO_TICKS(3000));
    }
}
void network_start(void) {
    static bool started=false;
    if(!started) {started=true;configASSERT(xTaskCreate(queue_task,"queue",16384,NULL,4,NULL)==pdPASS);}
}
