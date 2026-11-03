"""Local instrument UI + Windows serial worker; Python stdlib, no cloud service."""
import argparse,base64,csv,html,io,json,secrets,shutil,sqlite3,subprocess,threading,time,uuid
from contextlib import closing
from datetime import datetime
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs,urlsplit
from instrument_protocol import Framer,parse_record,parse_benchmark,configuration,command_packet
from workbench import ASSETS,render_page
from run_log import RunLog


def now():return datetime.now().astimezone().isoformat(timespec='milliseconds')


class Store:
 def __init__(self,root):
  self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True);self.db=self.root/'instrument.sqlite3';self.runlog=RunLog(self.root/'run_transcript.jsonl')
  with closing(self.connect()) as c:
   c.execute('PRAGMA journal_mode=WAL')
   c.execute('CREATE TABLE IF NOT EXISTS captures(id INTEGER PRIMARY KEY,received_at TEXT NOT NULL,payload TEXT NOT NULL,raw TEXT NOT NULL)')
   c.execute('CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,received_at TEXT NOT NULL,message TEXT NOT NULL)')
   c.execute('CREATE TABLE IF NOT EXISTS benchmarks(id INTEGER PRIMARY KEY,received_at TEXT NOT NULL,payload TEXT NOT NULL,raw TEXT NOT NULL)');c.commit()
 def connect(self):return sqlite3.connect(self.db,timeout=10)
 def latest_serial_clock(self):
  # Historical/imported records cannot change the next acquisition's clock.
  with closing(self.connect())as c:
   row=c.execute("SELECT payload FROM captures WHERE json_extract(payload,'$.origin')='SERIAL' ORDER BY id DESC LIMIT 1").fetchone()
  if not row:return None
  p=json.loads(row[0]);clock=p.get('clock_hz',27000000)
  return clock if clock in (27000000,60000000) else None
 def event(self,message):
  self.runlog.append("HOST",message)
  with closing(self.connect()) as c:c.execute('INSERT INTO events(received_at,message) VALUES(?,?)',(now(),message));c.commit()
 def add(self,raw,origin):
  record=parse_record(raw);record['origin']=origin
  with closing(self.connect()) as c:
   row=c.execute('INSERT INTO captures(received_at,payload,raw) VALUES(?,?,?)',(now(),json.dumps(record,ensure_ascii=False),raw));c.commit();rid=row.lastrowid
  return rid
 def add_benchmark(self,raw,origin):
  record=parse_benchmark(raw);record['origin']=origin
  with closing(self.connect())as c:
   cur=c.execute('INSERT INTO benchmarks(received_at,payload,raw) VALUES(?,?,?)',(now(),json.dumps(record),raw));c.commit();return cur.lastrowid
 def benchmarks(self):
  with closing(self.connect())as c:rows=c.execute('SELECT id,received_at,payload FROM benchmarks ORDER BY id DESC LIMIT 10').fetchall()
  return [dict(id=r[0],received_at=r[1],**json.loads(r[2]))for r in rows]
 def benchmark(self,rid):
  with closing(self.connect())as c:r=c.execute('SELECT raw FROM benchmarks WHERE id=?',(rid,)).fetchone()
  return r[0]if r else None
 def records(self):
  with closing(self.connect()) as c:rows=c.execute('SELECT id,received_at,payload FROM captures ORDER BY id DESC LIMIT 200').fetchall()
  return [dict(id=r[0],received_at=r[1],**json.loads(r[2]))for r in rows]
 def get(self,rid):
  with closing(self.connect()) as c:row=c.execute('SELECT id,received_at,payload FROM captures WHERE id=?',(rid,)).fetchone()
  return dict(id=row[0],received_at=row[1],**json.loads(row[2]))if row else None
 def search(self,query='',origin='',result='',offset=0,limit=50):
  if origin not in ('','SERIAL','IMPORTED','RTL_SIMULATION','ARCHIVED_SERIAL')or result not in ('','FAULT','NORMAL','ERROR'):raise ValueError('无效筛选')
  if not 0<=offset<=10000000 or not 1<=limit<=100:raise ValueError('分页超限')
  where=[];values=[]
  if query:
   if len(query)>80:raise ValueError('搜索过长')
   query={'丢脉冲':'MISSING_PULSE','周期异常':'PERIOD','电平卡死':'STUCK','串口':'SERIAL','导入':'IMPORTED','超时':'TIMEOUT'}.get(query,query)
   if len(query)==2 and query[0].upper()=='D'and query[1]in '01234567':
    where.append("EXISTS(SELECT 1 FROM json_each(payload,'$.faults') f WHERE json_extract(f.value,'$.channel')=?)");values.append(int(query[1]))
   else:
    # Literal substring search; % and _ are not wildcard operators here.
    where.append("(instr(lower(payload),lower(?))>0 OR instr(received_at,?)>0 OR CAST(id AS TEXT)=?)");values.extend([query,query,query.lstrip('#')])
  if origin:where.append("json_extract(payload,'$.origin')=?");values.append(origin)
  if result=='FAULT':where.append("json_array_length(payload,'$.faults')>0")
  if result=='NORMAL':where.append("json_extract(payload,'$.status')='PASS' AND json_array_length(payload,'$.faults')=0")
  if result=='ERROR':where.append("json_extract(payload,'$.status')!='PASS'")
  clause=' WHERE '+' AND '.join(where)if where else ''
  with closing(self.connect())as c:
   total=c.execute('SELECT count(*) FROM captures'+clause,values).fetchone()[0]
   rows=c.execute('SELECT id,received_at,payload FROM captures'+clause+' ORDER BY id DESC LIMIT ? OFFSET ?',[*values,limit,offset]).fetchall()
  keys={'origin','source','status','faults','config','clock_hz'}
  items=[dict(id=r[0],received_at=r[1],**{k:v for k,v in json.loads(r[2]).items()if k in keys})for r in rows]
  return dict(items=items,total=total,offset=offset,limit=limit)
 def events(self,limit=100):
  with closing(self.connect()) as c:return c.execute('SELECT received_at,message FROM events ORDER BY id DESC LIMIT ?',(limit,)).fetchall()
 def latest(self):
  with closing(self.connect()) as c:
   rid,count=c.execute('SELECT COALESCE(MAX(id),0),COUNT(*) FROM captures').fetchone()
   bid,bcount=c.execute('SELECT COALESCE(MAX(id),0),COUNT(*) FROM benchmarks').fetchone()
  return dict(latest=rid,count=count,benchmark_latest=bid,benchmark_count=bcount)


