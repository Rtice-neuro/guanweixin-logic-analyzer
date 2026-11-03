"""UART injection validation; real CPU-RTL fixtures, no physical serial port."""
import copy,io,json,tempfile,threading,unittest
from pathlib import Path
from ai_workbench import AIFramer,AIWorker,AIStore
from injection_protocol import prepare,parse_ack
from injection_controller import InjectionController
from instrument_protocol import parse_record
FIX=Path(__file__).parent/'fixtures/uart_injection_r18'
RECORDS=json.loads((FIX/'parsedrecords.json').read_text(encoding='utf-8'))
RAW=(FIX/'uart_output.log').read_bytes().decode('ascii')
BODY=dict(samples=RECORDS[0]['samples'],sample_rate=100000,rules=dict(monitor=255,pmin=6,pmax=10,missing=14))
class Store:
 def __init__(self):self.events=[]
 def event(self,text):self.events.append(text)
class Device:
 def __init__(self,mode='ok'):
  self.lock=threading.RLock();self.generation=1;self.verified=True;self.injection_job_active=False;self.mode=mode;self.sent=[];self.rid=0;self.count=0
  self.s=dict(connected=True,ready=True,pending=False,injection_state=dict(sequence=1,request_id=0,count=0,active=False))
 def raw_status(self):return copy.deepcopy(self.s)
 def send_injection(self,p):
  self.sent.append(p);op=p[4]
  if op==0:self.rid=int.from_bytes(p[5:9],'little');self.count=0
  elif op==1:self.count+=8
  self.s['injection_state']=dict(sequence=len(self.sent)+1,request_id=self.rid,count=self.count,active=op!=2)
  if self.mode=='bad_ack':self.s['injection_state']['count']=7
  if self.mode=='disconnect':self.s['connected']=False
  if self.mode=='reset':self.generation+=1
  if op==2:
   r=copy.deepcopy(RECORDS[0]);self.s['last_injected_record']=dict(request_id=self.rid,capture_id=91,status=r['status'],source=r['source'],samples=r['samples'],analysis=r['analysis'],config=r['config'],clock_hz=r['clock_hz'])
   if self.mode=='bad_samples':self.s['last_injected_record']['samples'][0]^=1
   if self.mode=='bad_config':self.s['last_injected_record']['config']['divider']+=1
   if self.mode=='missing_result':self.s.pop('last_injected_record')
class ProtocolTests(unittest.TestCase):
 def test_actual_cpu_stream_fragmented_bytewise(self):
  f=AIFramer();events=[]
  for c in RAW:events.extend(f.feed(c))
  ack=[parse_ack(r)for k,r in events if k=='injection'];records=[parse_record(r)for k,r in events if k=='record']
  self.assertEqual(len(ack),31);self.assertEqual(records[0]['faults'],[])
  self.assertEqual([(f['channel'],f['code'],f['index'])for f in records[1]['faults']],[(3,'STUCK',0),(5,'MISSING_PULSE',24)])
  self.assertEqual(records[2]['error'],'BAD_PACKET');self.assertFalse(ack[-1]['active'])
 def test_packet_layout_and_bounds(self):
  d=prepare(BODY,101);self.assertEqual(len(d['packets']),10)
  for p in d['packets']:
   self.assertEqual(len(p),16);self.assertEqual(p[:4],bytes([165,90,1,12]));x=0
   for b in p:x^=b
   self.assertEqual(x,0)
  self.assertEqual([p[5]for p in d['packets'][1:9]],list(range(0,64,8)))
  self.assertEqual(b''.join(p[6:14]for p in d['packets'][1:9]),bytes(BODY['samples']))
  for body in [dict(BODY,samples=[0]*63),dict(BODY,samples=[True]*64),dict(BODY,samples=[256]*64),dict(BODY,sample_rate=float('nan')),dict(BODY,sample_rate=1),dict(BODY,rules={'monitor':0}),dict(BODY,unknown=1)]:
   with self.assertRaises(ValueError):prepare(body,101)
 def test_ack_integrity_and_truncation_recovery(self):
  raw=next(r for k,r in AIFramer().feed(RAW)if k=='injection')
  for broken in [raw.replace('47574931','00000000'),raw.replace('COUNT=00000000','COUNT=00000001'),raw.replace('VERSION=00000001','VERSION=00000001\r\nVERSION=00000001')]:
   with self.assertRaises(ValueError):parse_ack(broken)
  f=AIFramer();events=f.feed('GWX INJECT BEGIN\r\nVERSION=00000001\r\n'+RECORDS[0]['raw'])
  self.assertEqual(len([1 for k,r in events if k=='record']),1);self.assertFalse(any(k=='injection'for k,r in events))
 def test_worker_keeps_real_returned_data(self):
  with tempfile.TemporaryDirectory()as tmp:
   store=AIStore(tmp);w=AIWorker('COM_TEST',store);w.connected=True;w.ready=True;w.process=type('Process',(),{'stdin':io.StringIO()})()
   with self.assertRaises(ValueError):w.send_injection(prepare(BODY,101)['packets'][0])
   for kind,raw in AIFramer().feed(RAW):w.handle_frame(kind,raw)
   self.assertEqual(w.last_injected_record['request_id'],102);self.assertEqual(w.last_injected_record['source'],'INJECTED');self.assertTrue(w.ready)
   self.assertEqual(store.get(w.last_injected_record['capture_id'])['samples'],RECORDS[1]['samples'])
