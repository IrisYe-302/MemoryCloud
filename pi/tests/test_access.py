import io
import sqlite3
import tempfile
import unittest
import os
from unittest.mock import patch
from contextlib import closing
from PIL import Image
from access import digest
from app import create_app
from worker import tick


class AccessTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.app=create_app(self.tmp.name,'setup-secret')
        self.owner=self.app.test_client()
        self.guest=self.app.test_client()
        self.h={'X-Memory-Client':'web'}
        self.post(self.owner,'/api/auth/register',{'username':'owner','password':'owner-password-123','setup_code':'setup-secret'})
        self.album=self.owner.get('/api/account').json['selected']

    def tearDown(self):
        self.tmp.cleanup()

    def post(self,client,path,body,status=200):
        r=client.post(path,json=body,headers=self.h)
        self.assertEqual(r.status_code,status,r.data)
        return r

    def invitation(self):
        return self.post(self.owner,'/api/invites',{'hours':24}).json['token']

    def join(self):
        token=self.invitation()
        self.post(self.guest,'/api/auth/register',{'username':'guest','password':'guest-password-123','invite':token})
        return token

    def photo(self):
        stream=io.BytesIO()
        Image.new('RGB',(20,20),'blue').save(stream,format='PNG')
        stream.seek(0)
        return self.owner.post('/api/photos',data={'photo':(stream,'blue.png')},headers=self.h).json['id']

    def test_invitation_required_single_use_and_owner_only(self):
        self.post(self.guest,'/api/auth/register',{'username':'guest','password':'guest-password-123','invite':'invalid'},400)
        token=self.join()
        self.post(self.guest,'/api/invites',{'hours':24},403)
        self.post(self.guest,'/api/invites/revoke',{},403)
        self.post(self.guest,'/api/invites/accept',{'invite':token},400)
        self.assertEqual(len(self.owner.get('/api/account').json['members']),2)

    def test_expired_and_revoked_invites(self):
        token=self.invitation()
        with closing(sqlite3.connect(self.tmp.name+'/memory.db')) as db:
            db.execute('UPDATE invites SET expires=0 WHERE token=?',(digest(token),))
            db.commit()
        self.post(self.guest,'/api/auth/register',{'username':'guest','password':'guest-password-123','invite':token},400)
        token=self.invitation()
        self.post(self.owner,'/api/invites/revoke',{})
        self.post(self.guest,'/api/auth/register',{'username':'guest','password':'guest-password-123','invite':token},400)

    def test_album_isolation_covers_files_previews_jobs_and_printers(self):
        self.join()
        pid=self.photo()
        body={'photo':pid,'printers':['desk'],'queue':True,'options':{},'key':'one'}
        job=self.post(self.owner,'/api/jobs',body).json['results'][0]['id']
        private=self.post(self.owner,'/api/albums',{'name':'Private album'}).json['id']
        self.post(self.guest,'/api/albums/select',{'album':private},404)
        self.post(self.owner,'/api/albums/select',{'album':private})
        state=self.owner.get('/api/state').json
        self.assertEqual(state['photos'],[])
        self.assertEqual(state['jobs'],[])
        self.assertEqual(len(state['printers']),2)
        self.assertEqual(self.owner.get('/api/photos/'+pid).status_code,404)
        self.assertEqual(self.owner.get('/api/prints/'+job).status_code,404)
        self.post(self.owner,'/api/preview/'+pid,{},404)
        self.post(self.owner,'/api/jobs',body,404)
        self.post(self.owner,'/api/printers/desk',{'online':False})
        private_photo=self.photo()
        # Identical content can be added to a separate album without giving access
        # to its printers or print jobs.
        private_printer=self.post(self.owner,'/api/printers',{'name':'Private printer'}).json['id']
        self.post(self.guest,'/api/jobs',dict(body,printers=[private_printer]),400)

    def test_member_can_print_but_only_owner_controls_printer(self):
        self.join()
        pid=self.photo()
        self.post(self.guest,'/api/printers/desk',{'online':False},404)
        self.post(self.owner,'/api/printers/desk/shares',{'username':'guest'})
        job=self.post(self.guest,'/api/jobs',{'photo':pid,'printers':['desk'],'queue':True,'options':{},'key':'one'}).json['results'][0]['id']
        tick(self.tmp.name)
        self.assertEqual(self.guest.get('/api/state').json['jobs'][0]['state'],'printed')
        response=self.guest.get('/api/prints/'+job)
        self.assertEqual(response.status_code,200)
        response.close()
        printer=self.post(self.guest,'/api/printers',{'name':'Guest desk'}).json['id']
        self.post(self.guest,'/api/printers/'+printer,{'online':True})
        self.post(self.owner,'/api/printers/'+printer,{'online':False},404)

    def test_logout_invalidates_session_and_password_is_hashed(self):
        cookie=self.owner.get_cookie('memory_session').value
        self.post(self.owner,'/api/auth/logout',{})
        self.owner.set_cookie('memory_session',cookie)
        self.assertEqual(self.owner.get('/api/state').status_code,401)
        self.post(self.owner,'/api/auth/login',{'username':'owner','password':'wrong-password-123'},401)
        self.post(self.owner,'/api/auth/login',{'username':'owner','password':'owner-password-123'})
        with closing(sqlite3.connect(self.tmp.name+'/memory.db')) as db:
            self.assertTrue(db.execute('SELECT password FROM users').fetchone()[0].startswith('scrypt:'))
            self.assertNotEqual(db.execute('SELECT token FROM sessions').fetchone()[0],self.owner.get_cookie('memory_session').value)

    def test_remove_photo_is_album_scoped_and_keeps_prints(self):
        pid=self.photo()
        job=self.post(self.owner,'/api/jobs',{'photo':pid,'printers':['desk'],'queue':True,'options':{},'key':'remove-test'}).json['results'][0]['id']
        other=self.post(self.owner,'/api/albums',{'name':'Other'}).json['id']
        self.post(self.owner,'/api/albums/select',{'album':other})
        self.assertEqual(self.photo(),pid)
        self.assertEqual(self.guest.delete('/api/photos/'+pid,json={},headers=self.h).status_code,401)
        self.post(self.owner,'/api/albums/select',{'album':self.album})
        self.assertEqual(self.owner.delete('/api/photos/'+pid,json={},headers=self.h).status_code,200)
        self.assertEqual(self.owner.get('/api/photos/'+pid).status_code,404)
        tick(self.tmp.name)
        response=self.owner.get('/api/prints/'+job)
        self.assertEqual(response.status_code,200)
        response.close()

        self.post(self.owner,'/api/albums/select',{'album':other})
        response=self.owner.get('/api/photos/'+pid)
        self.assertEqual(response.status_code,200)
        response.close()

    def test_printer_sharing_is_explicit_revocable_and_independent_of_album(self):
        self.join()
        pid=self.photo()
        body={'photo':pid,'printers':['desk'],'queue':True,'options':{},'key':'share-test'}
        self.assertEqual(self.guest.get('/api/state').json['printers'],[])
        self.post(self.guest,'/api/jobs',body,400)
        self.post(self.guest,'/api/printers/desk/shares',{'username':'owner'},404)
        self.post(self.owner,'/api/printers/desk/shares',{'username':'guest'})
        private=self.post(self.guest,'/api/albums',{'name':'Guest private'}).json['id']
        self.post(self.guest,'/api/albums/select',{'album':private})
        stream=io.BytesIO()
        Image.new('RGB',(20,20),'red').save(stream,format='PNG')
        stream.seek(0)
        pid=self.guest.post('/api/photos',data={'photo':(stream,'red.png')},headers=self.h).json['id']
        self.assertEqual([p['id'] for p in self.guest.get('/api/state').json['printers']],['desk'])
        self.post(self.guest,'/api/suggestions',{'printer':'desk'})
        self.post(self.guest,'/api/jobs',dict(body,photo=pid))
        self.post(self.guest,'/api/printers/desk',{'online':False},404)
        uid=self.guest.get('/api/account').json['user']['id']
        self.assertEqual(self.owner.delete('/api/printers/desk/shares/'+uid,json={},headers=self.h).status_code,200)
        self.assertEqual(self.guest.get('/api/state').json['printers'],[])
        self.post(self.guest,'/api/jobs',dict(body,photo=pid,key='revoked'),400)
        self.post(self.guest,'/api/suggestions',{'printer':'desk'},404)

    def test_existing_user_can_accept_other_album_invitation(self):
        self.join()
        album=self.post(self.owner,'/api/albums',{'name':'Another album'}).json['id']
        self.post(self.owner,'/api/albums/select',{'album':album})
        token=self.invitation()
        self.post(self.guest,'/api/invites/accept',{'invite':token})
        self.assertEqual(self.guest.get('/api/account').json['selected'],album)

    def test_cross_origin_and_malformed_json(self):
        r=self.owner.post('/api/albums',json={'name':'No'},headers={**self.h,'Origin':'https://other.example'})
        self.assertEqual(r.status_code,403)
        self.post(self.owner,'/api/albums',[],400)

    def test_setup_protects_existing_data(self):
        self.post(self.guest,'/api/auth/register',{'username':'newuser','password':'password-long-123','setup_code':'setup-secret'})
        self.assertNotEqual(self.guest.get('/api/account').json['selected'],self.album)
        self.assertEqual(self.guest.get('/api/state').json,{'photos':[],'printers':[],'jobs':[]})
        self.post(self.guest,'/api/albums/select',{'album':self.album},404)

    def test_session_survives_app_restart(self):
        cookie=self.owner.get_cookie('memory_session').value
        restarted=create_app(self.tmp.name,'setup-secret').test_client()
        restarted.set_cookie('memory_session',cookie)
        self.assertEqual(restarted.get('/api/account').json['selected'],self.album)

    def test_explicit_album_scope_is_checked(self):
        self.join()
        private=self.post(self.owner,'/api/albums',{'name':'Private'}).json['id']
        r=self.guest.get('/api/state',headers={'X-Memory-Album':private})
        self.assertEqual(r.status_code,404)
        self.assertEqual(self.guest.get('/api/state?album='+private).status_code,404)
        self.post(self.owner,'/api/albums/select',{'album':private})
        r=self.owner.get('/api/state',headers={'X-Memory-Album':self.album})
        self.assertEqual(len(r.json['printers']),2)

    def test_https_proxy_origin_and_secure_cookie(self):
        with patch.dict(os.environ,{'MEMORY_HTTPS':'1'}):
            client=create_app(self.tmp.name,'setup-secret').test_client()
        r=client.post('/api/auth/login',json={'username':'owner','password':'owner-password-123'},headers={**self.h,'Origin':'https://localhost','X-Forwarded-Proto':'https'})
        self.assertEqual(r.status_code,200)
        self.assertIn('Secure;',r.headers['Set-Cookie'])

    def test_existing_archive_is_adopted_without_losing_records(self):
        from delivery import Delivery
        with tempfile.TemporaryDirectory() as root:
            legacy=Delivery(root+'/memory.db')
            legacy.db.executescript("CREATE TABLE photos(id TEXT PRIMARY KEY,name TEXT,created REAL); CREATE TABLE printers(id TEXT PRIMARY KEY,name TEXT,online INTEGER); INSERT INTO photos VALUES ('legacy','Old photo',1); INSERT INTO printers VALUES ('old-printer','Existing printer',0);")
            job=legacy.submit('legacy-key','old-printer','legacy',True,1,9999999999)
            legacy.db.close()
            app=create_app(root,'setup-secret')
            client=app.test_client()
            self.post(client,'/api/auth/register',{'username':'owner','password':'owner-password-123','setup_code':'wrong'},400)
            self.post(client,'/api/auth/register',{'username':'owner','password':'owner-password-123','setup_code':'setup-secret'})
            state=client.get('/api/state').json
            self.assertEqual(state['photos'][0]['id'],'legacy')
            self.assertEqual(state['jobs'][0]['id'],job)
            self.assertIn('old-printer',[p['id'] for p in state['printers']])