class SerialWorker:
 def __init__(self,port,store,driver=None):
  self.port=port;self.store=store;self.process=None;self.lock=threading.Lock();self.connected=False;self.ready=False;self.pending=False;self.error='';self.stopping=False
  self.driver=driver or Path(__file__).with_name('serial_driver.ps1');self.thread=threading.Thread(target=self.run,daemon=True);self.deadline=0;self.stop_event=threading.Event();self.monitor=threading.Thread(target=self.watch,daemon=True);self.reconnecting=False
 def status(self):
  with self.lock:return dict(port=self.port,connected=self.connected,ready=self.ready,pending=self.pending,error=self.error)
 def send(self,cfg):
  cfg=configuration(cfg)
  packet=command_packet(cfg)
  with self.lock:
   if not self.connected or not self.ready or self.pending:raise ValueError('串口未就绪；启动接收后请按 KEY2，等自检完成')
   self.ready=False;self.pending=True;self.deadline=time.monotonic()+(120 if cfg['cmd']==4 else 30)
   try:self.process.stdin.write(packet.hex().upper()+'\n');self.process.stdin.flush()
   except (OSError,ValueError)as exc:self.pending=False;self.connected=False;self.error=str(exc);raise ValueError('串口控制进程中断')from exc
  self.store.event('已发送配置 '+json.dumps(cfg,ensure_ascii=False))
 def sync(self):
  with self.lock:
   if not self.connected or self.pending:raise ValueError('设备未连接或仍在处理命令')
   self.ready=False;self.pending=True;self.deadline=time.monotonic()+30
   try:self.process.stdin.write(command_packet(configuration({'cmd':2})).hex().upper()+'\n');self.process.stdin.flush()
   except (OSError,ValueError)as exc:self.pending=False;raise ValueError('串口控制进程中断')from exc
  self.store.event('用户请求板内安全同步采集，不驱动外部输入排针')
 def reconnect(self):
  with self.lock:
   if self.pending or self.reconnecting:raise ValueError('当前命令尚未结束或正在重连')
   self.reconnecting=True
  def restart():
   try:
    self.close();self.stopping=False;self.stop_event=threading.Event();self.process=None;self.deadline=0;self.error=''
    self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()
   finally:
    with self.lock:self.reconnecting=False
  threading.Thread(target=restart,daemon=True).start()
 def watch(self):
  while not self.stop_event.wait(.25):
   expired=False
   with self.lock:
    if self.pending and time.monotonic()>self.deadline:
     self.pending=False;self.ready=False;self.error='等待设备响应超时；请检查连接，再点击同步设备';expired=True
   if expired:self.store.event('命令响应超时；不自动重发，不将设备标记为就绪')
 def run(self):
  framer=Framer()
  self.monitor=threading.Thread(target=self.watch,daemon=True);self.monitor.start()
  try:
   pwsh=shutil.which('pwsh') or shutil.which('powershell')
   if not pwsh:raise RuntimeError('没有找到 PowerShell')
   self.process=subprocess.Popen([pwsh,'-NoProfile','-File',str(self.driver),'-Port',self.port],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',bufsize=1,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
   for line in self.process.stdout:
    try:event=json.loads(line)
    except ValueError:self.store.event('串口进程: '+line[:500].strip());continue
    if event.get('event')=='connected':
     with self.lock:self.connected=True;self.error=''
     self.store.event('已打开串口 '+self.port+'，等待板卡 READY')
    elif event.get('event')=='error':raise RuntimeError(event.get('message','串口错误'))
    elif event.get('event')=='rx':
     wire_bytes=base64.b64decode(event['data'],validate=True)
     with (self.store.root/'rx_stream.bin').open('ab')as stream:stream.write(wire_bytes)
     chunk=wire_bytes.decode('ascii',errors='replace')
     prior_dropped=framer.dropped;events=framer.feed(chunk)
     if framer.dropped!=prior_dropped:self.store.event('串口重新同步：丢弃启动噪声或中断数据 '+str(framer.dropped-prior_dropped)+' 处；原始字节保留')
     for kind,raw in events:
      if kind=='ready':
       with self.lock:self.ready=True;self.pending=False;self.error=''
      else:
       path=self.store.root/('uart_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'_'+uuid.uuid4().hex+'.txt')
       path.write_bytes(raw.encode('ascii',errors='backslashreplace'))
       try:
        rid=self.store.add(raw,'SERIAL')if kind=='record'else self.store.add_benchmark(raw,'SERIAL')
        path.with_suffix('.json').write_text(json.dumps(dict(record_id=rid,kind=kind,source='SERIAL',port=self.port,received_at=now()),ensure_ascii=False,indent=2),encoding='utf-8')
       except ValueError as exc:self.store.event('拒绝无效串口记录: '+str(exc))
   if not self.stopping:raise RuntimeError('串口进程已退出，请检查连接后点击重连串口')
  except Exception as exc:
   with self.lock:self.error=str(exc)
   self.store.event('串口异常: '+str(exc))
  finally:
   self.stop_event.set()
   with self.lock:self.connected=False;self.ready=False;self.pending=False
   if self.process and self.process.poll()is None:self.process.terminate()
 def close(self):
  self.stopping=True;self.stop_event.set()
  if self.process:
   try:self.process.stdin.close();self.process.wait(timeout=3)
   except (OSError,ValueError,subprocess.TimeoutExpired):self.process.terminate()
  self.thread.join(timeout=5)
  if self.monitor.is_alive():self.monitor.join(timeout=1)


LABELS={'NONE':'正常','MISSING_PULSE':'丢脉冲','PERIOD':'周期异常','STUCK':'电平卡死','TIMEOUT':'触发超时','CONFIG_ERROR':'配置错误','FAIL':'校验失败'}
def esc(value):return html.escape(str(value))


def waveform(record):
 data=record.get('samples',[])
 if not data:return '<p>本条记录没有有效波形。</p>'
 parts=['<svg viewBox="0 0 1100 500" role="img" aria-label="八通道采样波形"><rect width="1100" height="500" fill="var(--surface)"/>']
 faults={f['channel']:f for f in record['faults']}
 for ch in range(8):
  low=45+ch*54;high=low-22;coords=[];old=None
  for i,v in enumerate(data):
   x=92+i*15;y=high if v&(1<<ch)else low
   if old is not None and old!=y:coords.append(f'{x},{old}')
   coords.append(f'{x},{y}');old=y
  coords.append(f'{92+len(data)*15},{old}')
  colour='var(--wave)'
  parts.append(f'<text x="18" y="{low}" fill="var(--ink)">D{ch}</text><polyline points="'+ ' '.join(coords)+f'" fill="none" stroke="{colour}" stroke-width="2"/>')
  if ch in faults:
   f=faults[ch];x=92+f['index']*15
   parts.append(f'<line x1="{x}" x2="{x}" y1="{high-8}" y2="{low+8}" stroke="var(--ink)" stroke-dasharray="4 3" stroke-width="2"><title>{esc(LABELS[f["code"]])}；样点 {f["index"]}</title></line>')
 for i in range(0,65,8):parts.append(f'<text x="{92+i*15}" y="488" fill="var(--muted)">{i}</text>')
 return ''.join(parts)+'</svg>'


def page(store,worker,token,selected=None,query='',enable_benchmarks=False):
 return render_page(store,worker,token,selected,query,enable_benchmarks,waveform)


def make_handler(store,worker,token,enable_benchmarks=False):
 class Handler(BaseHTTPRequestHandler):
  def reply(self,code,data,kind='application/json; charset=utf-8'):
   if isinstance(data,(dict,list)):data=json.dumps(data,ensure_ascii=False)
   if isinstance(data,str):data=data.encode('utf-8')
   self.send_response(code);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(data)
  def do_GET(self):
   url=urlsplit(self.path);q=parse_qs(url.query)
   try:
    if url.path=='/':return self.reply(200,page(store,worker,token,int(q['id'][0])if'id'in q else None,q.get('q',[''])[0][:80],enable_benchmarks),'text/html; charset=utf-8')
    if url.path=='/api/status':return self.reply(200,{**store.latest(),**(worker.status()if worker else dict(connected=False,ready=False,pending=False,error='',port='未指定')), 'last_serial_clock_hz':store.latest_serial_clock(), 'clock_source':'last accepted serial record; not independent hardware measurement'})
    if url.path.startswith('/assets/'):
     name=url.path[8:];allowed={'run-console.js':'text/javascript; charset=utf-8','run-console.css':'text/css; charset=utf-8','injection-ui.js':'text/javascript; charset=utf-8','device-generator.css':'text/css; charset=utf-8','device-generator.js':'text/javascript; charset=utf-8','generator-model.js':'text/javascript; charset=utf-8','scope.js':'text/javascript; charset=utf-8','scope-model.js':'text/javascript; charset=utf-8','scope.css':'text/css; charset=utf-8','favicon.svg':'image/svg+xml','studio.css':'text/css; charset=utf-8','studio.js':'text/javascript; charset=utf-8','instrument-real.js':'text/javascript; charset=utf-8','vendor/three.module.js':'text/javascript; charset=utf-8','vendor/three.core.js':'text/javascript; charset=utf-8','instrument-3d.js':'text/javascript; charset=utf-8','instrument-view.js':'text/javascript; charset=utf-8','application.js':'text/javascript; charset=utf-8','application-model.js':'text/javascript; charset=utf-8','application.css':'text/css; charset=utf-8','workbench.css':'text/css; charset=utf-8','workbench.js':'text/javascript; charset=utf-8','waveform-model.js':'text/javascript; charset=utf-8'}
     if name not in allowed:return self.reply(404,{'error':'资源不存在'})
     return self.reply(200,(ASSETS/name).read_bytes(),allowed[name])
    if url.path=='/api/records':
     keys={'id','received_at','origin','source','status','faults','config'}
     return self.reply(200,[{k:v for k,v in r.items()if k in keys}for r in store.records()])
    if url.path=='/api/records/search':
     return self.reply(200,store.search(q.get('q',[''])[0],q.get('origin',[''])[0],q.get('result',[''])[0],int(q.get('offset',['0'])[0]),int(q.get('limit',['50'])[0])))
    if url.path=='/api/record':
     rec=store.get(int(q.get('id',['0'])[0]));return self.reply(200 if rec else 404,rec or {'error':'记录不存在'})
    if url.path=='/api/events':return self.reply(200,[dict(received_at=t,message=m)for t,m in store.events()])
    if url.path=='/api/benchmarks':return self.reply(200,store.benchmarks())
    if url.path=='/api/release':return self.reply(200,dict(version='0.4-studio',receiver_revision='20261026-r08',target='PGL50H',channels=8,depth=64,nominal_input_clock_hz=27000000,supported_core_clock_hz=[27000000,60000000],clock_independently_calibrated=False,external_input_enabled=False,storage='local SQLite',programming='Web端无烧录接口',benchmark_enabled=enable_benchmarks))
    if url.path=='/events.csv':
     out=io.StringIO();writer=csv.writer(out);writer.writerow(['received_at','message'])
     with closing(store.connect())as c:
      for t,m in c.execute('SELECT received_at,message FROM events ORDER BY id'):
       writer.writerow([t,"'"+m if m.startswith(('=','+','-','@','\t','\r'))else m])
     return self.reply(200,'\ufeff'+out.getvalue(),'text/csv; charset=utf-8')
    if url.path.startswith('/record/')and url.path.endswith('.txt'):
     rec=store.get(int(url.path[8:-4]));return self.reply(200 if rec else 404,rec['raw']if rec else '未找到','text/plain; charset=utf-8')
    if url.path.startswith('/benchmark/')and url.path.endswith('.txt'):
     raw=store.benchmark(int(url.path[11:-4]));return self.reply(200 if raw else 404,raw or '未找到','text/plain; charset=utf-8')
    if url.path=='/export.csv':
     text=io.StringIO();w=csv.writer(text);w.writerow(['id','received_at','origin','source','status','channel','fault','sample_index','gap','analysis_cycles','retired'])
     with closing(store.connect())as c:
      for rid,stamp,payload in c.execute('SELECT id,received_at,payload FROM captures ORDER BY id'):
       r=json.loads(payload)
       for f in r['faults']or[{}]:w.writerow([rid,stamp,r['origin'],r['source'],r['status'],f.get('channel',''),f.get('code','NONE'),f.get('index',''),f.get('gap',''),r.get('analysis',{}).get('cycles',''),r.get('analysis',{}).get('retired','')])
     return self.reply(200,text.getvalue(),'text/csv; charset=utf-8')
    self.reply(404,{'error':'未找到'})
   except ValueError:self.reply(400,{'error':'请求参数无效'})
  def do_POST(self):
   origin=self.headers.get('Origin');expected=f'http://127.0.0.1:{self.server.server_port}'
   if self.headers.get('X-GWX-Control')!=token or(origin and origin!=expected)or self.headers.get('Sec-Fetch-Site')=='cross-site':return self.reply(403,{'error':'只接受本地页面控制'})
   try:
    length=int(self.headers.get('Content-Length','0'))
    if not 0<length<=1048576:return self.reply(413,{'error':'请求长度超限'})
    body=json.loads(self.rfile.read(length).decode('utf-8'))
    if not isinstance(body,dict):raise ValueError('请求正文须为 JSON 对象')
    if self.path in ('/api/sync','/api/reconnect'):
     if not worker:return self.reply(409,{'error':'当前为历史记录模式，未启用串口'})
     worker.sync()if self.path=='/api/sync'else worker.reconnect()
     return self.reply(202,{'accepted':True})
    if self.path=='/api/command':
     cfg=configuration(body)
     if cfg['cmd']==4 and not enable_benchmarks:return self.reply(409,{'error':'演示模式不重复跑分，采集不受影响；专门测试需显式 --enable-benchmarks'})
     if not worker:return self.reply(409,{'error':'未启用串口；请使用 --serial COM8 启动'})
     worker.send(cfg);return self.reply(202,{'accepted':True})
    if self.path=='/api/import':
     raw=body['raw'];framer=Framer();events=framer.feed(raw)
     records=[v for k,v in events if k=='record'];benches=[v for k,v in events if k=='benchmark']
     if not(records or benches) or framer.frame or framer.benchmark or framer.pending or framer.dropped:raise ValueError('文件没有完整记录或有截断')
     for record in records:parse_record(record)
     for bench in benches:parse_benchmark(bench)
     ids=[store.add(record,'IMPORTED')for record in records];bids=[store.add_benchmark(bench,'IMPORTED')for bench in benches]
     return self.reply(201,{'id':ids[-1]if ids else 0,'count':len(ids),'benchmarks':len(bids)})
    self.reply(404,{'error':'未找到'})
   except (ValueError,KeyError,TypeError)as exc:self.reply(400,{'error':str(exc)})
 return Handler


def main():
 p=argparse.ArgumentParser();p.add_argument('--data',type=Path,required=True);p.add_argument('--serial');p.add_argument('--port',type=int,default=8765);p.add_argument('--enable-benchmarks',action='store_true');a=p.parse_args()
 if a.serial and not __import__('re').fullmatch('COM[0-9]+',a.serial):raise ValueError('串口名应为 COM 加数字')
 store=Store(a.data);worker=SerialWorker(a.serial,store)if a.serial else None;token=secrets.token_hex(24)
 server=ThreadingHTTPServer(('127.0.0.1',a.port),make_handler(store,worker,token,a.enable_benchmarks))
 if worker:worker.thread.start()
 print(f'观微芯黑白工作台 v0.4: http://127.0.0.1:{a.port}/ 数据: {a.data}',flush=True)
 try:server.serve_forever()
 except KeyboardInterrupt:pass
 finally:
  server.server_close()
  if worker:worker.close()
if __name__=='__main__':main()


