import unittest
from http.server import ThreadingHTTPServer
from threading import Thread
from urllib.request import urlopen
import json
from presentation import evidence, example, baseline
from ai_workbench import handler

class FakeStore:
    def __init__(self):
        self.rows=[]
        self.bench=[]
        self.ai=0
    def add(self, record): self.rows.insert(0,record)
    def records(self): return list(self.rows[:200])
    def get(self,rid): return next((r for r in self.rows if r['id']==rid),None)
    def latest(self): return dict(count=len(self.rows))
    def benchmarks(self): return self.bench
    def diagnoses(self,limit=1): return dict(total=self.ai,items=[])
    def connect(self): raise AssertionError('evidence must not read archived files or SQL internals')

def record(rid,source,samples,faults=None,mode=0,channel=0):
    return dict(id=rid,received_at=f'2026-11-01T22:{rid:02d}:00+08:00',board_id=rid,origin='SERIAL',source=source,status='PASS',faults=faults or [],samples=samples,clock_hz=27000000,config=dict(divider=270,mask=0,value=0,trigger=0,monitor=255,pmin=6,pmax=10,missing=14,mode=mode,channel=channel))

def pattern(): return [sum(int((i+c)%8<2)<<c for c in range(8)) for i in range(64)]

class PresentationTests(unittest.TestCase):
    def setUp(self):
        self.store=FakeStore(); base=pattern();self.store.add(record(20,'INJECTED',base))
        # A valid single-channel missing-pulse sample based on the same 8-bit capture.
        missing=base.copy();missing[18:20]=[v&~(1<<2) for v in missing[18:20]]
        self.store.add(record(21,'INJECTED',missing,[dict(channel=2,code='MISSING_PULSE',index=18,gap=16)]))
        period=base.copy();period[27:29]=[v&~(1<<3) for v in period[27:29]]
        self.store.add(record(22,'INJECTED',period,[dict(channel=3,code='PERIOD',index=27,gap=12)]))
        low=base.copy();low=[v&~(1<<4) for v in low]
        self.store.add(record(23,'INJECTED',low,[dict(channel=4,code='STUCK',index=0,gap=0)]))
        high=base.copy();high=[v|(1<<5) for v in high]
        self.store.add(record(24,'INJECTED',high,[dict(channel=5,code='STUCK',index=0,gap=0)]))
    def test_evidence_is_current_database_and_marks_only_real_coverage(self):
        result=evidence(self.store)
        self.assertEqual(result['capture_count'],5)
        self.assertEqual(result['coverage_total'],32)
        self.assertEqual(result['cases_attempted'],4)
        self.assertEqual(result['cases_passed'],4)
        self.assertEqual(result['normal_record_id'],20)
        self.assertEqual(result['ila']['capture_count'],0)
        self.assertEqual(len(result['records']),5)
        self.assertEqual(len(result['records'][0]['sample_sha256']),64)
        self.assertEqual(next(c for c in result['cases'] if c['mode']==4 and c['channel']==5)['record_id'],24)
    def test_examples_follow_live_records(self):
        self.assertEqual(example(self.store,0,0)['id'],20)
        self.assertEqual(example(self.store,1,2)['id'],21)
        self.assertEqual(example(self.store,4,5)['id'],24)
        self.assertIsNone(example(self.store,1,7))
        self.assertIsNotNone(baseline(self.store,21)['record'])
    def test_evidence_api_has_no_archived_json_dependency(self):
        srv=ThreadingHTTPServer(('127.0.0.1',0),handler(self.store,None,'test-token'))
        thread=Thread(target=srv.serve_forever,daemon=True);thread.start()
        try:
            payload=json.load(urlopen(f'http://127.0.0.1:{srv.server_port}/api/application/evidence'))
            self.assertEqual(payload['cases_passed'],4)
            self.assertEqual(payload['latest_capture_id'],24)
            self.assertEqual(len(payload['cases']),32)
        finally:
            srv.shutdown();srv.server_close();thread.join()

if __name__=='__main__': unittest.main()
