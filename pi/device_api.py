"""Printer-scoped device credentials and conservative physical delivery."""
import hashlib
import secrets
import re
from contextlib import closing
import sqlite3
import time
from pathlib import Path
from flask import request, abort, jsonify, Response, g
from PIL import Image


def init_devices(dbpath):
    with closing(sqlite3.connect(dbpath)) as db, db:
        db.executescript('''CREATE TABLE IF NOT EXISTS printer_devices(
          printer TEXT PRIMARY KEY, token_hash TEXT NOT NULL, seen REAL DEFAULT 0);
          CREATE TABLE IF NOT EXISTS device_jobs(job TEXT PRIMARY KEY, claimed REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS device_status(printer TEXT PRIMARY KEY, connected INTEGER NOT NULL DEFAULT 0);
          CREATE TABLE IF NOT EXISTS pending_devices(printer TEXT PRIMARY KEY, token_hash TEXT NOT NULL, expires REAL NOT NULL);''')


def pack_raster(path):
    with Image.open(path) as image:
        if image.width != 384 or not 1 <= image.height <= 4300:
            raise ValueError('MXW01 requires 384 dots wide and at most 4300 rows')
        image = image.convert('1', dither=Image.Dither.NONE)
        # PIL uses MSB-first white=1; MXW01 uses LSB-first black=1.
        reverse = bytes(int(f'{255-i:08b}'[::-1], 2) for i in range(256))
        data = image.tobytes().translate(reverse)
        height = max(90, image.height)
        return data + bytes((height-image.height)*48), height


def install_devices(app, dbpath, root):
    init_devices(dbpath)

    @app.before_request
    def device_auth():
        if not request.path.startswith('/api/device/'):
            return
        token = request.headers.get('Authorization', '').removeprefix('Bearer ')
        digest = hashlib.sha256(token.encode()).hexdigest()
        with closing(sqlite3.connect(dbpath)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT printer FROM printer_devices WHERE token_hash=?', (digest,)).fetchone()
            if not row:
                row=db.execute('SELECT printer FROM pending_devices WHERE token_hash=? AND expires>?',(digest,time.time())).fetchone()
                if row:
                    if db.execute("SELECT 1 FROM jobs WHERE printer=? AND state IN ('pending','sent','uncertain')",(row[0],)).fetchone():
                        abort(409)
                    db.execute('INSERT OR REPLACE INTO printer_devices VALUES (?,?,0)',(row[0],digest))
                    db.execute('DELETE FROM pending_devices WHERE printer=?',(row[0],))
                    db.execute('DELETE FROM device_status WHERE printer=?',(row[0],))
        if not token or not row:
            abort(401)
        g.device_printer = row[0]

    @app.post('/api/printers/<pid>/connect')
    def connect_printer(pid):
        body = request.get_json()
        address = body.get('address','')
        ssid = body.get('ssid','')
        password = body.get('password','')
        if not isinstance(address,str) or not re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}',address):
            raise ValueError('Enter the printer Bluetooth address, such as AA:BB:CC:DD:EE:FF')
        if not isinstance(ssid,str) or not 1 <= len(ssid.encode()) <= 32:
            raise ValueError('Wi-Fi name must contain 1–32 bytes')
        if not isinstance(password,str) or len(password.encode()) > 63:
            raise ValueError('Wi-Fi password is too long')
        if not request.is_secure:
            raise ValueError('Open the public HTTPS app to connect a printer')
        origin = request.host_url.rstrip('/')
        if len(origin) >= 192:
            raise ValueError('Server address is too long')
        token = secrets.token_urlsafe(32)
        config = dict(url=origin,token=token,ssid=ssid,password=password,address=address.upper())
        import json
        if len(json.dumps(config,separators=(',',':')).encode()) >= 511:
            raise ValueError('Setup details are too long')
        with closing(sqlite3.connect(dbpath)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT 1 FROM printer_access WHERE printer=? AND owner=?',(pid,g.user['id'])).fetchone():
                abort(404)
            if db.execute("SELECT 1 FROM jobs WHERE printer=? AND state IN ('pending','sent','uncertain')",(pid,)).fetchone():
                raise ValueError('Finish or resolve queued jobs before connecting this printer')
            db.execute('INSERT OR REPLACE INTO pending_devices VALUES (?,?,?)',(pid,hashlib.sha256(token.encode()).hexdigest(),time.time()+3600))
        # Wi-Fi credentials and Bluetooth address are returned once, not stored on the Pi.
        return jsonify(config=config)

    @app.post('/api/device/heartbeat')
    def heartbeat():
        connected=(request.get_json(silent=True) or {}).get('printer_connected')
        if not isinstance(connected,bool):
            abort(400)
        with closing(sqlite3.connect(dbpath)) as db, db:
            db.execute('UPDATE printer_devices SET seen=? WHERE printer=?',(time.time(),g.device_printer))
            db.execute('INSERT OR REPLACE INTO device_status VALUES (?,?)',(g.device_printer,int(connected)))
            db.execute('UPDATE printers SET online=? WHERE id=?',(int(connected),g.device_printer))
        return jsonify(ok=True)

    @app.post('/api/device/claim')
    def claim():
        now = time.time()
        with closing(sqlite3.connect(dbpath, timeout=15)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            pid = g.device_printer
            db.execute('UPDATE printer_devices SET seen=? WHERE printer=?', (now,pid))
            db.execute('UPDATE printers SET online=1 WHERE id=?', (pid,))
            db.execute("UPDATE jobs SET state='uncertain' WHERE printer=? AND state='sent' AND id IN (SELECT job FROM device_jobs WHERE claimed<?)", (pid,now-600))
            if db.execute("SELECT 1 FROM jobs WHERE printer=? AND state IN ('sent','uncertain')", (pid,)).fetchone():
                return jsonify(error='Previous delivery needs resolution'), 409
            db.execute("UPDATE jobs SET state='expired' WHERE printer=? AND state='pending' AND expires<=?", (pid,now))
            row = db.execute("SELECT j.id FROM jobs j JOIN artifacts a ON a.job=j.id WHERE j.printer=? AND j.state='pending' AND j.due<=? ORDER BY j.due,j.id LIMIT 1", (pid,now)).fetchone()
            if not row:
                return '', 204
            job = row[0]
            try:
                raster,height = pack_raster(Path(root)/'renders'/(job+'.png'))
            except (OSError, ValueError):
                db.execute("UPDATE jobs SET state='failed' WHERE id=?", (job,))
                return jsonify(error='Unsupported or missing raster'), 422
            db.execute("UPDATE jobs SET state='sent' WHERE id=?", (job,))
            db.execute('INSERT INTO device_jobs VALUES (?,?)', (job,now))
        return Response(raster, mimetype='application/octet-stream', headers={'X-Job-ID':job,'X-Raster-Height':str(height)})

    @app.post('/api/device/jobs/<job>/result')
    def result(job):
        state = (request.get_json(silent=True) or {}).get('state')
        if state not in ('printed','uncertain'):
            abort(400)
        with closing(sqlite3.connect(dbpath)) as db, db:
            row = db.execute('SELECT state FROM jobs WHERE id=? AND printer=? AND id IN (SELECT job FROM device_jobs)', (job,g.device_printer)).fetchone()
            if not row:
                abort(404)
            if row[0] in ('sent','uncertain'):
                db.execute('UPDATE jobs SET state=? WHERE id=?', (state,job))
        return jsonify(ok=True)
