# Connect your printer

## Current setup flow

1. Deploy the Pi app from the Mac: `bash pi/deploy/push-to-pi.sh` from the project root. Photos, accounts, and environment settings are preserved.
2. Flash `esp/printer-node` once onto an ESP32-S3. This is required for each new board; the browser configures firmware that is already installed.
3. Open the public HTTPS webapp in desktop Chrome/Edge, select **Printers**, and open **Set up printer ESP** on a printer you own.
4. Choose **Connect ESP via USB**, select the board, and press RESET when prompted. Guided firmware version 2 is required.
5. Choose a scanned Wi-Fi network and enter its password if needed. Open/personal Wi-Fi is supported; enterprise credentials and captive portals are not handled. Choose a network with direct Internet access.
6. Click **Find printers**, choose a nearby MXW01, then **Print a small test**. Confirm the test appeared on the intended printer before saving. To try a different printer after a connection attempt, disconnect USB and reset to restart setup.
7. Click **Yes, it printed — save connection**. The app supplies its URL and private credential automatically. No IP or Bluetooth address entry is needed.

One ESP is used per physical printer. The phone app must disconnect so the ESP can use Bluetooth. Only the printer owner can set up, rename, delete, or share it.

The public app origin is supplied automatically (for example, https://your-pi.your-tailnet.ts.net). The ESP needs Internet, DNS, and NTP with certificate-verified HTTPS; it does not run Tailscale. The Pi must have `MEMORY_HTTPS=1` behind the trusted Funnel proxy.

## Status and credentials

ESP online means its heartbeat reached the server within 30 seconds. Printer connected means BLE service discovery and notification setup completed; this is separate from paper/error readiness checked before printing. The UI shows last-seen time and reports printer status as unknown when the ESP is offline. The ESP retries BLE discovery without rebooting so network status stays available.

A new setup credential is staged for one hour. The previous credential continues working until the new ESP authenticates. Creating a setup response alone does not disconnect the old ESP. Pending/uncertain jobs block replacement. The server stores only token hashes; Wi-Fi credentials stay on the ESP.

Each boot offers a 20-second setup window, indefinite on unconfigured boards. The guided hello command holds that window open while the owner works. Closing setup without saving requires a reset to return to the previous saved configuration. Configurations missing a Bluetooth address enter setup instead of guessing.

The advanced `esp/provision.py` CLI still accepts a private configuration JSON file. The normal UI uses scanned lists instead of file downloads.

## Delivery behavior

The Pi stores only a hash of the device token. Wi-Fi details are returned for setup and stored on the ESP, not persisted by the Pi. The simulator excludes physical printers. One immutable raster is claimed at a time; a matching printer completion checksum is required before reporting printed.

The ESP saves in-flight delivery state in NVS. It retries result reports, never the physical print. Lost claims become uncertain after ten minutes and block further jobs until the owner chooses **It printed** or **It did not print**. Inspect the first photo to confirm paper quality.

Source folders: `pi/` for the server, `esp/printer-node/` for the queue client, `esp/ble-printer-test/` for the original verified diagnostic, and `esp/status-panel/` for the LCD scaffold.
