"""Local board-AI receiver. Model execution remains entirely on the FPGA."""
import argparse, base64, csv, hashlib, io, json, secrets, shutil, subprocess, threading, time, uuid
from contextlib import closing
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from http.server import ThreadingHTTPServer
from presentation import evidence as presentation_evidence, example as presentation_example, baseline as presentation_baseline
from instrument_protocol import Framer, parse_record, parse_benchmark, configuration, command_packet
from ai_protocol import parse_ai_frame
from device_manager import DeviceManager
from injection_protocol import parse_ack
from injection_controller import InjectionController
from instrument_web import Store, SerialWorker, make_handler, now

LABELS = ['正常', '丢脉冲', '周期异常', '卡高', '卡低', '未知']


def rule_comparison(capture,frame):
    """Compare only the fault classes actually provided by deterministic rules."""
    channel=frame['CHANNEL'];fault=next((f for f in capture.get('faults',[]) if f['channel']==channel),None)
    label={'MISSING_PULSE':1,'PERIOD':2}.get(fault['code'],5) if fault else 0
    stuck=bool(fault and fault['code']=='STUCK')
    agreement=frame['LABEL'] in (3,4) if stuck else label==frame['LABEL']
    return dict(rule_label='电平卡死' if stuck else LABELS[label],rule_label_id=None if stuck else label,
                ai_rule_agreement=agreement if frame.get('STATUS')=='PASS' else None,
                diagnosis_policy='rule_primary_ai_auxiliary')


class AIFramer:
    def __init__(self):
        self.base = Framer(); self.pending = ''; self.ai = []; self.injection=[]; self.dropped = 0
    def feed(self, chunk):
        self.pending += chunk; out = []
        while '\n' in self.pending:
            line, self.pending = self.pending.split('\n', 1); line = line.rstrip('\r')
            if line=='GWX INJECT BEGIN':
                self.injection=[line];continue
            if self.injection and line in ('GWX DET8 v0.2','GWX READY v0.2','GWX AI BEGIN','GWX COREMARK BEGIN'):
                self.injection=[];self.dropped+=1
            if self.injection:
                self.injection.append(line)
                if sum(map(len,self.injection))>4096:self.injection=[];self.dropped+=1
                elif line=='GWX INJECT END':out.append(('injection','\r\n'.join(self.injection)+'\r\n'));self.injection=[]
                continue
            if line == 'GWX AI BEGIN':
                if self.ai: self.dropped += 1
                self.ai = [line]
            elif self.ai and line not in ('GWX DET8 v0.2', 'GWX READY v0.2', 'GWX COREMARK BEGIN'):
                self.ai.append(line)
                if sum(map(len, self.ai)) > 8192:
                    self.ai = []; self.dropped += 1
                elif line == 'GWX AI END':
                    out.append(('ai', '\r\n'.join(self.ai)+'\r\n')); self.ai = []
            else:
                if self.ai: self.ai = []; self.dropped += 1
                out.extend(self.base.feed(line+'\n'))
        if len(self.pending) > 16384:
            self.pending = ''; self.ai = []; self.dropped += 1
        return out


