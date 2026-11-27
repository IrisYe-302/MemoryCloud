"""Simulated output adapter. Run as a separate process alongside the web app."""
import os
from pathlib import Path
import time
from delivery import Delivery
from device_api import init_devices


def tick(root):
    root = Path(root)
    init_devices(root / 'memory.db')
    d = Delivery(root / 'memory.db')
    try:
        # A server crash between job creation and raster storage must not block
        # every later job on that printer indefinitely.
        d.db.execute("UPDATE jobs SET state='failed' WHERE state='pending' AND due<? AND id NOT IN (SELECT job FROM artifacts)", (time.time()-60,))
        for printer in d.db.execute('SELECT * FROM printers WHERE id NOT IN (SELECT printer FROM printer_devices)').fetchall():
            # Only claim jobs after their immutable raster has been written.
            missing = d.db.execute("SELECT id FROM jobs WHERE state='pending' AND printer=? AND id NOT IN (SELECT job FROM artifacts)", (printer['id'],)).fetchall()
            if missing:
                continue
            for job in d.dispatch(printer['id'], bool(printer['online']), time.time()):
                if (root / 'renders' / (job['id'] + '.png')).exists():
                    d.acknowledge(job['id'], printer['id'])
                else:
                    d.mark_uncertain(printer['id'])
    finally:
        d.db.close()


if __name__ == '__main__':
    root = Path(os.environ.get('MEMORY_DATA', 'data'))
    init_devices(root / 'memory.db')
    # Recover any interrupted simulation conservatively.
    d = Delivery(root / 'memory.db')
    d.db.execute("UPDATE jobs SET state='uncertain' WHERE state='sent' AND printer NOT IN (SELECT printer FROM printer_devices)")
    d.db.close()
    while True:
        tick(root)
        time.sleep(1)
