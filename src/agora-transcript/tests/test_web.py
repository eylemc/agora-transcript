import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer
import web

class WebTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), web.Handler)
        self.server.jobs = web.Jobs(self.root)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.temp.cleanup()
    def request(self, path, method='GET', body=None, headers=None):
        c = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
        c.request(method, path, body, headers or {})
        r = c.getresponse(); result = r.status, r.read(); c.close(); return result
    def test_existing_transcript_and_download(self):
        job = self.root / '20261005T014847Z-493fdedb'; job.mkdir()
        (job/'manifest.json').write_text(json.dumps({'status':'completed','source':'example','segment_count':1}))
        (job/'transcript.txt').write_text('Türkçe döküm')
        status, body = self.request('/api/state')
        self.assertEqual(status,200); self.assertEqual(json.loads(body)['jobs'][0]['status'],'completed')
        self.assertEqual(self.request('/download/'+job.name+'/transcript.txt'),(200,'Türkçe döküm'.encode()))
        self.assertEqual(self.request('/download/'+job.name+'/source.mp3')[0],404)
    def test_cross_origin_and_host_blocked(self):
        self.assertEqual(self.request('/api/state',headers={'Host':'evil.test'})[0],403)
        self.assertEqual(self.request('/api/jobs','POST','{}',{'Content-Type':'application/json','Origin':'https://evil.test'})[0],403)
    def test_no_local_file_or_shell_input(self):
        for url in ['/etc/passwd','https://evil.test/a','$(touch /tmp/x)']:
            self.assertEqual(self.request('/api/jobs','POST',json.dumps({'url':url}),{'Content-Type':'application/json'})[0],400)
    def test_concurrency_guard(self):
        with patch.object(web.Jobs, 'run'):
            self.assertTrue(self.server.jobs.start({'url':'https://youtu.be/cgBmqZE8XCg'}))
            self.assertFalse(self.server.jobs.start({'url':'https://youtu.be/cgBmqZE8XCg'}))
    def test_symlink_not_exposed(self):
        job = self.root / '20261005T014847Z-493fdedb'; job.mkdir()
        (job/'transcript.txt').symlink_to('/etc/passwd')
        self.assertEqual(self.request('/preview/'+job.name+'/transcript.txt')[0],404)
if __name__=='__main__': unittest.main()
