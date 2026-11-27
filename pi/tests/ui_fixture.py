"""Disposable browser-test server; never uses the real album directory."""
import io
import tempfile
from PIL import Image
from app import create_app

root = tempfile.mkdtemp(prefix='memory-ui-')
app = create_app(root, 'fixture-setup')
client = app.test_client()
headers = {'X-Memory-Client':'web'}
client.post('/api/auth/register', json={'username':'demo','password':'demo-owner-123','setup_code':'fixture-setup'}, headers=headers)
stream = io.BytesIO()
Image.linear_gradient('L').resize((600,600)).save(stream, format='PNG')
stream.seek(0)
client.post('/api/photos', data={'photo':(stream,'Calibration print.png')},headers=headers)
