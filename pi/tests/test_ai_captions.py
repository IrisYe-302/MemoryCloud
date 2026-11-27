from contextlib import closing
import base64
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from PIL import Image
from app import create_app
from ai_captions import analyze, AIError

DATA={'captions':['A little sunshine.','Keeping this moment.','Worth remembering.'],'description':'A warm orange scene.','tags':['orange']}

class CaptionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.app=create_app(self.tmp.name,'setup-password')
        self.client=self.app.test_client()
        self.h={'X-Memory-Client':'web'}
        self.client.post('/api/auth/register',json={'username':'owner','password':'owner-password-123','setup_code':'setup-password'},headers=self.h)
        stream=io.BytesIO();Image.new('RGB',(1200,900),'orange').save(stream,format='PNG');stream.seek(0)
        self.pid=self.client.post('/api/photos',data={'photo':(stream,'private-name.png')},headers=self.h).json['id']
        self.url='/api/photos/'+self.pid+'/captions'
        self.env=patch.dict(os.environ,{'OPENAI_API_KEY':'test-not-real','OPENAI_CAPTION_MODEL':'gpt-5.4-mini'})
        self.env.start()
    def tearDown(self):
        self.env.stop();self.tmp.cleanup()
    def ask(self, **kwargs):
        return self.client.post(self.url,json=kwargs or {'consent':True},headers=self.h)

    @patch('ai_captions.analyze',return_value=(DATA,{'input_tokens':100,'output_tokens':50}))
    def test_cached_and_no_print_or_caption_mutation(self, provider):
        self.assertEqual(self.ask(consent=False).status_code,400)
        self.assertEqual(self.ask().json,{**DATA,'cached':False})
        self.assertEqual(self.ask().json,{**DATA,'cached':True})
        provider.assert_called_once()
        self.assertEqual(self.client.get('/api/state').json['jobs'],[])
        self.assertEqual(len(self.client.get('/api/state').json['photos']),1)
        self.assertEqual(self.app.test_client().post(self.url,json={'consent':True},headers=self.h).status_code,401)
        other=self.client.post('/api/albums',json={'name':'Empty'},headers=self.h).json['id']
        self.client.post('/api/albums/select',json={'album':other},headers=self.h)
        self.assertEqual(self.ask().status_code,404)
        provider.assert_called_once()

    @patch('ai_captions.analyze',return_value=(DATA,{}))
    def test_regenerate_replaces_cache_and_keeps_limits(self,provider):
        self.ask()
        fresh={**DATA,'captions':['A new moment.','Another little memory.','Together again.']}
        provider.return_value=(fresh,{})
        self.assertEqual(self.ask(consent=True,regenerate=True).json,{**fresh,'cached':False})
        self.assertEqual(self.ask().json,{**fresh,'cached':True})
        self.assertEqual(provider.call_count,2)
        with closing(sqlite3.connect(self.tmp.name+'/memory.db')) as db, db:
            user=db.execute('SELECT id FROM users').fetchone()[0]
            db.executemany('INSERT INTO ai_caption_attempts VALUES (?,?)',[(user,time.time())]*20)
        self.assertEqual(self.ask(consent=True,regenerate=True).status_code,429)
        self.assertEqual(self.ask().json,{**fresh,'cached':True})
        self.assertEqual(provider.call_count,2)

    @patch('ai_captions.analyze',side_effect=AIError('Service timed out',503))
    def test_failure_clears_pending_and_missing_key(self,provider):
        with patch.dict(os.environ,{'OPENAI_API_KEY':''}):
            self.assertEqual(self.ask().status_code,503)
        provider.assert_not_called()
        self.assertEqual(self.ask().status_code,503)
        with closing(sqlite3.connect(self.tmp.name+'/memory.db')) as db, db:
            self.assertEqual(db.execute('SELECT count(*) FROM ai_caption_pending').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT count(*) FROM ai_caption_cache').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT count(*) FROM ai_caption_attempts').fetchone()[0],1)

    @patch('ai_captions.analyze',return_value=(DATA,{}))
    def test_limits_and_inflight_prevent_provider_calls(self,provider):
        with closing(sqlite3.connect(self.tmp.name+'/memory.db')) as db, db:
            album=db.execute('SELECT album FROM album_photos').fetchone()[0]
            user=db.execute('SELECT id FROM users').fetchone()[0]
            db.execute('INSERT INTO ai_caption_pending VALUES (?,?,?,?,?,?)',(album,self.pid,'gpt-5.4-mini','captions-v1','token',time.time()))
        self.assertEqual(self.ask().status_code,409)
        with closing(sqlite3.connect(self.tmp.name+'/memory.db')) as db, db:
            db.execute('DELETE FROM ai_caption_pending')
            db.executemany('INSERT INTO ai_caption_attempts VALUES (?,?)',[(user,time.time())]*20)
        self.assertEqual(self.ask().status_code,429)
        provider.assert_not_called()

    def test_transport_payload_and_response_validation(self):
        result={'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(DATA)}]}],'usage':{'input_tokens':100}}
        def transport(req,timeout):
            payload=json.loads(req.data)
            self.assertFalse(payload['store'])
            self.assertEqual(payload['max_output_tokens'],700)
            self.assertEqual(timeout,20)
            content=payload['input'][0]['content'][1]
            raw=base64.b64decode(content['image_url'].split(',')[1])
            with Image.open(io.BytesIO(raw)) as image:
                self.assertLessEqual(max(image.size),768)
                self.assertFalse(image.getexif())
            self.assertNotIn('private-name',req.data.decode())
            return io.BytesIO(json.dumps(result).encode())
        path=Path(self.tmp.name)/'photos'/(self.pid+'.jpg')
        with patch('ai_captions.urllib.request.urlopen',side_effect=transport):
            self.assertEqual(analyze(path,'secret','gpt-5.4-mini')[0],DATA)
            result['status']='incomplete'
            with self.assertRaises(AIError):analyze(path,'secret','gpt-5.4-mini')
            result['status']='completed';result['output']=[]
            with self.assertRaises(AIError):analyze(path,'secret','gpt-5.4-mini')
        for error in [HTTPError('https://api.openai.com',401,'secret',{},None),URLError('secret')]:
            with patch('ai_captions.urllib.request.urlopen',side_effect=error):
                with self.assertRaises(AIError) as caught:analyze(path,'secret','gpt-5.4-mini')
                self.assertNotIn('secret',str(caught.exception))
