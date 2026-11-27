// AI-assisted, conditional ST7789 backend. Enable only after controller/board verification.
#include "status_model.h"
#include <ctype.h>
#include <stdio.h>
#include <string.h>
#include "driver/gpio.h"
#include "driver/spi_master.h"
#include "esp_lcd_panel_io.h"
#include "esp_lcd_panel_ops.h"
#include "esp_lcd_panel_vendor.h"
#include "esp_lcd_panel_st7789.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

#define WIDTH 170
#define HEIGHT 320
static uint16_t *pixels;
static esp_lcd_panel_handle_t panel;
static SemaphoreHandle_t flushed;
// Original compact 3x5 bitmap alphabet, enlarged for the small status screen.
static const char letters[]="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789:- ";
static const uint8_t glyphs[][5]={
 {2,5,7,5,5},{6,5,6,5,6},{3,4,4,4,3},{6,5,5,5,6},{7,4,6,4,7},
 {7,4,6,4,4},{3,4,5,5,3},{5,5,7,5,5},{7,2,2,2,7},{1,1,1,5,2},
 {5,5,6,5,5},{4,4,4,4,7},{5,7,7,5,5},{5,7,7,7,5},{2,5,5,5,2},
 {6,5,6,4,4},{2,5,5,3,1},{6,5,6,5,5},{3,4,2,1,6},{7,2,2,2,2},
 {5,5,5,5,7},{5,5,5,5,2},{5,5,7,7,5},{5,5,2,5,5},{5,5,2,2,2},
 {7,1,2,4,7},{7,5,5,5,7},{2,6,2,2,7},{6,1,2,4,7},{6,1,2,1,6},
 {5,5,7,1,1},{7,4,6,1,6},{3,4,6,5,2},{7,1,2,2,2},{2,5,2,5,2},
 {2,5,3,1,6},{0,2,0,2,0},{0,0,7,0,0},{0,0,0,0,0}
};

static uint16_t wire_color(uint16_t rgb565){return (rgb565>>8)|(rgb565<<8);}
static void text(int x,int y,const char *value,uint16_t color)
{
    for(;*value && x+6<WIDTH;value++,x+=8){
        const char *ch=strchr(letters,toupper((unsigned char)*value));
        if(!ch)continue;
        const uint8_t *rows=glyphs[ch-letters];
        for(int r=0;r<5;r++)for(int c=0;c<3;c++)if(rows[r]&(4>>c))
            for(int dy=0;dy<2;dy++)for(int dx=0;dx<2;dx++)
                if(y+r*2+dy<HEIGHT)pixels[(y+r*2+dy)*WIDTH+x+c*2+dx]=wire_color(color);
    }
}

static bool transfer_done(esp_lcd_panel_io_handle_t io,esp_lcd_panel_io_event_data_t *event,void *ctx)
{
    BaseType_t wake=pdFALSE;
    xSemaphoreGiveFromISR(flushed,&wake);
    return wake==pdTRUE;
}

