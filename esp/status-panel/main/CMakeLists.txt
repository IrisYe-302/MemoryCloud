if(CONFIG_MEMORY_LCD_ST7789)
    set(display_source "display_st7789.c")
else()
    set(display_source "display_console.c")
endif()
idf_component_register(SRCS "main.c" "status_model.c" "${display_source}"
                       INCLUDE_DIRS "." REQUIRES esp_timer esp_lcd esp_driver_spi esp_driver_gpio)
