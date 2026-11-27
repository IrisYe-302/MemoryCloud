# Current Mac layout

Pi source is now `./pi`. Use `bash pi/deploy/push-to-pi.sh` from the project root for code-only updates; this preserves Pi data. ESP source is in `esp/`. Historical commands below may use the old source path.

# Running Memory Cloud

## Local development

Python 3.11+ is required. From the project directory:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
export MEMORY_PASSWORD='choose-a-long-private-password'
.venv/bin/gunicorn --workers 1 --threads 4 --bind 127.0.0.1:8000 'app:create_app()'
```

Open http://localhost:8000. On first use, choose your username and a password of at least 12 characters; use `MEMORY_PASSWORD` as the setup code. This creates the first owner account and adopts any existing demo photos/printers/history. Subsequent visits use your personal credentials. New people need an invitation from an album owner. In another terminal in the same directory:

```sh
.venv/bin/python worker.py
```

The first server startup creates the database. Start the worker afterwards. The worker polls once a second independently of the browser. Upload a photo, select it, adjust the preview, select destinations and send. Bring the friend's simulated printer online to test queued delivery. A simulated print means a raster was accepted by the simulator, not that hardware printed it.

## Raspberry Pi setup

These files have been tested locally, not deployed to your Pi. Use Raspberry Pi OS 64-bit with Python 3.11+. Keep an existing OS if suitable; do not erase your microSD just to run this app. If the Pi has no OS, use Raspberry Pi Imager and configure Wi-Fi, SSH, a user, and hostname `memorypi` first.

### 1. Prepare the microSD on your Mac

You need the Pi 4, microSD, a USB microSD reader, a suitable Pi 4 USB-C power supply, and Wi-Fi or Ethernet. No monitor or keyboard is necessary.

1. Download Raspberry Pi Imager from https://www.raspberrypi.com/software/ and open it.
2. Insert the 256 GB microSD into your Mac's reader. Back up anything on it first: writing the OS erases the selected card.
3. Select Raspberry Pi 4 as the device and Raspberry Pi OS Lite (64-bit) as the OS. Lite runs without a desktop, which suits this server.
4. Select your microSD by name and capacity. Verify you are not selecting another external drive. Imager handles formatting; no manual FAT32 preparation is required.
5. In the customization screens set hostname `memorypi`, a username (for example `iris`), your own password, country/timezone and Wi-Fi credentials. Use your actual network name and password, not the app password.
6. Enable SSH in the remote access/services settings. For this first setup choose password authentication; SSH keys can be configured later. Screen labels differ between Imager versions.
7. Apply the customization, write and let verification finish. Eject the card when complete.

### 2. Boot and connect

With the Pi unplugged, insert the card. Connect Ethernet if using it, then power. Allow several minutes for first boot. Keep your Mac on the same network.

On your Mac, replace `YOUR_USER` with the username you created:

```sh
ssh YOUR_USER@memorypi.local
```

For the first host-key prompt, check that the address belongs to your Pi before accepting. Enter the Pi user's password (nothing appears while typing). A prompt such as `YOUR_USER@memorypi:~ $` means you're connected.

If `.local` is not found, find the Pi's address in your router's device list and use `ssh YOUR_USER@192.168.x.x`. A timeout usually means the device is not reachable; connection refused usually means SSH is not enabled; permission denied means the username/password or SSH authentication method is wrong. Shared campus/guest networks may isolate devices; use a private network or a permitted network arrangement that allows Mac-to-Pi communication.

Run on the Pi:

```sh
sudo apt update
sudo apt full-upgrade
sudo reboot
```

The SSH connection closes during reboot. Reconnect after the Pi starts, then check:

```sh
python3 --version
hostname -I
df -h /
```

Checkpoint: Python is 3.11 or newer, the Pi has an address, and the root filesystem has space. The same card will hold the OS and album data; no extra partition is required.

### 3. Copy and install the app

Copy source from your laptop (replace `YOUR_USER`; excludes local photos, credentials and virtual environment):

```sh
rsync -av --exclude=.venv --exclude=data --exclude=__pycache__ --exclude=.env ./ YOUR_USER@memorypi.local:memory-cloud/
ssh YOUR_USER@memorypi.local
```

On the Pi:

```sh
sudo apt update
sudo apt install python3-venv
sudo useradd --system --home /var/lib/memory-cloud --shell /usr/sbin/nologin memory
sudo install -d -o memory -g memory /var/lib/memory-cloud
sudo mkdir -p /opt/memory-cloud
sudo cp -R memory-cloud/. /opt/memory-cloud/
sudo python3 -m venv /opt/memory-cloud/.venv
sudo /opt/memory-cloud/.venv/bin/pip install -r /opt/memory-cloud/requirements.txt
sudo install -m 600 /dev/null /etc/memory-cloud.env
sudo nano /etc/memory-cloud.env
```

Put these two lines in the environment file, choosing a private setup code:

```ini
MEMORY_PASSWORD=replace-with-a-long-private-password
MEMORY_DATA=/var/lib/memory-cloud
```

Then enable the services:

```sh
sudo cp /opt/memory-cloud/deploy/memory-web.service /etc/systemd/system/
sudo cp /opt/memory-cloud/deploy/memory-worker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now memory-web memory-worker
sudo systemctl status memory-web memory-worker
```

Both should show `active (running)`. Press `q` to leave the status viewer. These are first-install instructions: do not recreate the environment file on subsequent updates, since that would erase your password. The `memory` service user is separate from the account you use for SSH.

### 4. Open the Pi-hosted album

The server listens on the Pi's loopback address by default. For an initial encrypted laptop connection:

```sh
ssh -N -L 8080:127.0.0.1:8000 YOUR_USER@memorypi.local
```

Run that in a new Mac terminal and leave it open. Open http://localhost:8080 on the Mac. Create your first account using the setup code from `/etc/memory-cloud.env`, or sign in if accounts already exist. The network traffic between laptop and Pi travels through SSH. Port 8080 distinguishes this from the Mac-hosted app on port 8000. Ctrl-C in the tunnel terminal ends access, but the Pi services keep running.

Upload a small image, send it to My desk, and verify a simulated print appears. Then test the friend's printer offline with queue enabled and bring it online. Finally reboot the Pi, reconnect the tunnel and confirm the album persists. This verifies storage and automatic service startup.

## Phone access over local HTTPS

Install Caddy using its official instructions, then adapt `deploy/Caddyfile` as `/etc/caddy/Caddyfile` and restart Caddy. It proxies HTTPS to the loopback web server. With `tls internal`, install and trust Caddy's local CA certificate on each phone/laptop before browsing https://memorypi.local; do not bypass certificate warnings. Hostname discovery depends on your network. Public hosting, domain certificates and remote access remain a later milestone.

For HTTPS hosting add `MEMORY_HTTPS=1` to `/etc/memory-cloud.env` and restart the web service. This enables Secure cookies and trusts the scheme header from the local reverse proxy. Keep Gunicorn on loopback; do not enable this behind an untrusted proxy. For local HTTP through an SSH tunnel leave `MEMORY_HTTPS` unset.

Accounts now have hashed passwords and server-side sessions. Album owners create single-use invitations (1 hour, 24 hours or 7 days) and can revoke unused links. Members can upload, view and print; only printer owners can toggle their simulator status. Each printer currently belongs to one album. Invitation URLs use a fragment so the token is not sent in ordinary page requests. Links generated on localhost only work on that computer: use the Pi's reachable HTTPS origin for real sharing. Keep the service private while password recovery, member removal and broader production hardening remain unimplemented. Never forward port 8000 from your router.

## Storage and maintenance

SQLite (including users, memberships, sessions and hashed invitations), normalized photos and immutable print PNGs live in `/var/lib/memory-cloud`. Original upload bytes and EXIF metadata are not retained; the content hash still detects exact reuploads. Back up this entire directory together while both services are stopped; restart them afterwards. Treat backups as private. Disk capacity management and deletion UI are not implemented yet.

```sh
sudo journalctl -u memory-web -u memory-worker -n 100 --no-pager
```

For updates, stop services, copy source without overwriting data or the environment file, install dependencies if changed, and restart. Do not run multiple simulator workers. USB integration will replace the simulator adapter after the printer protocol is known.

References: https://www.raspberrypi.com/documentation/computers/getting-started.html , https://www.raspberrypi.com/documentation/computers/remote-access.html , https://www.raspberrypi.com/documentation/computers/os.html and https://flask.palletsprojects.com/en/stable/deploying/gunicorn/
