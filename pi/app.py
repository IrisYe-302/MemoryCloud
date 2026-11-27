import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time
import warnings
from flask import Flask, abort, g, jsonify, request, send_file
from access import install_access
from ai_captions import install_ai
from PIL import Image, ImageOps, UnidentifiedImageError
from delivery import Delivery
from device_api import install_devices
from imaging import render, correct_color, duplicate_groups
from werkzeug.middleware.proxy_fix import ProxyFix

Image.MAX_IMAGE_PIXELS = 25000000


def create_app(data_dir=None, password=None):
    app = Flask(__name__, static_url_path='/static')
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
    app.config['SESSION_COOKIE_SECURE'] = os.environ.get('MEMORY_HTTPS') == '1'
    if app.config['SESSION_COOKIE_SECURE']:
        # Only enable behind the trusted local HTTPS proxy; keep Gunicorn bound
        # to loopback. Trust its scheme, not client-supplied host/address values.
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=0, x_proto=1, x_host=0)
    root = Path(data_dir or os.environ.get('MEMORY_DATA', 'data')).resolve()
    root.mkdir(parents=True, exist_ok=True)
    for name in ('photos', 'renders'):
        (root / name).mkdir(exist_ok=True)
    password = password or os.environ.get('MEMORY_PASSWORD')
    if not password:
        raise RuntimeError('Set MEMORY_PASSWORD before starting the server')
    dbpath = root / 'memory.db'
    d = Delivery(dbpath)
    d.db.executescript('''
        CREATE TABLE IF NOT EXISTS photos(id TEXT PRIMARY KEY, name TEXT, created REAL);
        CREATE TABLE IF NOT EXISTS printers(id TEXT PRIMARY KEY, name TEXT, online INTEGER);
        CREATE TABLE IF NOT EXISTS artifacts(job TEXT PRIMARY KEY, options TEXT);
        CREATE TABLE IF NOT EXISTS photo_metadata(album TEXT, photo TEXT, contributor TEXT, added REAL, original TEXT, PRIMARY KEY(album,photo));
        INSERT OR IGNORE INTO printers VALUES ('desk', 'My desk', 1);
        INSERT OR IGNORE INTO printers VALUES ('friend', 'Second demo printer', 0);
    ''')
    d.db.close()

    def connection():
        db = sqlite3.connect(dbpath)
        db.row_factory = sqlite3.Row
        return db

    install_access(app, dbpath, password)
    install_devices(app, dbpath, root)

    @app.before_request
    def validate_json():
        if request.method not in ('GET', 'HEAD', 'OPTIONS') and request.is_json and not isinstance(request.get_json(), dict):
            raise ValueError('Expected a JSON object')

    @app.after_request
    def headers(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self' blob:; style-src 'self'; script-src 'self'; frame-ancestors 'none'"
        return response

    @app.errorhandler(413)
    def too_large(e):
        return jsonify(error='Photo must be smaller than 16 MB.'), 413

    @app.errorhandler(ValueError)
    def invalid(e):
        return jsonify(error=str(e)), 400

    @app.get('/')
    def index():
        return app.send_static_file('index.html')

    @app.get('/api/state')
    def state():
        db = connection()
        try:
            db.execute('UPDATE printers SET online=0 WHERE id IN (SELECT printer FROM printer_devices WHERE seen<?)', (time.time()-30,))
            db.commit()
            return jsonify(photos=[dict(r) for r in db.execute('''SELECT p.*,m.contributor AS contributor_id,COALESCE((SELECT name FROM user_profiles WHERE user=u.id),upper(substr(u.username,1,1))||substr(u.username,2)) AS contributor,
                           COALESCE(m.added,p.created) AS added,m.original
                           FROM photos p JOIN album_photos a ON a.photo=p.id
                           LEFT JOIN photo_metadata m ON m.album=a.album AND m.photo=p.id
                           LEFT JOIN users u ON u.id=m.contributor
                           WHERE a.album=? ORDER BY added DESC,p.id''', (g.album,))],
                           printers=[dict(r) for r in db.execute('SELECT p.*,a.owner,(SELECT seen FROM printer_devices d WHERE d.printer=p.id) AS last_seen,(SELECT connected FROM device_status ds WHERE ds.printer=p.id) AS printer_connected,EXISTS(SELECT 1 FROM printer_devices d WHERE d.printer=p.id) AS physical FROM printers p JOIN printer_access a ON a.printer=p.id WHERE a.owner=? OR EXISTS (SELECT 1 FROM printer_shares s WHERE s.printer=p.id AND s.user=?)', (g.user['id'],g.user['id']))],
                           jobs=[dict(r) for r in db.execute('SELECT j.*,EXISTS(SELECT 1 FROM device_jobs dj WHERE dj.job=j.id) AS physical FROM jobs j JOIN job_access a ON a.job=j.id WHERE a.album=? ORDER BY j.rowid DESC LIMIT 50', (g.album,))])
        finally:
            db.close()

    @app.post('/api/photos')
    def upload():
        f = request.files.get('photo')
        if not f:
            raise ValueError('Choose an image')
        raw = f.read()
        photo_id = hashlib.sha256(raw).hexdigest()
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(raw)) as src:
                    src.load()
                    normalized = ImageOps.exif_transpose(src).convert('RGB')
                    normalized.thumbnail((2400, 2400))
                    normalized.save(root / 'photos' / (photo_id + '.jpg'), quality=92)
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
            raise ValueError('Use a valid JPEG, PNG or WebP photo under 25 megapixels')
        db = connection()
        try:
            db.execute('INSERT OR IGNORE INTO photos VALUES (?,?,?)', (photo_id, (f.filename or 'Photo')[:100], time.time()))
            added = db.execute('INSERT OR IGNORE INTO album_photos VALUES (?,?)', (g.album,photo_id))
            if added.rowcount:
                db.execute('INSERT OR REPLACE INTO photo_metadata VALUES (?,?,?,?,?)', (g.album,photo_id,g.user['id'],time.time(),None))
            db.commit()
        finally:
            db.close()
        return jsonify(id=photo_id), 201

    # AI-assisted implementation; suggestions never create print jobs.
    @app.post('/api/suggestions')
    def suggest():
        body = request.get_json()
        printer = body.get('printer')
        seen = body.get('seen', [])
        if not isinstance(printer, str) or not isinstance(seen, list) or len(seen) > 2000 or any(not isinstance(x, str) for x in seen):
            raise ValueError('Choose a printer and a valid suggestion session')
        db = connection()
        try:
            if not db.execute('SELECT 1 FROM printer_access a WHERE a.printer=? AND (a.owner=? OR EXISTS (SELECT 1 FROM printer_shares s WHERE s.printer=a.printer AND s.user=?))', (printer,g.user['id'],g.user['id'])).fetchone():
                abort(404)
            candidates = [dict(r) for r in db.execute('''
                SELECT p.* FROM photos p JOIN album_photos a ON a.photo=p.id
                WHERE a.album=? AND NOT EXISTS (
                    SELECT 1 FROM jobs j WHERE j.photo=p.id AND j.printer=?
                    AND j.state IN ('pending','sent','uncertain','printed'))
            ''', (g.album,printer)) if r['id'] not in set(seen)]
            return jsonify(photo=secrets.choice(candidates) if candidates else None)
        finally:
            db.close()

    def photo_path(pid):
        if not isinstance(pid, str) or len(pid) != 64 or any(c not in '0123456789abcdef' for c in pid):
            abort(404)
        db = connection()
        try:
            if not db.execute('SELECT 1 FROM album_photos WHERE photo=? AND album=?', (pid,g.album)).fetchone():
                abort(404)
        finally:
            db.close()
        path = root / 'photos' / (pid + '.jpg')
        if not path.exists():
            abort(404)
        return path

    install_ai(app, dbpath, photo_path)

    @app.get('/api/photos/<pid>')
    def photo(pid):
        return send_file(photo_path(pid))

    @app.post('/api/photos/<pid>/color-preview')
    def color_preview(pid):
        photo = correct_color(photo_path(pid), request.get_json())
        photo.thumbnail((1000,1000))
        output = io.BytesIO()
        photo.save(output,format='JPEG',quality=92)
        output.seek(0)
        return send_file(output,mimetype='image/jpeg')

    @app.post('/api/photos/<pid>/color-copy')
    def color_copy(pid):
        photo = correct_color(photo_path(pid), request.get_json())
        output = io.BytesIO()
        photo.save(output,format='JPEG',quality=92)
        raw = output.getvalue()
        photo_id = hashlib.sha256(raw).hexdigest()
        (root/'photos'/(photo_id+'.jpg')).write_bytes(raw)
        db = connection()
        try:
            now = time.time()
            db.execute('INSERT OR IGNORE INTO photos VALUES (?,?,?)', (photo_id,'Edited photo',now))
            added = db.execute('INSERT OR IGNORE INTO album_photos VALUES (?,?)', (g.album,photo_id))
            if added.rowcount:
                db.execute('INSERT OR REPLACE INTO photo_metadata VALUES (?,?,?,?,?)', (g.album,photo_id,g.user['id'],now,pid))
            db.commit()
        finally:
            db.close()
        return jsonify(id=photo_id),201

    @app.delete('/api/photos/<pid>')
    def remove_photo(pid):
        # Album membership is checked by the request guard. Retain source files
        # and immutable print artifacts used by other albums or existing jobs.
        db = connection()
        try:
            removed = db.execute('DELETE FROM album_photos WHERE album=? AND photo=?', (g.album, pid))
            if not removed.rowcount:
                abort(404)
            db.commit()
        finally:
            db.close()
        return jsonify(ok=True)

    @app.get('/api/duplicates')
    def duplicates():
        db = connection()
        try:
            photos = [dict(r) for r in db.execute('''SELECT p.id,COALESCE(m.added,p.created) AS added,COALESCE((SELECT name FROM user_profiles WHERE user=u.id),upper(substr(u.username,1,1))||substr(u.username,2)) AS contributor
                FROM photos p JOIN album_photos a ON a.photo=p.id
                LEFT JOIN photo_metadata m ON m.album=a.album AND m.photo=p.id
                LEFT JOIN users u ON u.id=m.contributor
                WHERE a.album=? ORDER BY added,p.id LIMIT 501''', (g.album,))]
        finally:
            db.close()
        if len(photos)>500:
            raise ValueError('Duplicate review currently supports albums with up to 500 photos')
        return jsonify(groups=duplicate_groups(photos,root/'photos'))

    @app.post('/api/duplicates/remove')
    def remove_duplicates():
        body = request.get_json()
        keep, remove = body.get('keep'), body.get('remove')
        if not isinstance(keep,str) or not isinstance(remove,list) or not 1 <= len(remove) <= 499 or any(not isinstance(pid,str) for pid in remove):
            raise ValueError('Choose a photo to keep and copies to remove')
        if keep in remove or len(set(remove)) != len(remove):
            raise ValueError('The kept photo cannot be removed')
        db = connection()
        try:
            db.execute('BEGIN IMMEDIATE')
            for pid in [keep,*remove]:
                if not db.execute('SELECT 1 FROM album_photos WHERE album=? AND photo=?',(g.album,pid)).fetchone():
                    raise ValueError('These photos changed or are not in this album. Scan again.')
            db.executemany('DELETE FROM album_photos WHERE album=? AND photo=?',[(g.album,pid) for pid in remove])
            db.commit()
        finally:
            db.close()
        return jsonify(removed=len(remove))

    @app.post('/api/preview/<pid>')
    def preview(pid):
        output = io.BytesIO()
        render(photo_path(pid), request.get_json()).save(output, format='PNG')
        output.seek(0)
        return send_file(output, mimetype='image/png')

    @app.post('/api/printers/<pid>')
    def printer(pid):
        online = request.get_json().get('online')
        if type(online) is not bool:
            raise ValueError('online must be boolean')
        db = connection()
        try:
            if not db.execute('SELECT 1 FROM printer_access WHERE printer=? AND owner=?', (pid,g.user['id'])).fetchone():
                abort(404)
            if db.execute('SELECT 1 FROM printer_devices WHERE printer=?', (pid,)).fetchone():
                raise ValueError('Physical printer status is reported by the ESP')
            db.execute('UPDATE printers SET online=? WHERE id=?', (online, pid))
            db.commit()
        finally:
            db.close()
        return jsonify(ok=True)

    @app.post('/api/jobs')
    def submit():
        body = request.get_json()
        path = photo_path(body.get('photo', ''))
        targets = body.get('printers', [])
        if not isinstance(targets, list) or not targets or len(targets) > 10 or any(type(p) is not str for p in targets):
            raise ValueError('Choose at least one printer')
        key = body.get('key', '')
        if not isinstance(key, str) or not 1 <= len(key) <= 100:
            raise ValueError('Request key required')
        queue = body.get('queue')
        if type(queue) is not bool:
            raise ValueError('Choose whether offline jobs should queue')
        options = body.get('options', {})
        if not isinstance(options, dict):
            raise ValueError('Print settings must be an object')
        raster = render(path, options)
        d = Delivery(dbpath)
        outcomes = []
        try:
            for target in dict.fromkeys(targets):
                if not d.db.execute('SELECT 1 FROM printer_access a WHERE a.printer=? AND (a.owner=? OR EXISTS (SELECT 1 FROM printer_shares s WHERE s.printer=a.printer AND s.user=?))', (target,g.user['id'],g.user['id'])).fetchone():
                    raise ValueError('Unknown printer')
            for target in dict.fromkeys(targets):
                try:
                    if raster.width != 384 and d.db.execute('SELECT 1 FROM printer_devices WHERE printer=?',(target,)).fetchone():
                        raise ValueError('MXW01 requires 384 dots; change print width')
                    # Fixed timing on retry preserves idempotency.
                    scoped_key = g.user['id'] + ':' + g.album + ':' + key + ':' + target
                    prior = d.db.execute('SELECT due,expires FROM jobs WHERE request_key=?', (scoped_key,)).fetchone()
                    due = prior['due'] if prior else time.time()
                    expires = prior['expires'] if prior else due + (86400 if queue else 15)
                    job = d.submit(scoped_key, target, body['photo'], queue, due, expires, body.get('reprint') is True)
                    d.db.execute('INSERT OR IGNORE INTO job_access VALUES (?,?,?)', (job,g.album,g.user['id']))
                    existing = d.db.execute('SELECT options FROM artifacts WHERE job=?', (job,)).fetchone()
                    packed = json.dumps(options, sort_keys=True)
                    if existing and existing['options'] != packed:
                        raise ValueError('Retry must use the original print settings')
                    if not existing:
                        raster.save(root / 'renders' / (job + '.png'))
                        d.db.execute('INSERT INTO artifacts VALUES (?,?)', (job, packed))
                    outcomes.append(dict(printer=target, id=job))
                except ValueError as e:
                    outcomes.append(dict(printer=target, error=str(e)))
        finally:
            d.db.close()
        return jsonify(results=outcomes)

    @app.post('/api/jobs/<job>/resolve')
    def resolve_delivery(job):
        state = request.get_json().get('state')
        if state not in ('printed', 'failed'):
            raise ValueError('Choose printed or not printed')
        db = connection()
        try:
            row = db.execute("SELECT j.state FROM jobs j JOIN printer_access p ON p.printer=j.printer WHERE j.id=? AND p.owner=?", (job,g.user['id'])).fetchone()
            if not row:
                abort(404)
            if row['state'] != 'uncertain':
                raise ValueError('Only uncertain jobs can be resolved')
            db.execute('UPDATE jobs SET state=? WHERE id=?', (state,job))
            db.commit()
        finally:
            db.close()
        return jsonify(ok=True)

    @app.get('/api/prints/<job>')
    def printed(job):
        import uuid
        db = connection()
        try:
            if not db.execute('SELECT 1 FROM job_access WHERE job=? AND album=?', (job,g.album)).fetchone():
                abort(404)
        finally:
            db.close()
        try:
            if str(uuid.UUID(job)) != job:
                abort(404)
        except ValueError:
            abort(404)
        path = root / 'renders' / (job + '.png')
        if not path.exists():
            abort(404)
        return send_file(path, mimetype='image/png')

    app.config['DATA_ROOT'] = root
    return app
