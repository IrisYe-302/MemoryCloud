# Memory Cloud ESP32-S3 status panel

AI-assisted scaffold developed with OpenAI Codex. This is an ESP-IDF project,
not Arduino. It currently runs a **serial-console display simulation**, not a
network client. A conditional ST7789 physical display backend is included but
disabled by default, awaiting controller and board confirmation. No GPIO is
assigned or energized in the default build.

## Existing Mac toolchain

User hardware: ESP32-S3 N16R8 development module. The current verified build
uses a conservative 2 MB flash layout within the larger flash and leaves PSRAM
disabled; the status renderer allocates its DMA buffer from internal RAM. Before
expanding storage or enabling octal PSRAM, confirm the exact module marking and
board schematic. N16R8 alone does not identify every development board's wiring.

ESP-IDF 6.1 and its Python 3.12 environment were found on this Mac. From an
ESP-IDF terminal (or with the activation below):

```sh
export IDF_PYTHON_ENV_PATH=$HOME/.espressif/python_env/idf6.1_py3.12_env
source $HOME/.espressif/v6.1/esp-idf/export.sh
cd ./esp/status-panel
idf.py set-target esp32s3
idf.py menuconfig
idf.py build
idf.py -p /dev/cu.YOUR_BOARD_PORT flash monitor
```

Use the actual port that appears when the board is connected. `Ctrl+]` exits
the monitor. Do not copy a guessed port or flash another connected device.
`set-target` is a one-time configuration step, not needed before every build.

Under **Memory Cloud status panel**, the default demo cycles through idle,
offline queue, sending, simulated completion, uncertain output, and stale
server data. Set the demo option off to feed newline-delimited JSON through
the configured serial console instead. This mode is for integration testing;
it is not an authenticated network transport.

## Display architecture

`status_input` produces a bounded status snapshot. A FreeRTOS queue of length
one keeps only the latest snapshot. `app_main` is the sole display owner and
checks freshness each second. `display_console.c` is the replaceable renderer.
The future network task must never call the display driver directly.

The physical screen will show:

- MEMORY CLOUD (and SIMULATED while using a simulator)
- Printer online/offline, separate from server connectivity
- Number of pending print jobs
- Current state and a shortened job identifier
- Server disconnected/stale, with printer status unknown after 15 seconds

Do not put usernames, filenames, photos, passwords or session tokens on the
status panel. `sending` means bytes/job delivery in progress, not confirmed
paper output; uncertain output must remain visibly uncertain.

## Version 1 status message

```json
{"version":1,"queued":2,"printer_online":false,"simulated":true,"state":"queued","job":"demo-1"}
```

Required fields: version=1, queued integer 0..9999, printer_online and simulated
booleans, state in idle/queued/sending/printed/uncertain/error, job string up to
36 characters. Invalid/oversized messages never refresh the last-good timestamp.
The receiver uses its own monotonic clock, not server timestamps.

## Physical driver: awaiting module identification

The AliExpress listing could not be retrieved. The user's supplied pinout image
confirms **1.9-inch IPS LCD, 170x320 RGB, SPI, 3.3 V**, not OLED. It does not
identify the controller or the ESP32 board variant.

| Module label | Function | Connection |
|---|---|---|
| GND | Ground | ESP32 ground |
| VCC | 3.3 V supply | 3V3, not 5 V |
| SCL | SPI clock | Configurable SCLK GPIO; this is not I2C |
| SDA | SPI write data | Configurable MOSI GPIO; no MISO needed |
| RES | Active-low reset | Configurable reset GPIO |
| DC | Command/data selection | Configurable DC GPIO |
| CS | Active-low chip select | Configurable CS GPIO |
| BLK | Active-high backlight control | 3.3 V per module instructions, or verified control GPIO |

`display_st7789.c` implements a 170x320 RGB565 status screen with a compact bitmap
font, SPI DMA completion synchronization, and configurable pins, color inversion,
RGB/BGR ordering and RAM X offset. The initial X offset 35 is a candidate for
centered 170-pixel glass on a 240-pixel controller, **not a verified module value**.
Enable `MEMORY_LCD_ST7789` only after confirming ST7789. Set all five signal GPIO
values in menuconfig; they default to -1 and initialization refuses missing or
duplicate assignments. GPIO validity alone does not establish board suitability:
avoid pins used for flash/PSRAM, USB, boot strapping or other onboard peripherals.
No physical screen or pin assignment has been tested yet.

Once confirmed:

1. Check module supply and logic voltage, choose safe GPIO from that board's
   schematic, and document the complete wiring table.
2. Initialize the appropriate I2C or SPI bus, then an `esp_lcd` controller driver.
   Select a vendor component if that controller is not provided by ESP-IDF.
3. Add a framebuffer/text renderer for the panel's pixel format and resolution.
   For a monochrome OLED a small bitmap font is enough; a color panel can use
   LVGL with Espressif's LVGL port. Keep all UI updates in the display task.
4. Verify reset, orientation, offsets and (TFT only) backlight controls with a
   text/test pattern before adding Wi-Fi. Never assume an SSD1306 driver.
5. Replace the console renderer; keep the same validated status model/queue.

## Next network milestone (not implemented)

Mac/Pi remains the authoritative queue and USB printer host. Add device-scoped,
revocable credentials and an authenticated status endpoint or MQTT/TLS topic.
ESP32 subscribes/polls only its printer's status and publishes heartbeat/RSSI.
The server must distinguish ESP32 heartbeat from printer readiness. No account
passwords in firmware and no anonymous album/media endpoint. Firmware accepts
status snapshots only; selecting/approving photos stays in the web UI.

## Validation

The status parser has a host-side test covering valid snapshots, invalid
state/count data and preserving the last-good timestamp after bad messages.
After resolving the cJSON component with `idf.py build`, run:

```sh
clang -std=c11 -Wall -Wextra -Werror -Imain \
  -Imanaged_components/espressif__cjson/cJSON \
  tests/status_model_test.c main/status_model.c \
  managed_components/espressif__cjson/cJSON/cJSON.c \
  -o /tmp/memory-status-test
/tmp/memory-status-test
```

The conditional ST7789 renderer has been compile-checked using the installed
Xtensa ESP32-S3 toolchain. Neither display output nor serial-input behavior has
been exercised on a board. No firmware has been flashed.

The default console-demo firmware completed a full ESP-IDF 6.1 build on this Mac
on November 22, 2026. Artifact: `build/memory_status_panel.bin` (176,960 bytes).

## Official references

- https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/get-started/index.html
- https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-reference/peripherals/lcd/index.html