class AIStore(Store):
    def __init__(self, root):
        super().__init__(root)
        with closing(self.connect()) as c:
            c.execute('CREATE TABLE IF NOT EXISTS diagnoses(id INTEGER PRIMARY KEY,received_at TEXT NOT NULL,capture_id INTEGER NOT NULL,origin TEXT NOT NULL,payload TEXT NOT NULL,raw TEXT NOT NULL,digest TEXT UNIQUE NOT NULL)'); c.commit()
    def add_ai(self, raw, capture_id, origin='SERIAL', session=''):
        frame = parse_ai_frame(raw); capture = self.get(capture_id)
        if not capture or capture['board_id'] != frame['RECORD'] or capture['status'] != 'PASS':
            raise ValueError('AI结果没有匹配的完整采集记录')
        if capture['clock_hz'] != frame['CLOCK_HZ']: raise ValueError('采集与AI时钟不同')
        if capture['config']['channel']!=frame['CHANNEL'] or (capture['config']['pmin']+capture['config']['pmax'])//2!=frame['EXPECTED_PERIOD']:
            raise ValueError('采集与AI通道或标称周期不同')
        payload = dict(frame=frame, label=LABELS[frame['LABEL']] if frame.get('STATUS')=='PASS' else frame['STATUS'],
                       source=capture['source'], channel=frame['CHANNEL'], mode=capture['config']['mode'],
                       host_model_executed=False, session=session, calibrated_probability=False,
                       **rule_comparison(capture,frame))
        digest = hashlib.sha256((session+'\0'+str(capture_id)+'\0'+raw).encode()).hexdigest()
        with closing(self.connect()) as c:
            cur=c.execute('INSERT INTO diagnoses(received_at,capture_id,origin,payload,raw,digest) VALUES(?,?,?,?,?,?)',
                          (now(),capture_id,origin,json.dumps(payload,ensure_ascii=False),raw,digest)); c.commit()
            return cur.lastrowid
    def diagnoses(self, offset=0, limit=50, query=''):
        if not 0<=offset<=10000000 or not 1<=limit<=100 or len(query)>80: raise ValueError('查询范围无效')
        channel_query=len(query)==2 and query[0].upper()=='D' and query[1]in '01234567'
        where="json_extract(payload,'$.channel')=?" if channel_query else 'instr(payload,?)>0'
        value=int(query[1]) if channel_query else query
        with closing(self.connect()) as c:
            total=c.execute('SELECT count(*) FROM diagnoses WHERE '+where,(value,)).fetchone()[0]
            rows=c.execute('SELECT id,received_at,capture_id,origin,payload FROM diagnoses WHERE '+where+' ORDER BY received_at DESC,id DESC LIMIT ? OFFSET ?', (value,limit,offset)).fetchall()
        return dict(total=total,offset=offset,limit=limit,items=[dict(id=r[0],received_at=r[1],capture_id=r[2],origin=r[3],**json.loads(r[4])) for r in rows])
    def diagnosis(self, rid):
        with closing(self.connect()) as c:
            r=c.execute('SELECT id,received_at,capture_id,origin,payload,raw FROM diagnoses WHERE id=?',(rid,)).fetchone()
        return dict(id=r[0],received_at=r[1],capture_id=r[2],origin=r[3],**json.loads(r[4]),raw=r[5]) if r else None


