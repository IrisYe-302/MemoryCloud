idf_component_register(SRCS "main.c" "printer.c" "network.c" INCLUDE_DIRS "." REQUIRES bt nvs_flash esp_wifi esp_event esp_netif esp_http_client esp-tls lwip)
