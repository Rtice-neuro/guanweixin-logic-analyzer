import argparse,json,re,subprocess,tempfile,threading
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from http.server import ThreadingHTTPServer
from instrument_protocol import Framer,parse_record,command_packet
from instrument_web import Store,make_handler,page


def main():
 p=argparse.ArgumentParser();p.add_argument('uart',type=Path);p.add_argument('--node',required=True);a=p.parse_args()
 raw=a.uart.read_bytes().decode('ascii');framer=Framer();events=[]
 for char in raw:events.extend(framer.feed(char))
 fixtures=[value for kind,value in events if kind=='record']
 assert len(fixtures)>=25
 for frame in fixtures:parse_record(frame)
 normal=fixtures[0]
 clock60=re.sub(r'CLOCK_HZ=[0-9A-F]{8}', 'CLOCK_HZ=03938700',normal) if 'CLOCK_HZ=' in normal else normal.replace('SOURCE=','CLOCK_HZ=03938700\r\nSOURCE=',1)
 assert parse_record(clock60)['clock_hz']==60000000
 assert parse_record(normal)['clock_hz']==27000000
 # Imported/history records cannot change the clock used for the next command.
 with tempfile.TemporaryDirectory()as folder:
  clocks=Store(Path(folder));assert clocks.latest_serial_clock()is None
  clocks.add(clock60,'SERIAL');assert clocks.latest_serial_clock()==60000000
  clocks.add(normal,'IMPORTED');assert clocks.latest_serial_clock()==60000000
 try:parse_record(clock60.replace('03938700','FFFFFFFF',1));raise AssertionError('accepted unverified clock')
 except ValueError:pass
 noisy=Framer();repaired=[]
 for char in '\x00'+normal+'GWX READY v0.2\r\n':repaired.extend(noisy.feed(char))
 assert [kind for kind,_ in repaired]==['record','ready']and noisy.dropped==1
 assert parse_record(repaired[0][1])['samples']==parse_record(normal)['samples']
 # A NUL inside a data field must still fail strict validation.
 try:parse_record(normal.replace('DATA=','DATA=\x00',1));raise AssertionError('accepted corrupted field')
 except ValueError:pass
 recovery=Framer();recovered=recovery.feed('GWX COREMARK BEGIN\r\npartial output\r\n'+normal+'GWX READY v0.2\r\n')
 assert [kind for kind,_ in recovered]==['record','ready'] and recovery.dropped==1
 recovery=Framer();assert recovery.feed('GWX COREMARK BEGIN\r\npartial\r\nGWX READY v0.2\r\n')==[('ready','GWX READY v0.2')]
 for invalid in (normal.replace('SUM=','SUM=F',1),normal.replace('FAULT_COUNT=00000000','FAULT_COUNT=00000001'),normal.replace('ID=00000001','ID=00000001\r\nID=00000001')):
  try:parse_record(invalid);raise AssertionError('accepted invalid record')
  except ValueError:pass
 for values in ({'divider':0},{'missing':5},{'channel':8},{'monitor':0},{'cmd':5},{'divider':True},{'unknown':1}):
  try:command_packet(values);raise AssertionError('accepted invalid config')
  except ValueError:pass
 packet=command_packet({});assert len(packet)==16 and packet[:4]==bytes([165,90,1,2])
 xor=0
 for b in packet:xor^=b
 assert xor==0
 with tempfile.TemporaryDirectory()as temp:
  store=Store(temp);token='integration-test';server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(store,None,token));thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  base=f'http://127.0.0.1:{server.server_port}'
  def post(path,body,expected,headers=None):
   req=Request(base+path,data=json.dumps(body).encode('utf-8'),headers=headers or {'X-GWX-Control':token,'Content-Type':'application/json'})
   try:
    with urlopen(req,timeout=5)as response:assert response.status==expected;return json.load(response)
   except HTTPError as e:assert e.code==expected,(path,e.code,expected)
  try:
   post('/api/import',{'raw':normal},403,{'X-GWX-Control':'wrong'})
   post('/api/import',{'raw':normal},403,{'X-GWX-Control':token,'Origin':'https://not-local.example'})
   selected=[fixtures[i]for i in (0,4,14,24)]
   post('/api/import',{'raw':''.join(selected)},201)
   post('/api/import',{'raw':normal[:-8]},400)
   post('/api/command',{},409)
   post('/api/command',{'cmd':4,'mode':0},409)
   post('/api/command',[],400)
   post('/api/sync',{},409)
   post('/api/reconnect',{},409)
   with urlopen(base+'/api/status')as r:assert json.load(r)['count']==4
   with urlopen(base+'/?id=3')as r:body=r.read().decode('utf-8');assert '周期异常'in body and body.count('<polyline')==8
   with urlopen(base+'/record/3.txt')as r:assert r.read().decode('utf-8')==selected[2]
   with urlopen(base+'/export.csv')as r:csv=r.read().decode('utf-8');assert 'MISSING_PULSE'in csv and 'PERIOD'in csv and 'STUCK'in csv
   with urlopen(base+'/api/records')as r:
    rows=json.load(r);assert len(rows)==4 and rows[0]['origin']=='IMPORTED'and 'raw'not in rows[0]
   with urlopen(base+'/api/record?id=3')as r:assert json.load(r)['samples']==parse_record(selected[2])['samples']
   with urlopen(base+'/api/release')as r:assert json.load(r)['external_input_enabled']is False
   for asset,kind in [('workbench.js','javascript'),('waveform-model.js','javascript'),('workbench.css','text/css')]:
    with urlopen(base+'/assets/'+asset)as r:assert kind in r.headers['Content-Type'];assert len(r.read())>100
   for path in ['/assets/../instrument_web.py','/assets/not-there.js','/api/record?id=9999']:
    try:urlopen(base+path);raise AssertionError('unbounded asset or missing record accepted')
    except HTTPError as e:assert e.code==404
   store.event('=FORMULA');store.event('设备已连接')
   with urlopen(base+'/api/events')as r:assert len(json.load(r))==2
   with urlopen(base+'/events.csv')as r:assert "'=FORMULA"in r.read().decode('utf-8')
   script=re.search(r'<script>(.*?)</script>',page(store,None,token),re.S).group(1)
   assert 'const benchmarkEnabled=false' in script
   assert 'const benchmarkEnabled=true' in page(store,None,token,enable_benchmarks=True)
   subprocess.run([a.node,'--check','-'],input=script,text=True,encoding='utf-8',check=True)
  finally:server.shutdown();server.server_close();thread.join(timeout=5)
 print('PASS workbench: strict records/config/framing, API, waveform SSR, static allowlist, trace, exports and local-control checks')
if __name__=='__main__':main()
