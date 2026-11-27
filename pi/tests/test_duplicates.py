import io
import tempfile
import unittest
from pathlib import Path
from PIL import Image, PngImagePlugin
from app import create_app
from worker import tick


class DuplicateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app(self.tmp.name, 'setup-password')
        self.client = self.app.test_client()
        self.h = {'X-Memory-Client': 'web'}
        self.post('/api/auth/register', {'username':'owner', 'password':'owner-password-123', 'setup_code':'setup-password'})

    def tearDown(self):
        self.tmp.cleanup()

    def post(self, url, body):
        return self.client.post(url, json=body, headers=self.h)

    def upload(self, label, color=(120,80,40)):
        stream = io.BytesIO()
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text('comment', label)
        Image.new('RGB', (100,80), color).save(stream, format='PNG', pnginfo=metadata)
        stream.seek(0)
        response = self.client.post('/api/photos', data={'photo':(stream,'photo.png')}, headers=self.h)
        self.assertEqual(response.status_code,201)
        return response.json['id']

    def test_exact_similar_and_unrelated_review_without_mutation(self):
        a, b = self.upload('a'), self.upload('b')
        similar = self.upload('c',(122,82,42))
        unrelated = self.upload('d',(20,210,180))
        groups = self.client.get('/api/duplicates').json['groups']
        self.assertEqual(len(groups),1)
        self.assertEqual({p['id'] for p in groups[0]}, {a,b,similar})
        self.assertNotIn(unrelated,{p['id'] for p in groups[0]})
        self.assertEqual(len(self.client.get('/api/state').json['photos']),4)
        # Two identical normalized photos are labeled exact even with different upload bytes.
        matches = self.client.get('/api/duplicates').json['groups'][0]
        self.assertIn('exact',[p['match'] for p in matches])
        self.assertIn('similar',[p['match'] for p in matches])

    def test_remove_preserves_other_album_source_and_print(self):
        a, b = self.upload('a'), self.upload('b')
        job = self.post('/api/jobs', {'photo':b,'printers':['desk'],'queue':True,'options':{},'key':'duplicate-test'}).json['results'][0]['id']
        import sqlite3
        with sqlite3.connect(self.tmp.name+'/memory.db') as db:
            album = db.execute('SELECT album FROM album_photos WHERE photo=?',(a,)).fetchone()[0]
        other = self.post('/api/albums',{'name':'Other'}).json['id']
        self.post('/api/albums/select',{'album':other})
        self.assertEqual(self.upload('b'),b)
        self.post('/api/albums/select',{'album':album})
        self.assertEqual(self.post('/api/duplicates/remove',{'keep':a,'remove':[b]}).json,{'removed':1})
        self.assertEqual([p['id'] for p in self.client.get('/api/state').json['photos']],[a])
        self.assertTrue((Path(self.tmp.name)/'photos'/(b+'.jpg')).exists())
        tick(self.tmp.name)
        response = self.client.get('/api/prints/'+job)
        self.assertEqual(response.status_code,200)
        response.close()
        self.post('/api/albums/select',{'album':other})
        self.assertEqual([p['id'] for p in self.client.get('/api/state').json['photos']],[b])

    def test_invalid_selection_is_atomic_and_auth_required(self):
        a, b = self.upload('a'), self.upload('b')
        for body in ({'keep':a,'remove':[b,'missing']},{'keep':a,'remove':[a,b]}, {'keep':a,'remove':[b,b]}, {'keep':a,'remove':[]}):
            self.assertEqual(self.post('/api/duplicates/remove',body).status_code,400)
            self.assertEqual(len(self.client.get('/api/state').json['photos']),2)
        guest = self.app.test_client()
        self.assertEqual(guest.get('/api/duplicates').status_code,401)
        self.assertEqual(guest.post('/api/duplicates/remove',json={'keep':a,'remove':[b]},headers=self.h).status_code,401)
        other = self.post('/api/albums',{'name':'Empty'}).json['id']
        self.post('/api/albums/select',{'album':other})
        self.assertEqual(self.client.get('/api/duplicates').json['groups'],[])
        self.assertEqual(self.post('/api/duplicates/remove',{'keep':a,'remove':[b]}).status_code,400)
