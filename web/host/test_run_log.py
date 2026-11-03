import unittest,tempfile,json,base64,hashlib
from pathlib import Path
from unittest.mock import patch
from run_log import RunLog
from ai_workbench import AIStore,AIWorker

class LiveTranscriptTests(unittest.TestCase):
    def test_cursor_hash_and_gap(self):
        with tempfile.TemporaryDirectory() as d:
            log=RunLog(Path(d)/'wire.jsonl',capacity=3)
            for i in range(5):log.append('RX','data='+str(i))
            snap=log.snapshot(1)
            self.assertTrue(snap['gap']);self.assertEqual([r['seq']for r in snap['items']],[4,5,6])
            for row in snap['items']:
                self.assertEqual(row['sha256'],hashlib.sha256(row['text'].encode()).hexdigest())
            self.assertEqual(len((Path(d)/'wire.jsonl').read_text().splitlines()),6)
    def test_driver_confirmation_and_raw_bytes_are_logged_without_creating_capture(self):
        with tempfile.TemporaryDirectory()as d:
            store=AIStore(Path(d));worker=AIWorker('COM99',store);worker.stopping=True
            raw=b'GWX READY v0.2\r\n'
            events=[dict(event='connected'),dict(event='sent',packet='A55A0102'),dict(event='rx',data=base64.b64encode(raw).decode())]
            class Process:
                stdout=[json.dumps(e)+'\n' for e in events]
                def poll(self):return 0
            with patch('ai_workbench.subprocess.Popen',return_value=Process()):
                worker.run()
            rows=store.runlog.snapshot()['items']
            self.assertEqual([x['text']for x in rows if x['kind']=='TX'],['A55A0102'])
            self.assertEqual(''.join(x['text']for x in rows if x['kind']=='RX'),raw.decode())
            self.assertTrue(any(x['kind']=='FRAME'and'READY'in x['text']for x in rows))
            self.assertEqual(store.latest()['count'],0)
if __name__=='__main__':unittest.main()
