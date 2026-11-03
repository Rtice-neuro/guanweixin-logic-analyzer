import tempfile,unittest
from device_manager import DeviceManager
class Store:
 def __init__(self):self.events=[]
 def event(self,s):self.events.append(s)
class Thread:
 def __init__(self,w):self.w=w
 def start(self):self.w.connected=True
class Worker:
 def __init__(self,port,store):self.port=port;self.connected=False;self.ready=False;self.pending=False;self.observer=None;self.thread=Thread(self);self.sent=[];self.closed=False
 def status(self):return dict(port=self.port,connected=self.connected,ready=self.ready,pending=self.pending,ai_running=False,error='',external_enabled=False)
 def close(self):self.closed=True;self.connected=False
 def sync(self):self.pending=True;self.sent.append('probe')
 def send(self,c):self.sent.append(c)
 def send_ai(self,c):self.sent.append(c)
class Tests(unittest.TestCase):
 def setUp(self):
  self.ports=[dict(port='COM8',name='CP2102',pnp_id='USB\\VID_10C4&PID_EA60\\board',role='board_uart',board_candidate=True),dict(port='COM3',name='Bluetooth',pnp_id='BT',role='other',board_candidate=False)]
  self.d=DeviceManager(Store(),Worker,lambda:self.ports)
 def test_port_validation_and_unverified_transport(self):
  for port in ['COM3','COM6','COM8;whoami',None]:
   with self.assertRaises(ValueError):self.d.connect(port,probe=False)
  self.d.connect('COM8',probe=False);s=self.d.status();self.assertTrue(s['transport_connected']);self.assertFalse(s['connected']);self.assertFalse(s['protocol_verified']);self.assertIsNone(s['device_identity']['last_frame'])
  with self.assertRaises(ValueError):self.d.send({'cmd':2})
 def test_probe_ready_identity_and_busy_disconnect(self):
  self.d.connect('COM8',probe=False);self.d.probe();self.assertEqual(self.d.worker.sent,['probe'])
  with self.assertRaises(ValueError):self.d.disconnect()
  self.d.worker.pending=False;self.d.worker.ready=True;self.d.observe(self.d.generation,'ready','GWX READY v0.2');self.assertTrue(self.d.status()['connected']);self.d.send({'cmd':2});self.assertEqual(self.d.worker.sent[-1],{'cmd':2});self.d.disconnect();self.assertFalse(self.d.status()['connected']);self.assertIsNone(self.d.identity()['last_frame'])
 def test_stale_generation_and_unplug(self):
  self.d.connect('COM8',probe=False);g=self.d.generation;self.d.disconnect();self.d.connect('COM8',probe=False);self.d.observe(g,'ready','GWX READY v0.2');self.assertFalse(self.d.verified);self.d.observe(self.d.generation,'ready','GWX READY v0.2');self.assertTrue(self.d.status()['connected']);self.d.worker.connected=False;self.assertFalse(self.d.status()['connected']);self.assertFalse(self.d.verified)
 def test_frame_identity_is_received_not_database(self):
  from pathlib import Path
  import json
  r=json.loads((Path(__file__).parent/'fixtures/board_ai_legacy/board_ai_result.json').read_text(encoding='utf-8'))['capture']
  self.d.connect('COM8',probe=False);self.d.observe(self.d.generation,'record',r['raw']);info=self.d.identity();self.assertTrue(info['protocol_verified']);self.assertEqual(info['last_frame']['board_id'],r['board_id']);self.assertEqual(info['last_frame']['clock_hz'],r['clock_hz']);self.assertFalse(info['physical_output_supported'])

class HttpTests(unittest.TestCase):
 def setUp(self):
  from http.server import ThreadingHTTPServer
  from ai_workbench import AIStore,handler
  import threading
  self.tmp=tempfile.TemporaryDirectory();self.store=AIStore(self.tmp.name)
  self.manager=DeviceManager(self.store,Worker,lambda:[dict(port='COM8',name='CP2102',pnp_id='test',role='board_uart',board_candidate=True)])
  from injection_controller import InjectionController
  self.injector=InjectionController(self.manager,self.store)
  self.server=ThreadingHTTPServer(('127.0.0.1',0),handler(self.store,self.manager,'unit-token',False,self.manager,self.injector));self.url='http://127.0.0.1:'+str(self.server.server_port);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
 def tearDown(self):
  self.server.shutdown();self.server.server_close();self.manager.close();self.thread.join();self.tmp.cleanup()
 def request(self,path,body=None,token='unit-token'):
  import urllib.request,urllib.error,json
  req=urllib.request.Request(self.url+path,data=None if body is None else json.dumps(body).encode(),headers={'X-GWX-Control':token,'Content-Type':'application/json','Origin':self.url})
  try:
   with urllib.request.urlopen(req)as r:return r.status,json.load(r)
  except urllib.error.HTTPError as e:return e.code,json.load(e)
 def test_authentication_and_open_transport_not_verified(self):
  self.assertEqual(self.request('/api/device/connect',{'port':'COM8','probe':False},'bad')[0],403);self.assertIsNone(self.manager.worker)
  code,result=self.request('/api/device/connect',{'port':'COM8','probe':False});self.assertEqual(code,202);self.assertTrue(result['transport_connected']);self.assertFalse(result['connected'])
  self.assertEqual(self.request('/api/command',{'cmd':2})[0],400)
  self.manager.worker.ready=True;self.manager.observe(self.manager.generation,'ready','GWX READY v0.2');self.assertTrue(self.request('/api/status')[1]['connected'])
  self.assertEqual(self.request('/api/device/disconnect',{})[0],202);self.assertFalse(self.request('/api/status')[1]['connected'])
 def test_injection_authentication_and_old_firmware_gate(self):
  self.assertFalse(self.request('/api/injection/status')[1]['supported'])
  self.assertEqual(self.request('/api/injection/analyze',{},'bad')[0],403)
  self.manager.connect('COM8',probe=False);self.manager.worker.ready=True;self.manager.observe(self.manager.generation,'ready','GWX READY v0.2')
  code,body=self.request('/api/injection/analyze',dict(samples=[0]*64,sample_rate=100000))
  self.assertEqual(code,400);self.assertIn('r18',body['error']);self.assertEqual(self.manager.worker.sent,[]);self.assertFalse(self.manager.injection_job_active)
 def test_body_bounds_and_readonly_discovery(self):
  self.assertEqual(len(self.request('/api/device/ports')[1]['ports']),1)
  self.assertEqual(self.request('/api/device/connect',{'port':'COM8','allow_configured':True})[0],400)
  self.assertEqual(self.request('/api/device/connect',{'port':'COM8','probe':'yes'})[0],400)
  self.assertIsNone(self.manager.worker)
if __name__=='__main__':unittest.main()

