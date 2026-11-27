# ESP32-S3 → MXW01 BLE test

Standalone ESP-IDF/NimBLE project, using the existing IDF 6.1 toolchain. Flashing replaces the board's running application; it does not modify the separate `status-panel` source project. Conservative default flash layout, no PSRAM required, no Wi-Fi or display wiring.

1. Turn on the MXW01 near the ESP32 and disconnect it from the phone app and Pi.
2. Build and flash from the Mac:

```sh
export IDF_PYTHON_ENV_PATH=$HOME/.espressif/python_env/idf6.1_py3.12_env
source $HOME/.espressif/v6.1/esp-idf/export.sh
cd ./esp/ble-printer-test
idf.py -B build-current menuconfig  # Memory Cloud BLE test: set your printer address
idf.py -B build-current build
idf.py -B build-current -p /dev/cu.usbmodem101 flash monitor
```

The actual connected port may change. This board was identified as ESP32-S3 with USB Serial/JTAG. Console uses that USB interface. Ctrl+] exits IDF monitor. Press RESET/EN on the board to repeat a test.

The test scans for the specific MXW01, negotiates the MTU, discovers its characteristics and the notification descriptor, and subscribes to AE02. It then logs `READY`.

Type **p** followed by Enter in the serial monitor to send one 384×96 pixel test pattern. Resetting alone never prints. It requests status (A1), requires standby, paper present, and no error, sets moderate intensity (A2), requests printing (A9), waits for acceptance, streams LSB-first monochrome data through AE03 in 20-byte chunks, flushes (AD), and waits for completion (AA) with a matching image checksum. Timeouts or disconnects stop the attempt without retrying. A completion notification still needs physical paper inspection.

Notifications are length checked, and compact replies ending in 00 are supported and CRC is checked for CRC+FF replies; malformed responses cannot authorize printing. Raw notification bytes are logged for diagnosing firmware variations. A print interrupted after acceptance has an uncertain outcome; inspect the paper before resetting and trying again.

Protocol reference: https://github.com/jeremy46231/MXW01-catprinter/blob/main/PROTOCOL.md (community reverse engineering; hardware validation required).

This is a standalone diagnostic, not yet a webapp queue worker. No Wi-Fi or LCD GPIO is used. Keep other printer clients disconnected. The source in `status-panel` is unchanged.

Compact response layout and completion checksum reference: https://github.com/eliorpom-cmd/print-on-my-desk/blob/main/docs/09-protocol.md . This device returned a ten-byte status payload; state, supply, temperature, error, and paper are at payload offsets 0, 3, 4, 6, and 9. Other status lengths stop this test rather than guessing.

Before building, run `idf.py menuconfig`, open **Memory Cloud BLE test**, and set your printer Bluetooth address. This is stored only in ignored `sdkconfig`; an unconfigured test refuses to scan or print. The main printer-node firmware uses guided discovery instead.
