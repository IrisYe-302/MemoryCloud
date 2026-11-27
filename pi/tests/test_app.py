import base64
import io
from pathlib import Path
import tempfile
import unittest
from PIL import Image
from app import create_app
from worker import tick


class AppTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app(self.tmp.name, 'test-password')
        self.client = self.app.test_client()
        self.headers = {'X-Memory-Client':'web'}
        r=self.client.post('/api/auth/register',json={'username':'owner','password':'owner-password-123','setup_code':'test-password'},headers=self.headers)
        self.assertEqual(r.status_code,200)

    def tearDown(self):
        self.tmp.cleanup()

    def upload(self):
        image=io.BytesIO()
        Image.new('RGB',(100,80),'orange').save(image,format='PNG')
        image.seek(0)
        r=self.client.post('/api/photos',data={'photo':(image,'photo.png')},headers=self.headers)
        self.assertEqual(r.status_code,201)
        return r.json['id']

    def test_auth_and_request_guard(self):
        self.assertEqual(self.app.test_client().get('/api/state').status_code,401)
        self.assertEqual(self.client.post('/api/photos').status_code,403)

    def test_suggestions_require_approval_and_respect_history(self):
        pid=self.upload()
        def suggest(**kw):
            return self.client.post('/api/suggestions',json={'printer':'desk',**kw},headers=self.headers)
        self.assertEqual(suggest().json['photo']['id'],pid)
        self.assertEqual(self.client.get('/api/state').json['jobs'],[])
        self.assertIsNone(suggest(seen=[pid]).json['photo'])
        self.assertEqual(suggest(printer='someone-elses-printer').status_code,404)
        self.assertEqual(suggest(seen='bad').status_code,400)
        self.assertEqual(self.app.test_client().post('/api/suggestions',json={'printer':'desk'},headers=self.headers).status_code,401)
        body={'photo':pid,'printers':['desk'],'queue':True,'options':{},'key':'approved'}
        self.client.post('/api/jobs',json=body,headers=self.headers)
        self.assertIsNone(suggest().json['photo'])
        # A second approval after another request has queued the photo cannot duplicate it.
        body['key']='racing-approval'
        result=self.client.post('/api/jobs',json=body,headers=self.headers)
        self.assertIn('error',result.json['results'][0])
        tick(self.tmp.name)
        self.assertIsNone(suggest().json['photo'])

    def test_upload_preview_and_simulated_offline_delivery(self):
        pid=self.upload()
        self.assertEqual(self.upload(),pid)
        preview=self.client.post('/api/preview/'+pid,json={'caption':'Hello!'},headers=self.headers)
        self.assertEqual(preview.status_code,200)
        image=Image.open(io.BytesIO(preview.data))
        self.assertEqual(image.mode,'1')
        self.assertEqual(image.width,384)
        body={'photo':pid,'printers':['desk','friend'],'queue':True,'options':{},'key':'first'}
        r=self.client.post('/api/jobs',json=body,headers=self.headers)
        self.assertEqual(len(r.json['results']),2)
        tick(self.tmp.name)
        jobs=self.client.get('/api/state',headers=self.headers).json['jobs']
        self.assertEqual({j['printer']:j['state'] for j in jobs},{'desk':'printed','friend':'pending'})
        self.client.post('/api/printers/friend',json={'online':True},headers=self.headers)
        tick(self.tmp.name)
        jobs=self.client.get('/api/state',headers=self.headers).json['jobs']
        self.assertTrue(all(j['state']=='printed' for j in jobs))
        retry=self.client.post('/api/jobs',json=body,headers=self.headers)
        self.assertEqual(retry.json,r.json)
        artifact=self.client.get('/api/prints/'+jobs[0]['id'],headers=self.headers)
        self.assertEqual(artifact.status_code,200)
        artifact.close()

    def test_skip_offline_and_reject_invalid_images(self):
        pid=self.upload()
        self.client.post('/api/jobs',json={'photo':pid,'printers':['friend'],'queue':False,'options':{},'key':'skip'},headers=self.headers)
        tick(self.tmp.name)
        self.assertEqual(self.client.get('/api/state',headers=self.headers).json['jobs'][0]['state'],'skipped')
        r=self.client.post('/api/photos',data={'photo':(io.BytesIO(b'not an image'),'bad.png')},headers=self.headers)
        self.assertEqual(r.status_code,400)

    def test_color_copy_preserves_original_and_records_contributor(self):
        pid=self.upload()
        path=Path(self.tmp.name)/'photos'/(pid+'.jpg')
        original=path.read_bytes()
        before=self.client.get('/api/state').json['photos'][0]
        self.assertEqual(before['contributor'],'Owner')
        adjustments={'saturation':0,'warmth':0.4,'exposure':1.1}
        preview=self.client.post('/api/photos/'+pid+'/color-preview',json=adjustments,headers=self.headers)
        self.assertEqual(preview.status_code,200)
        self.assertEqual(Image.open(io.BytesIO(preview.data)).mode,'RGB')
        self.assertEqual(len(self.client.get('/api/state').json['photos']),1)
        copy=self.client.post('/api/photos/'+pid+'/color-copy',json=adjustments,headers=self.headers)
        self.assertEqual(copy.status_code,201)
        copied=copy.json['id']
        self.assertNotEqual(copied,pid)
        self.assertEqual(path.read_bytes(),original)
        photos=self.client.get('/api/state').json['photos']
        self.assertEqual(len(photos),2)
        self.assertEqual(photos[0]['original'],pid)
        self.assertEqual(photos[0]['contributor'],'Owner')
        self.assertGreaterEqual(photos[0]['added'],before['added'])
        for suffix in ('color-preview','color-copy'):
            self.assertEqual(self.client.post('/api/photos/'+pid+'/'+suffix,json={'warmth':3},headers=self.headers).status_code,400)
            self.assertEqual(self.app.test_client().post('/api/photos/'+pid+'/'+suffix,json={},headers=self.headers).status_code,401)
        other=self.client.post('/api/albums',json={'name':'Other'},headers=self.headers).json['id']
        self.client.post('/api/albums/select',json={'album':other},headers=self.headers)
        for suffix in ('color-preview','color-copy'):
            self.assertEqual(self.client.post('/api/photos/'+pid+'/'+suffix,json={},headers=self.headers).status_code,404)