class ControllerTests(unittest.TestCase):
 def test_success_requires_exact_returned_samples_and_analysis(self):
  d=Device();c=InjectionController(d,Store());c.execute(1,prepare(BODY,101))
  self.assertEqual(len(d.sent),10);self.assertEqual(c.result['record_id'],91);self.assertTrue(c.result['samples_verified']);self.assertEqual(c.phase,'complete')
 def test_result_not_reused_across_disconnect_reset_or_new_connection(self):
  d=Device();c=InjectionController(d,Store());c.execute(1,prepare(BODY,101));self.assertIsNotNone(c.status()['result'])
  d.generation=2;self.assertIsNone(c.status()['result']);d.generation=1;d.s['connected']=False;self.assertIsNone(c.status()['result'])
  d.s['connected']=True;d.s['injection_state']['request_id']=0;self.assertIsNone(c.status()['result']);self.assertEqual(c.status()['phase'],'idle')
 def test_reject_bad_ack_disconnect_or_reset_without_retry(self):
  for mode in ['bad_ack','disconnect','reset']:
   d=Device(mode);c=InjectionController(d,Store())
   with self.assertRaises(ValueError):c.execute(1,prepare(BODY,101))
   self.assertEqual(len(d.sent),1);self.assertIsNone(c.result)
 def test_no_success_for_wrong_or_absent_board_record(self):
  for mode in ['bad_samples','bad_config','missing_result']:
   c=InjectionController(Device(mode),Store())
   with self.assertRaises(ValueError):c.execute(1,prepare(BODY,101))
   self.assertIsNone(c.result)
 def test_older_firmware_busy_state_and_reservation(self):
  d=Device();c=InjectionController(d,Store());d.s['injection_state']=None
  with self.assertRaises(ValueError):c.submit(BODY)
  self.assertEqual(d.sent,[]);d.s['injection_state']=dict(sequence=1)
  accepted=c.submit(BODY);self.assertTrue(accepted['accepted']);self.assertTrue(d.injection_job_active)
  with self.assertRaises(ValueError):c.submit(BODY)
  self.assertEqual(d.sent,[])
 def test_background_failure_releases_job(self):
  d=Device('bad_ack');c=InjectionController(d,Store());c.submit(BODY);c.start()
  import time
  until=time.monotonic()+2
  while d.injection_job_active and time.monotonic()<until:time.sleep(.01)
  c.close();self.assertFalse(d.injection_job_active);self.assertEqual(c.phase,'error');self.assertIsNone(c.result)
if __name__=='__main__':unittest.main()
