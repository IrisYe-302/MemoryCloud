# Verified hardware result — 2026-11-25

Built with ESP-IDF 6.1, flashed and hash-verified on ESP32-S3 rev 0.2 at `/dev/cu.usbmodem101`. Module reports 16 MB flash and 8 MB PSRAM; test uses conservative 2 MB layout and no PSRAM. USB Serial/JTAG console verified with esp-idf-monitor.

Observed real serial output:

```text
I (464) PRINTER_TEST: FOUND MXW01 target [configured printer address] RSSI=-63 address_type=0
I (1164) PRINTER_TEST: CONNECTED via BLE. Discovering services...
I (1314) PRINTER_TEST: SERVICE 0x1800 handles=1..3
I (1314) PRINTER_TEST: SERVICE 0x1801 handles=4..7
I (1314) PRINTER_TEST: SERVICE 0xae30 handles=8..23
I (1414) PRINTER_TEST: SERVICE 0xae3a handles=64..69
I (1614) PRINTER_TEST: CHARACTERISTIC 0x2a00 value_handle=3 properties=0x0a
I (1814) PRINTER_TEST: CHARACTERISTIC 0x2a05 value_handle=6 properties=0x20
I (2014) PRINTER_TEST: CHARACTERISTIC 0xae01 value_handle=10 properties=0x04
I (2014) PRINTER_TEST: CHARACTERISTIC 0xae02 value_handle=12 properties=0x10
I (2014) PRINTER_TEST: CHARACTERISTIC 0xae03 value_handle=15 properties=0x04
I (2114) PRINTER_TEST: CHARACTERISTIC 0xae04 value_handle=17 properties=0x10
I (2114) PRINTER_TEST: CHARACTERISTIC 0xae05 value_handle=20 properties=0x20
I (2114) PRINTER_TEST: CHARACTERISTIC 0xae10 value_handle=23 properties=0x0a
I (2314) PRINTER_TEST: CHARACTERISTIC 0xae3b value_handle=66 properties=0x04
I (2314) PRINTER_TEST: CHARACTERISTIC 0xae3c value_handle=68 properties=0x10
I (2414) PRINTER_TEST: TEST COMPLETE: services inspected; no print commands sent. Reset board to repeat.
I (2464) PRINTER_TEST: Disconnected reason=534; completed=yes
```

NimBLE also logged an unsupported remote feature during connection (0x21A); service/characteristic discovery nevertheless completed. No characteristic writes, notification subscriptions, printer status requests, or print jobs were attempted. This verifies transport and service discovery, not the print protocol or physical output.

Initial raw pyserial capture produced no output; the result above came from ESP-IDF monitor, which correctly reset and opened the USB console. The blank hardware-test.log was removed.

## Protocol test — successful device acknowledgment

Built and hash-verified on the same ESP. MTU negotiated to 128; AE02 CCCD discovered at handle13 and subscribed. Explicit serial `p` triggered a single 384×96 test pattern (4608 bytes), streamed in 20-byte chunks with 20ms pacing.

Initial test rejected the compact status response before any print request. Updated parsing using the compact protocol reference linked in README, then rebuilt and reflashed. Second attempt observed:

```text
A1: 22 21 a1 03 0a 00 00 00 00 64 13 00 00 00 b7 00 00
State=0 supply=100 temperature=19 error=0 paper=0
A9: 22 21 a9 00 01 00 00 00
AD sent after all 4608 image bytes
AA: 22 21 aa 00 03 00 00 2b 2b 00
PRINT COMPLETE with matching image checksum
```

Image CRC8 was 0x2b, matching both completion bytes. Printer disconnected deliberately afterward; serial monitor closed. No automatic repeat. User confirmed physical output: "printed" and "looks good, box with slashes". This validates the expected test pattern on paper. No Pi/webapp queue integration yet. The discovery harness's final `completed=no` field is its old discovery-stop flag, not the print result; the MXW01 completion line above is the protocol result.
