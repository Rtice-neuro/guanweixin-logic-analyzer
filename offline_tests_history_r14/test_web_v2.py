from pathlib import Path
import sys,json,tempfile,io
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'host'))
from ai_workbench import AIFramer,AIStore,AIWorker
from ai_protocol import parse_ai_frame
raw=(R/'verification/candidate_mode13/uart_mode_13.bin').read_bytes().decode('ascii');f=AIFramer();events=[]
for c in raw:events.extend(f.feed(c))
ai=next(v for k,v in events if k=='ai');cap=[v for k,v in events if k=='record'][-1];frame=parse_ai_frame(ai)
assert frame['RUNTIME_VERSION']==2 and frame['DOT_GROUPS']==50944 and frame['LABEL']==4
for corrupt in [ai.replace('DOT_GROUPS=0000C700','DOT_GROUPS=0000DD00'),ai.replace('RUNTIME_VERSION=00000002','RUNTIME_VERSION=00000003')]:
 try:parse_ai_frame(corrupt)
 except ValueError:pass
 else:raise AssertionError('Invalid computation was accepted')
with tempfile.TemporaryDirectory(dir=R/'tmp')as tmp:
 store=AIStore(tmp);worker=AIWorker('NOT_OPENED',store);worker.process=type('Mock',(),{'stdin':io.StringIO()})();worker.connected=True;worker.ready=True
 worker.send_ai({'config':{'mode':3,'channel':0}});worker.handle_frame('record',cap);worker.handle_frame('ai',ai);worker.handle_frame('ready','GWX READY v0.2')
 assert worker.ready and store.diagnoses()['total']==1
 row=store.diagnoses()['items'][0];assert row['frame']['RUNTIME_VERSION']==2
print('PASS old/new strict protocol; fragmentation, pairing, persistence, wrong counts/version rejected; no serial opened')
