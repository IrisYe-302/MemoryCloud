"""Run with the installed ESP-IDF Python. Sends credentials without printing them."""
import argparse,json,time
from pathlib import Path
import serial
from esp_idf_monitor.base.reset import Reset, LOW, HIGH
p=argparse.ArgumentParser();p.add_argument('file');p.add_argument('--port',default='/dev/cu.usbmodem101');a=p.parse_args()
config=json.loads(Path(a.file).read_text())
wire=json.dumps(config,separators=(',',':')).encode()+b'\n'
if len(wire)>511:raise SystemExit('Provisioning too long')
s=serial.Serial(port=None,baudrate=115200,timeout=1);s.port=a.port
reset=Reset(s,'esp32s3');reset._setRTS(LOW);reset._setDTR(LOW);s.open();reset._setRTS(HIGH);reset._setDTR(HIGH);reset.hard()
sent=False;start=time.monotonic()
try:
    while time.monotonic()-start<90:
        line=s.readline()
        if (b'Provisioning needed' in line or b'Setup window' in line) and not sent:
            # Small batches avoid overflowing the USB console RX buffer.
            for i in range(0,len(wire),32):s.write(wire[i:i+32]);s.flush();time.sleep(.05)
            sent=True;print('Private configuration sent.')
        # Redact all secret field values if they ever appear in a library log.
        text=line.decode(errors='replace')
        for key in ('token','password'):
            if config.get(key):text=text.replace(config[key],'[redacted]')
        print(text,end='',flush=True)
        if b'Server recorded result' in line:break
finally:s.close()
if not sent:print('No provisioning prompt: configuration may already be stored.')
