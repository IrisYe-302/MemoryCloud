import unittest
import tempfile
import sqlite3
from pathlib import Path
from app import create_app

class PrinterSetup(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.app=create_app(self.root,'setup-secret');self.owner=self.app.test_client();self.guest=self.app.test_client()
        self.h={'X-Memory-Client':'web'}
        self.owner.post('/api/auth/register',headers=self.h,json={'username':'iris','name':'Iris Chen','password':'test-password-123','setup_code':'setup-secret'})
        self.guest.post('/api/auth/register',headers=self.h,json={'username':'other','name':'Other Person','password':'test-password-123'})
        self.pid=self.owner.post('/api/printers',headers=self.h,json={'name':'Kitchen'}).json['id']
        self.body={'address':'12:34:56:78:9A:BC','ssid':'Guest','password':''}
    def tearDown(self): self.temp.cleanup()
    def test_name_separate_from_username(self):
        u=self.owner.get('/api/account').json['user']
        self.assertEqual(u['name'],'Iris Chen');self.assertEqual(u['username'],'iris')
        with sqlite3.connect(self.root/'memory.db') as db:db.execute('DELETE FROM user_profiles WHERE user=?',(u['id'],))
        self.assertEqual(self.owner.get('/api/account').json['user']['name'],'Iris')
    def test_rename_owner_only(self):
        path=f'/api/printers/{self.pid}'
        self.assertEqual(self.guest.patch(path,headers=self.h,json={'name':'Stolen'}).status_code,404)
        self.assertEqual(self.owner.patch(path,headers=self.h,json={'name':'  Bedroom  '}).status_code,200)
        self.assertEqual(self.owner.patch(path,headers=self.h,json={'name':' '}).status_code,400)
        printers=self.owner.get('/api/state').json['printers']
        self.assertEqual(next(p['name'] for p in printers if p['id']==self.pid),'Bedroom')
    def connect(self,client=None,body=None):
        return (client or self.owner).post(f'/api/printers/{self.pid}/connect',base_url='https://localhost',headers=self.h,json=body or self.body)
    def test_enrollment_scoped_rotating_private(self):
        self.assertEqual(self.connect(self.guest).status_code,404)
        response=self.connect();self.assertEqual(response.status_code,200,response.data)
        config=response.json['config'];self.assertEqual(config['address'],self.body['address'])
        first={'Authorization':'Bearer '+config['token']}
        self.assertEqual(self.owner.post('/api/device/claim',headers=first).status_code,204)
        new=self.connect().json['config']
        self.assertNotEqual(new['token'],config['token'])
        self.assertEqual(self.owner.post('/api/device/claim',headers=first).status_code,204)
        self.assertEqual(self.owner.post('/api/device/claim',headers={'Authorization':'Bearer '+new['token']}).status_code,204)
        self.assertEqual(self.owner.post('/api/device/claim',headers=first).status_code,401)
        self.assertNotIn(config['token'],str(self.owner.get('/api/state').json))
    def test_reject_invalid_and_inflight(self):
        self.assertEqual(self.connect(body={**self.body,'address':'invalid'}).status_code,400)
        self.assertEqual(self.owner.post(f'/api/printers/{self.pid}/connect',headers=self.h,json=self.body).status_code,400)
        with sqlite3.connect(self.root/'memory.db') as db:
            db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?)',('job','key',self.pid,'photo',1,0,9999999999,'uncertain'))
        self.assertEqual(self.connect().status_code,400)

    def test_sharing_list_accepts_empty_get_with_json_header(self):
        response=self.owner.get(f'/api/printers/{self.pid}/shares',headers={**self.h,'Content-Type':'application/json'})
        self.assertEqual(response.status_code,200,response.data)
        self.assertEqual(response.json,{'users':[]})
        bad=self.owner.post(f'/api/printers/{self.pid}/shares',headers={**self.h,'Content-Type':'application/json'},data='')
        self.assertEqual(bad.status_code,400)

    def test_delete_owner_only_and_revokes_device(self):
        token=self.connect().json['config']['token']
        path=f'/api/printers/{self.pid}'
        self.assertEqual(self.guest.delete(path,headers=self.h,json={}).status_code,404)
        self.assertEqual(self.owner.delete(path,headers=self.h,json={}).status_code,200)
        self.assertNotIn(self.pid,[p['id'] for p in self.owner.get('/api/state').json['printers']])
        self.assertEqual(self.owner.post('/api/device/claim',headers={'Authorization':'Bearer '+token}).status_code,401)

    def test_delete_blocks_outstanding_jobs(self):
        with sqlite3.connect(self.root/'memory.db') as db:
            db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?)',('job','key',self.pid,'photo',1,0,9999999999,'pending'))
        for status in ('pending','sent','uncertain'):
            with sqlite3.connect(self.root/'memory.db') as db:db.execute('UPDATE jobs SET state=?',(status,))
            self.assertEqual(self.owner.delete(f'/api/printers/{self.pid}',headers=self.h,json={}).status_code,400)
        with sqlite3.connect(self.root/'memory.db') as db:db.execute("UPDATE jobs SET state='printed'")
        self.assertEqual(self.owner.delete(f'/api/printers/{self.pid}',headers=self.h,json={}).status_code,200)
        with sqlite3.connect(self.root/'memory.db') as db:self.assertEqual(db.execute('SELECT state FROM jobs').fetchone()[0],'printed')

    def test_heartbeat_reports_esp_separately(self):
        token=self.connect().json['config']['token']
        headers={'Authorization':'Bearer '+token}
        self.assertEqual(self.owner.post('/api/device/heartbeat',headers=headers,json={'printer_connected':False}).status_code,200)
        p=next(p for p in self.owner.get('/api/state').json['printers'] if p['id']==self.pid)
        self.assertGreater(p['last_seen'],0)
        self.assertFalse(p['online']);self.assertFalse(p['printer_connected'])
        self.assertEqual(self.owner.post('/api/device/heartbeat',headers=headers,json={'printer_connected':True}).status_code,200)
        p=next(p for p in self.owner.get('/api/state').json['printers'] if p['id']==self.pid)
        self.assertTrue(p['online']);self.assertTrue(p['printer_connected'])
        self.assertEqual(self.owner.post('/api/device/heartbeat',headers=headers,json={'printer_connected':'yes'}).status_code,400)
