# Memory Cloud — EE250

Current milestone: mobile web album, thermal image preview, persistent delivery policies and two simulated printers. See [HOSTING.md](HOSTING.md) for local startup and Raspberry Pi services.

Surprise me: choose a printer in the current album, review an unprinted photo,
try another or cancel, customize its thermal preview, then explicitly approve.
Suggestions do not enqueue jobs. Previously suggested photos are excluded for
this browser session (reset on reload or album change). Full printer history
excludes pending, sent, uncertain and printed photos; the existing transactional
duplicate guard checks again on approval. This is random selection, not AI.
Optional date filtering, bulk selection and queue reordering are not implemented.

ESP-IDF 6.1 status-panel scaffold and hardware bring-up steps are in
[firmware/status-panel/README.md](firmware/status-panel/README.md). It currently
simulates display status on the serial console; Wi-Fi and the physical display
driver await integration. Source in this project was developed with OpenAI Codex
assistance; acknowledge that in the final course write-up as well.

Implemented: authenticated shared album, validated photo upload, exact-upload deduplication, center-cropped one-bit PNG previews, contrast/dithering controls, three built-in frames, manual captions, selective sends, offline queue choice, persistent print history and simulator status toggles.

Also implemented: individual accounts, multiple private albums, membership checks on media and print endpoints, single-use expiring invitations, unused-link revocation, owner-controlled simulated printers, and persistent server-side sessions. The first account claims the existing demo archive using the server setup code. See [ACCOUNTS.md](ACCOUNTS.md).

Not implemented yet: QR device pairing, semantic search, AI captions/frames, scheduling UI, real USB/ESP32 transport, password recovery and member removal. Frame templates and current image processing are deterministic, not AI.

## Two-week build sequence

1. Days 1–2: identify printer model, companion app, Bluetooth protocol and USB data support; validate one raster print. Keep simulator available until hardware arrives.
2. Days 3–4: Pi web server, SQLite, photo storage, accounts, invite-only albums and expiring single-use invitations.
3. Days 5–6: mobile upload, album gallery, thermal preview, crop/contrast/dithering, frame and caption controls.
4. Days 7–8: authenticated device pairing through short-lived QR claims; transport adapter; ESP32 heartbeat, LED and display status. Simulate a second node if only one printer exists.
5. Days 9–10: selective sends, explicit offline queue policy, schedules, persistent history and uncertain-job resolution.
6. Days 11–12: semantic search and optional AI captions/frames; integrate one real AI feature before adding more.
7. Days 13–14: TLS deployment, permissions testing, disconnect/reboot demo, measurements and presentation.

## Architecture decisions

Pi owns album data, permissions, image processing and durable jobs. Web UI works on phones. ESP32 handles device status and the printer adapter if its protocol is supported. Printer model is unverified: a Bluetooth/USB listing does not establish ESC/POS compatibility, BLE support or USB printing support.

ESP32-S3 supports BLE, not Bluetooth Classic: https://docs.espressif.com/projects/esp-idf/en/latest/esp32s3/api-guides/ble/overview.html . A Classic-only printer needs a different transport arrangement. Do not assign display pins until its controller and voltage are known.

Prefer HTTPS for image downloads and MQTT over TLS for small job notifications/status. Notifications reference durable jobs; broker messages are not the authoritative queue. Configure printable width from hardware tests, not nominal paper width.

Image preparation starts with deterministic crop, grayscale, contrast and dithering. Those operations alone are not AI. Add actual model-based captioning and semantic embeddings as separate providers. Store original files on Pi; remote inference requires an explicit deployment choice. Near-duplicate suggestions use perceptual similarity; exact duplicate detection uses original-content SHA-256. Print history lives in SQLite, not volatile RAM. Different frames do not silently bypass photo-level duplicate protection.

## Delivery contract

- Every target has its own job and outcome; selecting multiple printers creates multiple jobs.
- User chooses queue-until-online or online-only. Online-only jobs expire after a short dispatch window and are skipped immediately if disconnected at dispatch.
- Scheduled sends use the policy at the scheduled time. Queue policy has an explicit expiry as well.
- Client supplies a unique request key per recipient. Retries reuse that key; a changed payload under the same key is rejected.
- A photo already pending, sent, uncertain or confirmed on that printer is blocked unless the user explicitly chooses reprint.
- Claiming a job marks it sent before device I/O. A crash or lost acknowledgement becomes uncertain; never automatically retry a possibly printed job.
- Device-side durable job IDs are still required before integrating transport. Exactly-once physical output cannot be guaranteed across a printer power failure.
- Only a reliable device acknowledgement or user confirmation may mark a job printed. Successful byte transmission is not proof of paper output.

## Run tests

From this directory after installing requirements: `.venv/bin/python -m unittest discover -s tests -v`.

Keep this prototype on localhost or a trusted private HTTPS deployment; Internet deployment hardening remains a later milestone.
