# Memory Cloud ESP printer node

ESP32-S3 N16R8, ESP-IDF 6.1. Wi-Fi HTTPS queue client plus verified MXW01 BLE protocol. No LCD GPIO yet. The BLE address comes from each owner’s UI setup, stored with the Wi-Fi details in NVS.

```sh
export IDF_PYTHON_ENV_PATH=$HOME/.espressif/python_env/idf6.1_py3.12_env
source $HOME/.espressif/v6.1/esp-idf/export.sh
cd ./esp/printer-node
idf.py build
idf.py -p /dev/cu.usbmodem101 flash monitor
```

Uses a 2 MiB app partition within a 4 MiB flash layout; the board has 16 MiB. Original NVS and PHY offsets are preserved. No PSRAM dependency. TLS CA bundle enabled; clock sync required. Secrets are provisioned through USB into NVS, not compiled into firmware. `../provision.py` sends a private JSON file without echoing its token.

Read ../../docs/ESP-QUEUE.md for Pi deployment and enrollment.

The standalone verified box-pattern diagnostic remains in ../ble-printer-test. This node automatically consumes eligible jobs only after provisioning. It stores the job ID as uncertain before printing, then persists printed only after a matching checksum. HTTP result reporting can retry; physical printing cannot retry automatically. A reboot reports the stored outcome before requesting another job. Reset during a lost claim may require owner resolution on the webapp after ten minutes.

Guided USB setup uses newline JSON commands (`hello`, `scan_wifi`, `scan_printers`, `test`) and `MCJSON:` response lines. Scanning does not save credentials or print; `test` is an explicit physical print. A full configuration JSON saves NVS and starts the queue client. Version 2 responses distinguish guided firmware from earlier builds.

Independent heartbeats report the ESP and BLE status even when the printer is disconnected or a long print is running. Saved delivery outcomes still block reconfiguration until acknowledged.

See ../../docs/ESP-QUEUE.md for the browser flow and deployment requirements. Wi-Fi scans support open/personal networks; enterprise access is not supported. Printer discovery currently lists MXW01 by advertised name. Confirm the physical test before saving when several printers share the same name.

Validation (2026-11-25): version 2 built and flashed with hash verification on the connected ESP32-S3. USB hello returned version 2, Wi-Fi scan returned nine networks, and BLE scan discovered MXW01. No test print was sent during this validation. The Pi must receive the matching webapp update before completing browser setup; browser end-to-end provisioning has not yet been verified.

Long-print reliability update: data writes rejected with local NimBLE ENOMEM/EAGAIN/EBUSY are retried at the same byte offset, up to eight retries. Pacing increases permanently for the rest of that transfer (10 to 160 ms) after a stall. Accepted bytes are not resent. A 200 ms drain pause precedes flush. Disconnects, permanent errors, or checksum failures remain uncertain; there is no automatic job replay. Logs report expected raster height and byte/row progress.

Host test: `cc -Wall -Wextra -Werror esp/printer-node/tests/test_transfer.c -o /tmp/memory-test-transfer && /tmp/memory-test-transfer` from the repository root. It verifies a 700-row payload remains byte-identical through simulated stalls and that persistent stalls stop. A physical portrait retry is still required to verify the reported cropped-output issue.

Captured failure: a 536-row job returned AA `fc 6a ea` after 10.38 seconds, around row 216, while the old 20-byte/20-ms transfer continued to 25.72 seconds. Updated to one 48-byte row per 10 ms (536 rows in about 5.36 seconds), requiring negotiated MTU >=51. This addresses the observed early termination; physical verification is still required. The host test also checks row boundaries and transfer pacing.
