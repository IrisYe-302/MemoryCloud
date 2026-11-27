"""Persistent delivery policies; transport and authorization belong above this layer."""
import sqlite3
import uuid


class Delivery:
    def __init__(self, path):
        self.db = sqlite3.connect(path, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute('''CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL,
            printer TEXT NOT NULL, photo TEXT NOT NULL, queue INTEGER NOT NULL,
            due REAL NOT NULL, expires REAL NOT NULL, state TEXT NOT NULL)''')

    def submit(self, key, printer, photo, queue, due, expires, reprint=False):
        if expires <= due:
            raise ValueError('Expiry must follow scheduled time')
        self.db.execute('BEGIN IMMEDIATE')
        try:
            prior = self.db.execute('SELECT * FROM jobs WHERE request_key=?', (key,)).fetchone()
            if prior:
                if tuple(prior[k] for k in ('printer', 'photo', 'queue', 'due', 'expires')) != (printer, photo, int(queue), due, expires):
                    raise ValueError('Request key reused with changed payload')
                result = prior['id']
            else:
                duplicate = self.db.execute("SELECT 1 FROM jobs WHERE printer=? AND photo=? AND state IN ('pending','sent','uncertain','printed')", (printer, photo)).fetchone()
                if duplicate and not reprint:
                    raise ValueError('Explicit reprint required')
                result = str(uuid.uuid4())
                self.db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?)', (result, key, printer, photo, int(queue), due, expires, 'pending'))
            self.db.execute('COMMIT')
            return result
        except Exception:
            self.db.execute('ROLLBACK')
            raise

    def dispatch(self, printer, online, now):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            self.db.execute("UPDATE jobs SET state='expired' WHERE printer=? AND state='pending' AND expires<=?", (printer, now))
            if not online:
                self.db.execute("UPDATE jobs SET state='skipped' WHERE printer=? AND state='pending' AND due<=? AND queue=0", (printer, now))
                jobs = []
            else:
                jobs = self.db.execute("SELECT * FROM jobs WHERE printer=? AND state='pending' AND due<=? ORDER BY due, id", (printer, now)).fetchall()
                self.db.executemany("UPDATE jobs SET state='sent' WHERE id=?", [(j['id'],) for j in jobs])
            self.db.execute('COMMIT')
            return [dict(j, state='sent') for j in jobs]
        except Exception:
            self.db.execute('ROLLBACK')
            raise

    def acknowledge(self, job, printer):
        self.db.execute("UPDATE jobs SET state='printed' WHERE id=? AND printer=? AND state IN ('sent','uncertain')", (job, printer))

    def mark_uncertain(self, printer):
        self.db.execute("UPDATE jobs SET state='uncertain' WHERE printer=? AND state='sent'", (printer,))

    def state(self, job):
        return self.db.execute('SELECT state FROM jobs WHERE id=?', (job,)).fetchone()[0]