class AIWorker(SerialWorker):
    def __init__(self, port, store, external_enabled=False, driver=None):
        self.injection_state=None; self.last_injected_record=None; self.observer=None; self.active_ai=None; self.ai_complete=False; self.ai_started=0; self.capture_map={}; self.last_board_id=None
        self.session=uuid.uuid4().hex; self.external_enabled=False; self.ai_result_id=None
        super().__init__(port,store,driver)
    def status(self):
        with self.lock:
            return dict(port=self.port,connected=self.connected,ready=self.ready,pending=self.pending,error=self.error,
                        ai_running=self.active_ai is not None and not self.ai_complete,
                        ai_elapsed_seconds=round(time.monotonic()-self.ai_started,1) if self.active_ai else None,
                        ai_result_id=self.ai_result_id,external_enabled=self.external_enabled,
                        injection_state=self.injection_state,last_injected_record=self.last_injected_record,phase='AI推理中' if self.active_ai and not self.ai_complete else '等待采集' if self.pending else '就绪' if self.ready else '等待同步')
    def send(self,cfg):
        cfg=configuration(cfg)
        if cfg['cmd']==1: raise ValueError('当前版本仅支持板内八路自检，已移除外部输入')
        return super().send(cfg)
    def send_injection(self,packet):
        if not isinstance(packet,bytes)or len(packet)!=16 or packet[:4]!=bytes([0xa5,0x5a,1,12]):raise ValueError('注入数据包无效')
        check=0
        for value in packet:check^=value
        if check:raise ValueError('注入数据包校验无效')
        with self.lock:
            if not self.injection_state:raise ValueError('当前固件未回传r18注入能力，不发送新命令')
            if not self.connected or not self.ready or self.pending:raise ValueError('设备尚未就绪')
            self.ready=False;self.pending=True;self.deadline=time.monotonic()+30
            try:self.process.stdin.write(packet.hex().upper()+'\n');self.process.stdin.flush()
            except (OSError,ValueError):self.pending=False;self.connected=False;raise ValueError('串口发送失败')
    def sync(self):
        if self.active_ai and not self.ai_complete:raise ValueError('板端推理尚未结束；不可插入同步命令')
        return super().sync()
    def send_ai(self,body):
        if not isinstance(body,dict) or set(body)-{'config','software'}: raise ValueError('AI参数无效')
        software=body.get('software',False)
        if type(software)is not bool: raise ValueError('software须为布尔值')
        cfg=configuration(body.get('config',{}))
        if cfg['cmd'] not in (1,2): raise ValueError('AI只支持一次内部或外部采集')
        if cfg['cmd']==1: raise ValueError('当前版本仅支持板内八路自检，已移除外部输入')
        if not 4<=(cfg['pmin']+cfg['pmax'])//2<=16: raise ValueError('模型标称周期须为4至16个样点')
        p=bytearray(command_packet(cfg)); p[3]=(6 if cfg['cmd']==1 else 5)+(2 if software else 0); p[15]=0
        for value in p[:15]:p[15]^=value
        with self.lock:
            if not self.connected or not self.ready or self.pending: raise ValueError('设备未就绪或已有命令正在运行')
            self.ready=False; self.pending=True; self.deadline=time.monotonic()+600
            self.active_ai=dict(cfg,accelerated=not software); self.ai_complete=False; self.ai_started=time.monotonic(); self.capture_map={}
            try:self.process.stdin.write(p.hex().upper()+'\n'); self.process.stdin.flush()
            except (OSError,ValueError):
                self.pending=False; self.connected=False; self.active_ai=None; raise ValueError('串口发送失败')
        self.store.event('已发送板端AI命令 '+json.dumps(dict(config=cfg,software=software),ensure_ascii=False))
    def handle_frame(self,kind,raw):
        self.store.runlog.append('FRAME',kind.upper()+' frame parsed',self.port) if hasattr(self.store,'runlog') else None
        if kind=='ready':
            with self.lock:
                if self.active_ai and not self.ai_complete:
                    self.error='AI结果未完整返回；保留原始数据，禁止当作成功'; return
                self.ready=True; self.pending=False; self.error=''; self.active_ai=None
            if self.observer:self.observer(kind,raw)
            return
        name='uart_'+now().replace(':','-')+'_'+uuid.uuid4().hex+'.log'
        (self.store.root/name).write_bytes(raw.encode('ascii',errors='backslashreplace'))
        if kind=='record':
            record=parse_record(raw)
            if self.last_board_id is not None and record['board_id']<self.last_board_id:
                with self.lock:self.active_ai=None; self.ai_complete=False; self.capture_map={}; self.ready=False;self.last_injected_record=None;self.injection_state=None
                self.session=uuid.uuid4().hex; self.store.event('检测到板卡复位，旧命令作废；等待启动自检与READY')
            self.last_board_id=record['board_id']
            rid=self.store.add(raw,'SERIAL'); self.capture_map[record['board_id']]=rid
            if record.get('source')=='INJECTED':self.last_injected_record=dict(request_id=record.get('injection_id'),capture_id=rid,status=record['status'],samples=record['samples'],analysis=record.get('analysis'),config=record.get('config'),clock_hz=record.get('clock_hz'),source=record.get('source'))
            if len(self.capture_map)>128:self.capture_map.pop(next(iter(self.capture_map)))
            if record['status']!='PASS' and self.active_ai:
                with self.lock:self.active_ai=None; self.error='AI前置采集失败：'+record['status']
        elif kind=='benchmark':self.store.add_benchmark(raw,'SERIAL')
        elif kind=='injection':
            self.injection_state=parse_ack(raw)
        elif kind=='ai':
            frame=parse_ai_frame(raw); expected=self.active_ai
            if expected is None: raise ValueError('忽略无待处理命令的AI结果')
            if self.ai_complete: raise ValueError('忽略重复AI结果；等待READY')
            rid=self.capture_map.get(frame['RECORD']); parent=self.store.get(rid) if rid else None
            if not parent or frame['CHANNEL']!=expected['channel'] or frame['ACCEL']!=int(expected['accelerated']):
                raise ValueError('AI命令与返回结果不匹配')
            cfg=parent['config']
            if any(cfg[k]!=expected[k] for k in ('mode','channel','divider','mask','value','trigger','monitor','pmin','pmax','missing')):
                raise ValueError('AI关联采集参数不匹配')
            if parent['source']!=('EXTERNAL' if expected['cmd']==1 else 'INTERNAL'): raise ValueError('AI信号来源不匹配')
            self.ai_result_id=self.store.add_ai(raw,rid,session=self.session)
            with self.lock:self.ai_complete=True
            self.store.event('板端AI结果已保存 #'+str(self.ai_result_id)+'；状态 '+frame['STATUS'])
        if self.observer:self.observer(kind,raw)
    def run(self):
        self.injection_state=None; self.last_injected_record=None; self.active_ai=None; self.capture_map={}; self.last_board_id=None; self.session=uuid.uuid4().hex
        framer=AIFramer(); self.monitor=threading.Thread(target=self.watch,daemon=True); self.monitor.start()
        try:
            ps=shutil.which('pwsh') or shutil.which('powershell')
            self.process=subprocess.Popen([ps,'-NoProfile','-File',str(self.driver),'-Port',self.port],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',bufsize=1,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            for line in self.process.stdout:
                try:event=json.loads(line)
                except ValueError:self.store.event('串口进程 '+line[:300]);continue
                if event.get('event')=='connected':
                    with self.lock:self.connected=True;self.error=''
                    self.store.event('已连接 '+self.port+'；等待同步或板卡READY')
                elif event.get('event')=='error':raise RuntimeError(event.get('message','串口异常'))
                elif event.get('event')=='sent':
                    self.store.runlog.append('TX',event.get('packet',''),self.port)
                elif event.get('event')=='rx':
                    data=base64.b64decode(event['data'],validate=True)
                    self.store.runlog.append('RX',data.decode('ascii',errors='backslashreplace'),self.port)
                    with (self.store.root/'rx_stream.bin').open('ab')as f:f.write(data)
                    for kind,raw in framer.feed(data.decode('ascii',errors='replace')):
                        try:self.handle_frame(kind,raw)
                        except ValueError as exc:
                            self.store.event('拒绝无效记录：'+str(exc))
                            with self.lock:self.error=str(exc)
            if not self.stopping:raise RuntimeError('串口接收已断开；未自动重发命令')
        except Exception as exc:
            with self.lock:self.error=str(exc)
            self.store.event('串口异常：'+str(exc))
        finally:
            self.stop_event.set()
            with self.lock:self.connected=False;self.ready=False;self.pending=False
            if self.process and self.process.poll()is None:self.process.terminate()


def handler(store,worker,token,benchmarks=False,devices=None,injector=None):
    base=make_handler(store,worker,token,benchmarks)
    class Handler(base):
        def do_GET(self):
            u=urlsplit(self.path); q=parse_qs(u.query)
            try:
                if u.path=='/api/run-log':return self.reply(200,store.runlog.snapshot(int(q.get('after',['0'])[0]),int(q.get('limit',['300'])[0])))
                if u.path=='/api/run-log/export':return self.reply(200,store.runlog.path.read_bytes(),'text/plain; charset=utf-8')
                if u.path=='/api/injection/status':return self.reply(200,injector.status()if injector is not None else dict(supported=False,busy=False))
                if u.path=='/api/device/ports':return self.reply(200,devices.ports()if devices is not None else dict(ports=[],error='当前测试会话未启用连接管理'))
                if u.path=='/api/device/identity':return self.reply(200,devices.identity()if devices is not None else dict(protocol_verified=False))
                if u.path=='/api/application/mcu-hex':return self.reply(404,{'error':'当前版本已移除51及外部信号功能'})
                if u.path=='/api/application/evidence':return self.reply(200,presentation_evidence(store))
                if u.path=='/api/application/baseline':return self.reply(200,presentation_baseline(store,int(q.get('id',['0'])[0])))
                if u.path=='/api/application/example':
                    result=presentation_example(store,int(q.get('mode',['0'])[0]),int(q.get('channel',['0'])[0]));return self.reply(200 if result else 404,result or {'error':'本地数据库未找到对应归档样例'})
                if u.path=='/api/status':return self.reply(200,{**store.latest(),**(worker.status()if worker is not None else dict(connected=False,ready=False,pending=False,port='未指定',error='',external_enabled=False)), 'ai_count':store.diagnoses(limit=1)['total'],'last_serial_clock_hz':store.latest_serial_clock()})
                if u.path=='/api/ai/results':return self.reply(200,store.diagnoses(int(q.get('offset',['0'])[0]),int(q.get('limit',['50'])[0]),q.get('q',[''])[0]))
                if u.path=='/api/ai/result':
                    result=store.diagnosis(int(q.get('id',['0'])[0]));return self.reply(200 if result else 404,result or {'error':'结果不存在'})
                if u.path=='/api/release':return self.reply(200,dict(version='0.9-uart-injection-r18',application_scope='internal_selftest_and_uart_injected_board_analysis',firmware_revision='runtime_protocol_not_bitstream_attested',uart_injection_candidate=True,virtual_sample_grid=True,physical_gpio_output=False,supported_runtime_versions=[1,2],target='PGL50H',channels=8,depth=64,external_input_enabled=bool(worker and worker.external_enabled),ai_execution='FPGA_RV32I',host_model=False,programming='无烧录接口',ai_timeout_seconds=600,clock_independently_calibrated=False))
                if u.path=='/ai.csv':
                    out=io.StringIO();w=csv.writer(out);w.writerow(['电脑接收时间','结果ID','采集ID','来源','通道','诊断','状态','周期折算秒','模型分数_非概率','路径'])
                    with closing(store.connect())as c:
                        for r in c.execute('SELECT id,received_at,capture_id,origin,payload FROM diagnoses ORDER BY id'):
                            p=json.loads(r[4]);f=p['frame'];w.writerow([r[1],r[0],r[2],r[3],p['channel'],p['label'],f['STATUS'],f.get('nominal_inference_seconds',''),f.get('SCORE_PERMILLE',''),'ACCEL'if f['ACCEL']else'CPU'])
                    return self.reply(200,'\ufeff'+out.getvalue(),'text/csv; charset=utf-8')
                if u.path=='/assets/ai-workbench.js':return self.reply(200,Path(__file__).with_name('assets').joinpath('ai-workbench.js').read_bytes(),'text/javascript; charset=utf-8')
            except (ValueError,TypeError):return self.reply(400,{'error':'请求无效'})
            return super().do_GET()
        def do_POST(self):
            if self.path not in ('/api/ai/command','/api/device/connect','/api/device/disconnect','/api/device/probe','/api/injection/analyze'):return super().do_POST()
            origin=self.headers.get('Origin'); expected=f'http://127.0.0.1:{self.server.server_port}'
            if self.headers.get('X-GWX-Control')!=token or(origin and origin!=expected)or self.headers.get('Sec-Fetch-Site')=='cross-site':return self.reply(403,{'error':'只接受本机控制页面'})
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=4096:return self.reply(413,{'error':'参数长度超限'})
                body=json.loads(self.rfile.read(length))
                if not isinstance(body,dict):raise ValueError('请求正文须为对象')
                if self.path=='/api/injection/analyze':
                    if injector is None:return self.reply(409,{'error':'当前会话未启用注入管理'})
                    return self.reply(202,injector.submit(body))
                if self.path.startswith('/api/device/'):
                    if devices is None:return self.reply(409,{'error':'当前会话未启用连接管理'})
                    if self.path=='/api/device/connect':
                        if set(body)-{'port','probe'}:raise ValueError('连接参数无效')
                        result=devices.connect(body.get('port'),body.get('probe',True))
                    elif self.path=='/api/device/disconnect':
                        if body:raise ValueError('断开参数无效')
                        devices.disconnect();result=devices.status()
                    else:
                        if body:raise ValueError('读取参数无效')
                        devices.probe();result=devices.status()
                    return self.reply(202,result)
                if not worker:return self.reply(409,{'error':'当前为记录浏览模式，未连接板卡'})
                worker.send_ai(body);return self.reply(202,{'accepted':True,'execution':'FPGA_RV32I'})
            except (ValueError,TypeError)as exc:return self.reply(400,{'error':str(exc)})
    return Handler


def main():
    p=argparse.ArgumentParser();p.add_argument('--data',type=Path,required=True);p.add_argument('--serial');p.add_argument('--port',type=int,default=8765)
    p.add_argument('--enable-benchmarks',action='store_true');a=p.parse_args()
    if a.serial and not __import__('re').fullmatch('COM[0-9]+',a.serial):raise ValueError('串口名无效')
    store=AIStore(a.data);devices=DeviceManager(store,AIWorker);injector=InjectionController(devices,store);worker=devices;token=secrets.token_hex(24)
    server=ThreadingHTTPServer(('127.0.0.1',a.port),handler(store,worker,token,a.enable_benchmarks,devices,injector))
    if a.serial:devices.connect(a.serial,probe=False,allow_configured=True)
    injector.start()
    print(f'观微芯板端AI工作台 http://127.0.0.1:{a.port}/ 数据：{a.data}',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:
        server.server_close()
        injector.close();devices.close()


if __name__=='__main__':main()
