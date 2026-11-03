"""Boundary and persistence tests with real UART fixtures; no board accessed."""
import io,json,sys,tempfile,threading,unittest
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from http.server import ThreadingHTTPServer
from ai_workbench import AIFramer,AIStore,AIWorker,handler

FIXTURE=Path(__file__).resolve().parent/'fixtures/board_ai_legacy'
RESULT=json.loads((FIXTURE/'board_ai_result.json').read_text(encoding='utf-8'))
RAW=(FIXTURE/'uart_raw.bin').read_bytes().decode('ascii')
AI=next(raw for kind,raw in AIFramer().feed(RAW)if kind=='ai')
CAP=RESULT['capture']['raw']


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=AIStore(self.temp.name)
        self.worker=AIWorker('COM8',self.store);self.worker.process=type('Fake',(),{'stdin':io.StringIO()})()
        self.worker.connected=True;self.worker.ready=True
    def tearDown(self):self.temp.cleanup()
    def test_fragmentation_and_reset(self):
        f=AIFramer();events=[]
        for byte in RAW:events.extend(f.feed(byte))
        self.assertEqual(sum(k=='ai'for k,v in events),1)
        f=AIFramer();ev=f.feed('GWX AI BEGIN\r\nEXEC=FPGA_RV32I\r\n'+CAP+'GWX READY v0.2\r\n')
        self.assertTrue(any(k=='record'for k,v in ev));self.assertFalse(any(k=='ai'for k,v in ev));self.assertEqual(f.dropped,1)
    def test_ai_pairing_and_readiness(self):
        w=self.worker;w.send_ai({'config':{'mode':3,'channel':7}})
        packet=bytes.fromhex(w.process.stdin.getvalue());self.assertEqual(packet[3],5)
        checksum=0
        for b in packet:checksum^=b
        self.assertEqual(checksum,0)
        w.handle_frame('record',CAP)
        self.assertTrue(w.pending);self.assertFalse(w.ready)
        w.handle_frame('ready','GWX READY v0.2');self.assertFalse(w.ready)
        with self.assertRaises(ValueError):w.send_ai({'config':{}})
        w.handle_frame('ai',AI);self.assertFalse(w.ready)
        with self.assertRaises(ValueError):w.handle_frame('ai',AI)
        self.assertEqual(self.store.diagnoses()['total'],1)
        w.handle_frame('ready','GWX READY v0.2');self.assertTrue(w.ready);self.assertFalse(w.pending)
        rows=self.store.diagnoses()['items'];self.assertEqual(len(rows),1);self.assertEqual(rows[0]['label'],'卡低')
        self.assertEqual(self.store.diagnoses(query='D7')['total'],1);self.assertEqual(self.store.diagnoses(query='D0')['total'],0)
    def test_reject_mismatched_and_unsolicited(self):
        w=self.worker
        with self.assertRaises(ValueError):w.handle_frame('ai',AI)
        w.send_ai({'config':{'mode':3,'channel':7}});w.handle_frame('record',CAP)
        with self.assertRaises(ValueError):w.handle_frame('ai',AI.replace('CHANNEL=00000007','CHANNEL=00000000'))
        self.assertEqual(self.store.diagnoses()['total'],0)
        self.assertFalse(w.ready)
    def test_external_and_parameter_guards(self):
        for body in ({'config':{'cmd':1}}, {'config':{'cmd':3}}, {'software':'yes'}, {'config':{'pmin':20,'pmax':22,'missing':25}}, {'host_model':True}):
            with self.subTest(body=body),self.assertRaises(ValueError):self.worker.send_ai(body)
        with self.assertRaises(ValueError):self.worker.send({'cmd':1})
        self.assertEqual(self.worker.process.stdin.getvalue(),'')
    def test_external_commands_rejected_even_if_flag_is_mutated(self):
        w=self.worker
        w.external_enabled=True
        with self.assertRaises(ValueError):w.send({'cmd':1})
        with self.assertRaises(ValueError):w.send_ai({'config':{'cmd':1}})
    def test_reset_invalidates_pending(self):
        w=self.worker;w.last_board_id=200;w.send_ai({'config':{'mode':3,'channel':7}});w.handle_frame('record',CAP)
        self.assertIsNone(w.active_ai);w.handle_frame('ready','GWX READY v0.2');self.assertTrue(w.ready)
        with self.assertRaises(ValueError):w.handle_frame('ai',AI)
    def test_persist_and_csv_http(self):
        rid=self.store.add(CAP,'IMPORTED');aid=self.store.add_ai(AI,rid,'ARCHIVED_SERIAL','fixture')
        store2=AIStore(self.temp.name);self.assertEqual(store2.diagnosis(aid)['capture_id'],rid)
        server=ThreadingHTTPServer(('127.0.0.1',0),handler(store2,None,'known-token'))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            root=f'http://127.0.0.1:{server.server_port}'
            self.assertEqual(json.load(urlopen(root+'/api/ai/results'))['total'],1)
            self.assertIn('卡低',urlopen(root+'/ai.csv').read().decode('utf-8'))
            request=Request(root+'/api/ai/command',data=b'{}',headers={'Content-Type':'application/json'},method='POST')
            with self.assertRaises(HTTPError)as ctx:urlopen(request)
            self.assertEqual(ctx.exception.code,403)
            request.add_header('X-GWX-Control','known-token')
            with self.assertRaises(HTTPError)as ctx:urlopen(request)
            self.assertEqual(ctx.exception.code,409)
        finally:server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
