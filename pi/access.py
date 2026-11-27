"""Accounts, server-side sessions and album membership for the private prototype."""
import hashlib
import secrets
import sqlite3
import time
import uuid
from contextlib import closing
from flask import abort, g, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def install_access(app, dbpath, setup_password):
    def db():
        if 'access_db' not in g:
            g.access_db = sqlite3.connect(dbpath, isolation_level=None)
            g.access_db.row_factory = sqlite3.Row
        return g.access_db

    with closing(sqlite3.connect(dbpath)) as conn:
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, username TEXT UNIQUE, password TEXT);
            CREATE TABLE IF NOT EXISTS user_profiles(user TEXT PRIMARY KEY, name TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS albums(id TEXT PRIMARY KEY, name TEXT, owner TEXT);
            CREATE TABLE IF NOT EXISTS members(album TEXT, user TEXT, PRIMARY KEY(album,user));
            CREATE TABLE IF NOT EXISTS album_photos(album TEXT, photo TEXT, PRIMARY KEY(album,photo));
            CREATE TABLE IF NOT EXISTS printer_access(printer TEXT PRIMARY KEY, album TEXT, owner TEXT);
            CREATE TABLE IF NOT EXISTS printer_shares(printer TEXT, user TEXT, PRIMARY KEY(printer,user));
            CREATE TABLE IF NOT EXISTS job_access(job TEXT PRIMARY KEY, album TEXT, sender TEXT);
            CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user TEXT, album TEXT, expires REAL);
            CREATE TABLE IF NOT EXISTS invites(token TEXT PRIMARY KEY, album TEXT, expires REAL, used INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS auth_attempts(address TEXT, at REAL);
        ''')

    @app.teardown_appcontext
    def close(error):
        conn = g.pop('access_db', None)
        if conn:
            conn.close()

    def member(album):
        if not db().execute('SELECT 1 FROM members WHERE album=? AND user=?', (album, g.user['id'])).fetchone():
            abort(404)

    def owner():
        if not db().execute('SELECT 1 FROM albums WHERE id=? AND owner=?', (g.album, g.user['id'])).fetchone():
            abort(403)

    def invite(token):
        if not isinstance(token, str):
            abort(400)
        found = db().execute('SELECT * FROM invites WHERE token=? AND used=0 AND expires>?', (digest(token), time.time())).fetchone()
        if not found:
            raise ValueError('Invitation is invalid, expired or already used')
        return found

    def establish(user, album):
        db().execute('DELETE FROM sessions WHERE token=? OR expires<?', (digest(request.cookies.get('memory_session', '')), time.time()))
        token = secrets.token_urlsafe(32)
        db().execute('INSERT INTO sessions VALUES (?,?,?,?)', (digest(token), user, album, time.time()+7*86400))
        response = jsonify(ok=True)
        response.set_cookie('memory_session', token, max_age=7*86400, httponly=True, samesite='Lax', secure=app.config.get('SESSION_COOKIE_SECURE', False))
        return response

    @app.before_request
    def guard():
        if request.path.startswith('/api/device/'):
            return  # Separately authenticated with a printer-scoped bearer token.
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            if request.headers.get('X-Memory-Client') != 'web':
                abort(403)
            if request.headers.get('Sec-Fetch-Site') == 'cross-site':
                abort(403)
            origin = request.headers.get('Origin')
            if origin and origin != request.host_url.rstrip('/'):
                abort(403)
        public = ('/', '/api/auth/status', '/api/auth/login', '/api/auth/register')
        if request.path in public or request.path.startswith('/static/'):
            return
        session = db().execute('SELECT * FROM sessions WHERE token=? AND expires>?', (digest(request.cookies.get('memory_session', '')), time.time())).fetchone()
        if not session:
            return jsonify(error='Please sign in'), 401
        g.user = db().execute('SELECT u.id,u.username,COALESCE(p.name,upper(substr(u.username,1,1))||substr(u.username,2)) AS name FROM users u LEFT JOIN user_profiles p ON p.user=u.id WHERE u.id=?', (session['user'],)).fetchone()
        g.album = request.headers.get('X-Memory-Album') or request.args.get('album') or session['album']
        if not g.user:
            abort(401)
        member(g.album)

    def rate_limit():
        address = request.remote_addr or 'local'
        now = time.time()
        db().execute('BEGIN IMMEDIATE')
        db().execute('DELETE FROM auth_attempts WHERE at<?', (now-900,))
        count = db().execute('SELECT count(*) FROM auth_attempts WHERE address=?', (address,)).fetchone()[0]
        if count >= 20:
            db().execute('ROLLBACK')
            abort(429)
        db().execute('INSERT INTO auth_attempts VALUES (?,?)', (address, now))
        db().execute('COMMIT')

    def credentials():
        body = request.get_json()
        username = body.get('username', '')
        password = body.get('password', '')
        if not isinstance(username, str) or not isinstance(password, str):
            raise ValueError('Username and password must be text')
        username = username.strip().lower()
        if not 3 <= len(username) <= 40 or not all(c.isascii() and (c.isalnum() or c in '_-.') for c in username):
            raise ValueError('Use a 3–40 character username with letters, numbers, dots, dashes or underscores')
        if not 12 <= len(password) <= 128:
            raise ValueError('Use a password between 12 and 128 characters')
        return body, username, password

    @app.get('/api/auth/status')
    def auth_status():
        return jsonify(setup_required=not bool(db().execute('SELECT 1 FROM users LIMIT 1').fetchone()))

    @app.post('/api/auth/register')
    def register():
        rate_limit()
        body, username, password = credentials()
        name = body.get('name', username[:1].upper()+username[1:])
        if not isinstance(name,str) or not 1 <= len(name.strip()) <= 60 or any(ord(c)<32 for c in name):
            raise ValueError('Name must contain 1–60 characters')
        name = name.strip()
        hashed = generate_password_hash(password)
        db().execute('BEGIN IMMEDIATE')
        try:
            first = not db().execute('SELECT 1 FROM users LIMIT 1').fetchone()
            invited = None
            if first:
                code = body.get('setup_code', '')
                if not isinstance(code, str) or not secrets.compare_digest(code.encode(), setup_password.encode()):
                    raise ValueError('Incorrect setup code')
            elif body.get('invite'):
                invited = invite(body['invite'])
            user = str(uuid.uuid4())
            db().execute('INSERT INTO users VALUES (?,?,?)', (user, username, hashed))
            db().execute('INSERT INTO user_profiles VALUES (?,?)',(user,name))
            if first:
                album = str(uuid.uuid4())
                db().execute('INSERT INTO albums VALUES (?,?,?)', (album, 'Our little archive', user))
                db().execute('INSERT INTO album_photos SELECT ?,id FROM photos', (album,))
                db().execute('INSERT INTO printer_access SELECT id,?,? FROM printers', (album,user))
                db().execute('INSERT INTO job_access SELECT id,?,? FROM jobs', (album,user))
            elif invited:
                album = invited['album']
                db().execute('UPDATE invites SET used=1 WHERE token=?', (invited['token'],))
            else:
                album = str(uuid.uuid4())
                db().execute('INSERT INTO albums VALUES (?,?,?)', (album, 'My little archive', user))
            db().execute('INSERT INTO members VALUES (?,?)', (album,user))
            db().execute('COMMIT')
        except sqlite3.IntegrityError:
            db().execute('ROLLBACK')
            raise ValueError('Username is already in use')
        except Exception:
            db().execute('ROLLBACK')
            raise
        return establish(user, album)

    @app.post('/api/auth/login')
    def login():
        rate_limit()
        _, username, password = credentials()
        user = db().execute('SELECT * FROM users WHERE username=?', (username,)).fetchone()
        if not user or not check_password_hash(user['password'], password):
            return jsonify(error='Incorrect username or password'), 401
        album = db().execute('SELECT album FROM members WHERE user=? ORDER BY rowid LIMIT 1', (user['id'],)).fetchone()[0]
        return establish(user['id'], album)

    @app.post('/api/auth/logout')
    def logout():
        db().execute('DELETE FROM sessions WHERE token=?', (digest(request.cookies.get('memory_session', '')),))
        response = jsonify(ok=True)
        response.delete_cookie('memory_session')
        return response

    @app.get('/api/account')
    def account():
        return jsonify(user=dict(g.user), selected=g.album,
            albums=[dict(r) for r in db().execute('SELECT a.* FROM albums a JOIN members m ON m.album=a.id WHERE m.user=?', (g.user['id'],))],
            members=[dict(r) for r in db().execute('SELECT u.id,u.username,COALESCE((SELECT name FROM user_profiles WHERE user=u.id),upper(substr(u.username,1,1))||substr(u.username,2)) AS name FROM users u JOIN members m ON m.user=u.id WHERE m.album=?', (g.album,))])

    @app.post('/api/albums')
    def new_album():
        name = request.get_json().get('name', '')
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 60:
            raise ValueError('Album name must contain 1–60 characters')
        album = str(uuid.uuid4())
        db().execute('BEGIN IMMEDIATE')
        try:
            db().execute('INSERT INTO albums VALUES (?,?,?)', (album, name.strip(), g.user['id']))
            db().execute('INSERT INTO members VALUES (?,?)', (album, g.user['id']))
            db().execute('COMMIT')
        except Exception:
            db().execute('ROLLBACK')
            raise
        return jsonify(id=album)

    @app.post('/api/albums/select')
    def select_album():
        album = request.get_json().get('album')
        member(album)
        db().execute('UPDATE sessions SET album=? WHERE token=?', (album, digest(request.cookies.get('memory_session', ''))))
        return jsonify(ok=True)

    @app.post('/api/invites')
    def new_invite():
        owner()
        hours = request.get_json().get('hours', 24)
        if hours not in (1,24,168):
            raise ValueError('Choose 1 hour, 24 hours or 7 days')
        token = secrets.token_urlsafe(32)
        expires = time.time()+hours*3600
        db().execute('INSERT INTO invites VALUES (?,?,?,0)', (digest(token),g.album,expires))
        return jsonify(token=token,expires=expires)

    @app.post('/api/invites/revoke')
    def revoke():
        owner()
        db().execute('UPDATE invites SET used=1 WHERE album=?', (g.album,))
        return jsonify(ok=True)

    @app.post('/api/invites/accept')
    def accept():
        db().execute('BEGIN IMMEDIATE')
        try:
            invited = invite(request.get_json().get('invite', ''))
            db().execute('INSERT OR IGNORE INTO members VALUES (?,?)', (invited['album'],g.user['id']))
            db().execute('UPDATE invites SET used=1 WHERE token=?', (invited['token'],))
            db().execute('UPDATE sessions SET album=? WHERE token=?', (invited['album'],digest(request.cookies.get('memory_session',''))))
            db().execute('COMMIT')
        except Exception:
            db().execute('ROLLBACK')
            raise
        return jsonify(ok=True)

    @app.post('/api/printers')
    def new_printer():
        name = request.get_json().get('name', '')
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 40:
            raise ValueError('Printer name must contain 1–40 characters')
        printer = str(uuid.uuid4())
        db().execute('BEGIN IMMEDIATE')
        try:
            db().execute('INSERT INTO printers VALUES (?,?,0)', (printer,name.strip()))
            db().execute('INSERT INTO printer_access VALUES (?,?,?)', (printer,g.album,g.user['id']))
            db().execute('COMMIT')
        except Exception:
            db().execute('ROLLBACK')
            raise
        return jsonify(id=printer)

    @app.delete('/api/printers/<pid>')
    def delete_printer(pid):
        conn = db()
        conn.execute('BEGIN IMMEDIATE')
        try:
            if not conn.execute('SELECT 1 FROM printer_access WHERE printer=? AND owner=?', (pid,g.user['id'])).fetchone():
                abort(404)
            if conn.execute("SELECT 1 FROM jobs WHERE printer=? AND state IN ('pending','sent','uncertain')", (pid,)).fetchone():
                raise ValueError('Finish queued prints and resolve uncertain prints before deleting this printer.')
            conn.execute('DELETE FROM pending_devices WHERE printer=?', (pid,))
            conn.execute('DELETE FROM device_status WHERE printer=?', (pid,))
            conn.execute('DELETE FROM printer_devices WHERE printer=?', (pid,))
            conn.execute('DELETE FROM printer_shares WHERE printer=?', (pid,))
            conn.execute('DELETE FROM printer_access WHERE printer=?', (pid,))
            conn.execute('DELETE FROM printers WHERE id=?', (pid,))
            conn.execute('COMMIT')
        except Exception:
            conn.execute('ROLLBACK')
            raise
        return jsonify(ok=True)

    @app.patch('/api/printers/<pid>')
    def rename_printer(pid):
        name = request.get_json().get('name', '')
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 40:
            raise ValueError('Printer name must contain 1–40 characters')
        if not db().execute('SELECT 1 FROM printer_access WHERE printer=? AND owner=?', (pid,g.user['id'])).fetchone():
            abort(404)
        db().execute('UPDATE printers SET name=? WHERE id=?', (name.strip(),pid))
        return jsonify(ok=True)

    @app.get('/api/printers/<pid>/shares')
    def printer_shares(pid):
        if not db().execute('SELECT 1 FROM printer_access WHERE printer=? AND owner=?', (pid,g.user['id'])).fetchone():
            abort(404)
        return jsonify(users=[dict(r) for r in db().execute('SELECT u.id,u.username FROM users u JOIN printer_shares s ON s.user=u.id WHERE s.printer=? ORDER BY u.username', (pid,))])

    @app.post('/api/printers/<pid>/shares')
    def share_printer(pid):
        if not db().execute('SELECT 1 FROM printer_access WHERE printer=? AND owner=?', (pid,g.user['id'])).fetchone():
            abort(404)
        username=request.get_json().get('username')
        if not isinstance(username,str):
            raise ValueError('Enter an existing account username')
        user=db().execute('SELECT id FROM users WHERE username=?', (username.strip().lower(),)).fetchone()
        if not user:
            raise ValueError('No account with that username')
        if user['id']==g.user['id']:
            raise ValueError('You already own this printer')
        db().execute('INSERT OR IGNORE INTO printer_shares VALUES (?,?)', (pid,user['id']))
        return jsonify(ok=True)

    @app.delete('/api/printers/<pid>/shares/<uid>')
    def unshare_printer(pid,uid):
        if not db().execute('SELECT 1 FROM printer_access WHERE printer=? AND owner=?', (pid,g.user['id'])).fetchone():
            abort(404)
        db().execute('DELETE FROM printer_shares WHERE printer=? AND user=?', (pid,uid))
        return jsonify(ok=True)
