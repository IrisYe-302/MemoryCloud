import hashlib
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from PIL import Image
from app import create_app
from worker import tick
from device_api import pack_raster

class Devices(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.app=create_app(self.root,'test-password');self.client=self.app.test_client()
        self.headers={'Authorization':'Bearer device-secret'}
        with sqlite3.connect(self.root/'memory.db') as db:
            db.execute('INSERT INTO printer_devices VALUES (?,?,?)',('desk',hashlib.sha256(b'device-secret').hexdigest(),0))
            db.execute("INSERT INTO printers VALUES ('other','Other',1)")
    def tearDown(self): self.tmp.cleanup()
    def job(self,job='12345678-1234-1234-1234-123456789abc',printer='desk',width=384):
        Image.new('1',(width,100),255).save(self.root/'renders'/f'{job}.png')
        with sqlite3.connect(self.root/'memory.db') as db:
            db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?)',(job,job,printer,'photo',1,time.time()-1,time.time()+60,'pending'))
            db.execute('INSERT INTO artifacts VALUES (?,?)',(job,'{}'))
        return job
    def state(self,job):
        with sqlite3.connect(self.root/'memory.db') as db:return db.execute('SELECT state FROM jobs WHERE id=?',(job,)).fetchone()[0]
    def test_auth_and_scoping(self):
        self.assertEqual(self.client.post('/api/device/claim').status_code,401)
        j=self.job(printer='other')
        self.assertEqual(self.client.post('/api/device/claim',headers=self.headers).status_code,204)
        self.assertEqual(self.client.post(f'/api/device/jobs/{j}/result',headers=self.headers,json={'state':'printed'}).status_code,404)
    def test_simulator_excluded_and_claim_once(self):
        j=self.job();tick(self.root);self.assertEqual(self.state(j),'pending')
        r=self.client.post('/api/device/claim',headers=self.headers)
        self.assertEqual(r.status_code,200);self.assertEqual(len(r.data),4800)
        self.assertEqual(r.headers['X-Job-ID'],j)
        self.assertEqual(self.client.post('/api/device/claim',headers=self.headers).status_code,409)
        for _ in range(2):self.assertEqual(self.client.post(f'/api/device/jobs/{j}/result',headers=self.headers,json={'state':'printed'}).status_code,200)
        self.assertEqual(self.state(j),'printed')
    def test_interrupted_claim_not_replayed(self):
        j=self.job();self.client.post('/api/device/claim',headers=self.headers)
        with sqlite3.connect(self.root/'memory.db') as db:db.execute('UPDATE device_jobs SET claimed=0')
        self.assertEqual(self.client.post('/api/device/claim',headers=self.headers).status_code,409)
        self.assertEqual(self.state(j),'uncertain')
    def test_wrong_width(self):
        j=self.job(width=576)
        self.assertEqual(self.client.post('/api/device/claim',headers=self.headers).status_code,422)
        self.assertEqual(self.state(j),'failed')
    def test_bit_order_and_padding(self):
        image=Image.new('1',(384,1),255);image.putpixel((0,0),0);image.putpixel((15,0),0)
        p=self.root/'bits.png';image.save(p)
        data,height=pack_raster(p)
        self.assertEqual(height,90);self.assertEqual(data[:3],bytes([1,128,0]));self.assertEqual(len(data),4320)

    def test_owner_can_resolve_uncertain(self):
        h={'X-Memory-Client':'web'}
        owner=self.app.test_client()
        self.assertEqual(owner.post('/api/auth/register',headers=h,json={'username':'Iris','password':'a-test-password-123','setup_code':'test-password'}).status_code,200)
        j=self.job();self.client.post('/api/device/claim',headers=self.headers)
        self.client.post(f'/api/device/jobs/{j}/result',headers=self.headers,json={'state':'uncertain'})
        self.assertEqual(owner.post(f'/api/jobs/{j}/resolve',headers=h,json={'state':'failed'}).status_code,200)
        self.assertEqual(self.state(j),'failed')
        # A late device response must not overturn the owner's decision.
        self.client.post(f'/api/device/jobs/{j}/result',headers=self.headers,json={'state':'printed'})
        self.assertEqual(self.state(j),'failed')

    def test_claim_is_serialized(self):
        from concurrent.futures import ThreadPoolExecutor
        self.job()
        def call(_):
            with self.app.test_client() as client:
                return client.post('/api/device/claim',headers=self.headers).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(call,range(2))),[200,409])
