"""Bind an existing printer to an ESP; writes a private provisioning file."""
import argparse
import hashlib
import json
import re
import secrets
import sqlite3
import sys
from pathlib import Path
from urllib.parse import urlparse
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from device_api import init_devices
p=argparse.ArgumentParser()
p.add_argument('--data',default='/var/lib/memory-cloud')
p.add_argument('--printer',required=True)
p.add_argument('--address',required=True)
p.add_argument('--url',required=True)
p.add_argument('--ssid',required=True)
p.add_argument('--output',required=True)
a=p.parse_args()
if not re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}',a.address):p.error('Invalid Bluetooth address')
url=urlparse(a.url)
if url.scheme!='https' or not url.hostname or url.username or url.password or url.query or url.fragment or url.path not in ('','/') or len(a.url)>=190:
    p.error('Use the public HTTPS origin without a path, query, or embedded credentials')
dbpath=Path(a.data)/'memory.db'
if not dbpath.is_file(): p.error('Database does not exist')
init_devices(dbpath)
token=secrets.token_urlsafe(32)
# Exclusive creation prevents accidental overwrites. Never prints the credential.
with open(a.output,'x') as f:
    Path(a.output).chmod(0o600)
    with sqlite3.connect(dbpath) as db:
        if not db.execute('SELECT 1 FROM printers WHERE id=?',(a.printer,)).fetchone():
            raise SystemExit('Unknown printer ID')
        if db.execute("SELECT 1 FROM jobs WHERE printer=? AND state IN ('pending','sent','uncertain')",(a.printer,)).fetchone():
            raise SystemExit('Resolve existing jobs before converting this printer')
        db.execute('INSERT OR REPLACE INTO printer_devices VALUES (?,?,0)',(a.printer,hashlib.sha256(token.encode()).hexdigest()))
        db.execute('UPDATE printers SET online=0 WHERE id=?',(a.printer,))
    json.dump(dict(url=a.url.rstrip('/'),ssid=a.ssid,password='',token=token,address=a.address.upper()),f)
print('Device enrolled; private provisioning file written.')