void memory_display_init(void)
{
    int pins[]={CONFIG_MEMORY_LCD_SCLK,CONFIG_MEMORY_LCD_MOSI,CONFIG_MEMORY_LCD_RESET,
        CONFIG_MEMORY_LCD_DC,CONFIG_MEMORY_LCD_CS,CONFIG_MEMORY_LCD_BLK};
    for(unsigned i=0;i<6;i++){
        if(i==5 && pins[i]==-1)continue;
        if(!GPIO_IS_VALID_OUTPUT_GPIO(pins[i])){
            ESP_LOGE("display","Set valid board-specific LCD pins in menuconfig first");
            ESP_ERROR_CHECK(ESP_ERR_INVALID_ARG);
        }
        for(unsigned j=0;j<i;j++)if(pins[j]==pins[i])ESP_ERROR_CHECK(ESP_ERR_INVALID_ARG);
    }
    if(CONFIG_MEMORY_LCD_BLK>=0){
        ESP_ERROR_CHECK(gpio_set_direction(CONFIG_MEMORY_LCD_BLK,GPIO_MODE_OUTPUT));
        ESP_ERROR_CHECK(gpio_set_level(CONFIG_MEMORY_LCD_BLK,0));
    }
    pixels=heap_caps_calloc(WIDTH*HEIGHT,sizeof(uint16_t),MALLOC_CAP_DMA|MALLOC_CAP_INTERNAL);
    flushed=xSemaphoreCreateBinary();
    configASSERT(pixels && flushed);
    spi_bus_config_t bus={.sclk_io_num=pins[0],.mosi_io_num=pins[1],.miso_io_num=-1,
        .quadwp_io_num=-1,.quadhd_io_num=-1,.max_transfer_sz=WIDTH*HEIGHT*2};
    ESP_ERROR_CHECK(spi_bus_initialize(SPI2_HOST,&bus,SPI_DMA_CH_AUTO));
    esp_lcd_panel_io_handle_t io;
    esp_lcd_panel_io_spi_config_t cfg={.dc_gpio_num=pins[3],.cs_gpio_num=pins[4],
        .pclk_hz=10000000,.lcd_cmd_bits=8,.lcd_param_bits=8,.spi_mode=0,.trans_queue_depth=1};
    ESP_ERROR_CHECK(esp_lcd_new_panel_io_spi(SPI2_HOST,&cfg,&io));
    esp_lcd_panel_io_callbacks_t callbacks={.on_color_trans_done=transfer_done};
    ESP_ERROR_CHECK(esp_lcd_panel_io_register_event_callbacks(io,&callbacks,NULL));
    esp_lcd_panel_dev_config_t dev={.reset_gpio_num=pins[2],.bits_per_pixel=16,
#if CONFIG_MEMORY_LCD_BGR
        .rgb_ele_order=LCD_RGB_ELEMENT_ORDER_BGR
#else
        .rgb_ele_order=LCD_RGB_ELEMENT_ORDER_RGB
#endif
    };
    ESP_ERROR_CHECK(esp_lcd_new_panel_st7789(io,&dev,&panel));
    ESP_ERROR_CHECK(esp_lcd_panel_reset(panel));
    ESP_ERROR_CHECK(esp_lcd_panel_init(panel));
    ESP_ERROR_CHECK(esp_lcd_panel_set_gap(panel,CONFIG_MEMORY_LCD_X_GAP,0));
#if CONFIG_MEMORY_LCD_INVERT
    ESP_ERROR_CHECK(esp_lcd_panel_invert_color(panel,true));
#endif
    ESP_ERROR_CHECK(esp_lcd_panel_disp_on_off(panel,true));
    if(CONFIG_MEMORY_LCD_BLK>=0)ESP_ERROR_CHECK(gpio_set_level(CONFIG_MEMORY_LCD_BLK,1));
}

void memory_display_render(const memory_status_t *s,bool fresh)
{
    memset(pixels,0,WIDTH*HEIGHT*sizeof(uint16_t));
    text(10,18,"MEMORY CLOUD",0xffff);
    if(s->simulated)text(10,40,"SIMULATED",0xffe0);
    text(10,76,fresh?"SERVER CONNECTED":"SERVER STALE",fresh?0x9e73:0xfcc0);
    text(10,104,!fresh?"PRINTER UNKNOWN":s->printer_online?"PRINTER ONLINE":"PRINTER OFFLINE",0xffff);
    if(fresh){
        char count[24];snprintf(count,sizeof(count),"QUEUED: %u",s->queued);
        text(10,142,count,0xffff);text(10,180,s->state,0xffe0);
        text(10,216,"JOB",0x9e73);char job[9];snprintf(job,sizeof(job),"%.8s",s->job);text(10,238,job,0xffff);
    } else text(10,142,"WAITING FOR DATA",0xffff);
    ESP_ERROR_CHECK(esp_lcd_panel_draw_bitmap(panel,0,0,WIDTH,HEIGHT,pixels));
    // The SPI driver owns the DMA buffer until completion; don't redraw early.
    configASSERT(xSemaphoreTake(flushed,pdMS_TO_TICKS(2000))==pdTRUE);
}
