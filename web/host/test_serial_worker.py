"""Simulated process/serial failures ONLY; does not open hardware or prove USB tests."""
import argparse,base64,json,queue,tempfile,time
from pathlib import Path
from unittest.mock import patch
from instrument_protocol import Framer
from instrument_web import SerialWorker,Store

def until(condition):
 deadline=time.monotonic()+4
 while time.monotonic()<deadline:
  if condition():return
  time.sleep(.01)
 raise AssertionError('condition did not become true')

class Pipe:
 def __init__(self,owner):self.owner=owner
 def write(self,text):
  if self.owner.code is not None:raise OSError('simulated disconnected process')
  self.owner.commands.append(bytes.fromhex(text.strip()))
  if self.owner.respond:
   data=(self.owner.frame+'GWX READY v0.2\r\n').encode('ascii')
   self.owner.lines.put(json.dumps(dict(event='rx',data=base64.b64encode(data).decode())))
 def flush(self):pass
 def close(self):self.owner.terminate()

class Process:
 def __init__(self,frame):
  self.frame=frame;self.code=None;self.respond=True;self.commands=[];self.lines=queue.Queue();self.stdin=Pipe(self);self.stdout=self
  self.lines.put(json.dumps(dict(event='connected')))
 def __iter__(self):return self
 def __next__(self):
  line=self.lines.get(timeout=5)
  if line is None:raise StopIteration
  return line
 def poll(self):return self.code
 def wait(self,timeout=None):return self.code
 def terminate(self):
  if self.code is None:self.code=0;self.lines.put(None)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('uart',type=Path);args=p.parse_args()
 frame=next(raw for kind,raw in Framer().feed(args.uart.read_bytes().decode('ascii'))if kind=='record')
 processes=[]
 def popen(*args,**kwargs):
  proc=Process(frame);processes.append(proc);return proc
 with tempfile.TemporaryDirectory()as temp,patch('instrument_web.subprocess.Popen',side_effect=popen),patch('instrument_web.shutil.which',return_value='fake-powershell'):
  store=Store(temp);worker=SerialWorker('COM8',store);worker.thread.start()
  try:
   until(lambda:worker.status()['connected']);assert not worker.status()['ready']
   try:worker.send({});raise AssertionError('sent while not ready')
   except ValueError:pass
   worker.sync();until(lambda:worker.status()['ready']);assert store.latest()['count']==1
   assert processes[0].commands[0][3]==2
   processes[0].respond=False;worker.send({'cmd':2})
   with worker.lock:worker.deadline=time.monotonic()-1
   until(lambda:not worker.status()['pending']);assert not worker.status()['ready']and '超时'in worker.status()['error']
   processes[0].respond=True;worker.sync();until(lambda:worker.status()['ready']);assert not worker.status()['error']
   worker.reconnect();until(lambda:len(processes)==2 and worker.status()['connected']and not worker.reconnecting)
   assert processes[0].code==0 and not worker.status()['ready']
   worker.sync();until(lambda:worker.status()['ready']);assert store.latest()['count']==3
   processes[1].terminate();until(lambda:not worker.status()['connected']);assert not worker.status()['ready']
  finally:worker.close()
 print('PASS SIMULATED serial process: readiness gate, safe sync, timeout, recovery, reconnect and disconnect; no hardware opened')
