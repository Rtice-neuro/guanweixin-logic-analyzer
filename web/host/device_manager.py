"""Local UART discovery and verified application-session identity. No drivers or JTAG."""
import json,re,shutil,subprocess,threading,time
from instrument_protocol import parse_record
from ai_protocol import parse_ai_frame

def enumerate_ports():
    ps=shutil.which('pwsh') or shutil.which('powershell')
    if not ps:return []
    script="[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); @(Get-CimInstance Win32_SerialPort -ErrorAction Stop | Select-Object DeviceID,Name,PNPDeviceID) | ConvertTo-Json -Compress"
    result=subprocess.run([ps,'-NoProfile','-Command',script],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=12,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode:raise ValueError('读取串口清单失败；未修改驱动或系统设置')
    data=json.loads(result.stdout.strip()or'[]');data=[data]if isinstance(data,dict)else data
    out=[]
    for d in data:
        port=str(d.get('DeviceID','')).upper();name=str(d.get('Name',''));pnp=str(d.get('PNPDeviceID',''))
        if not re.fullmatch(r'COM[0-9]+',port):continue
        candidate='VID_10C4&PID_EA60'in pnp.upper() or bool(re.search(r'CP210[0-9X]',name,re.I))
        role='board_uart'if candidate else 'jtag_or_usb_bridge'if'VID_0403'in pnp.upper()else'other'
        out.append(dict(port=port,name=name,pnp_id=pnp,role=role,board_candidate=candidate))
    return sorted(out,key=lambda p:int(p['port'][3:]))

class DeviceManager:
    def __init__(self,store,factory,scanner=enumerate_ports):
        self.store=store;self.factory=factory;self.scanner=scanner;self.worker=None;self.lock=threading.RLock();self.cache=[];self.scan_at=0;self.scan_error='';self.metadata={};self.verified=False;self.last_frame=None;self.last_ai=None;self.last_rx=None;self.injection_job_active=False;self.generation=0;self.connection_at=None;self.scan_lock=threading.Lock()
    def __bool__(self):return self.worker is not None
    @property
    def external_enabled(self):return False
    @property
    def port(self):return self.worker.port if self.worker else '未指定'
    def ports(self,force=False):
        with self.lock:
            due=force or time.monotonic()-self.scan_at>3
        if due and self.scan_lock.acquire(blocking=False):
            try:
                try:cache=self.scanner();error=''
                except Exception as exc:cache=[];error=str(exc)
                with self.lock:self.cache=cache;self.scan_error=error;self.scan_at=time.monotonic()
            finally:self.scan_lock.release()
        with self.lock:return dict(ports=list(self.cache),error=self.scan_error,scanned_at=time.time())
    def identity(self):
        with self.lock:
            s=self.worker.status()if self.worker else {}
            return dict(target='PGL50H',target_source='project_configuration',channels=8,depth=64,baud=115200,port=self.port,uart=self.metadata,transport_connected=bool(s.get('connected')),protocol_verified=self.verified,protocol='GWX DET8/READY v0.2'if self.verified else None,ready=bool(self.verified and s.get('ready')and not self.injection_job_active),connected_at=self.connection_at,last_received_at=self.last_rx,last_frame=self.last_frame,last_ai=self.last_ai,firmware_revision='r18注入能力已读回，程序哈希以部署记录为准'if s.get('injection_state')else'版本未由板端确认（串口未提供位流哈希）',physical_output_supported=False,injection_supported=bool(self.verified and s.get('injection_state')),injection=s.get('injection_state')if self.verified else None,external_capture_enabled=False)
    def status(self):
        with self.lock:
            s=self.worker.status()if self.worker else dict(port='未指定',connected=False,ready=False,pending=False,error='',external_enabled=False)
            if not s.get('connected')and self.verified:self.verified=False;self.last_frame=self.last_ai=self.last_rx=None
            return {**s,'transport_connected':bool(s.get('connected')),'connected':bool(s.get('connected')and self.verified),'pending':bool(s.get('pending')or self.injection_job_active),'ready':bool(s.get('ready')and self.verified and not self.injection_job_active),'injection_job_active':self.injection_job_active,'protocol_verified':self.verified,'device_identity':self.identity()}
    def observe(self,generation,kind,raw):
        with self.lock:
            if generation!=self.generation:return
            if kind=='record':
                r=parse_record(raw)
                self.last_frame=dict(board_id=r['board_id'],status=r['status'],source=r['source'],clock_hz=r.get('clock_hz'),sample_count=len(r['samples']))
                if r['status']=='PASS':self.verified=True
            elif kind=='ready':
                if raw!='GWX READY v0.2':return
                self.verified=True
            elif kind=='ai':
                frame=parse_ai_frame(raw);self.last_ai=dict(model_crc=hex(frame['MODEL_CRC']),channel=frame['CHANNEL'],status=frame['STATUS'])
            self.last_rx=time.time()
    def connect(self,port,probe=True,allow_configured=False):
        if not isinstance(port,str)or not re.fullmatch(r'COM[0-9]+',port):raise ValueError('串口名称无效')
        if type(probe)is not bool:raise ValueError('读取标志须为布尔值')
        ports=self.ports(force=True)['ports'];meta=next((p for p in ports if p['port']==port),None)
        if not allow_configured and(not meta or not meta['board_candidate']):raise ValueError('请选择已识别的CP210x板载UART；不连接蓝牙或JTAG下载器端口')
        with self.lock:
            if self.worker:
                s=self.worker.status()
                if s.get('pending')or s.get('ai_running')or self.injection_job_active:raise ValueError('板端任务未结束，不能切换连接')
                if self.worker.port==port and s.get('connected'):
                    if probe:self.probe()
                    return self.status()
                self.worker.close()
            self.generation+=1;g=self.generation;self.verified=False;self.last_frame=self.last_ai=self.last_rx=None;self.metadata=meta or dict(port=port,role='configured_uart');self.connection_at=time.time()
            self.worker=self.factory(port,self.store);self.worker.observer=lambda kind,raw:self.observe(g,kind,raw);self.worker.thread.start()
            self.store.event('连接管理：打开板载UART '+port+'；等待观微芯协议验证')
        if probe:
            def read_identity():
                connected_since=None
                for _ in range(150):
                    with self.lock:
                        if g!=self.generation or not self.worker:return
                        s=self.worker.status();frame=self.last_frame
                    if s.get('connected'):
                        if connected_since is None:connected_since=time.monotonic()
                        if frame is not None:
                            if s.get('ready'):return
                            time.sleep(.1);continue
                        if time.monotonic()-connected_since<.4:
                            time.sleep(.1);continue
                        if not s.get('pending'):
                            try:self.probe()
                            except ValueError as exc:self.store.event('读取设备信息未执行：'+str(exc))
                        return
                    time.sleep(.1)
            threading.Thread(target=read_identity,daemon=True).start()
        return self.status()
    def probe(self):
        with self.lock:
            if not self.worker:raise ValueError('尚未连接板载UART')
            s=self.worker.status()
            if not s.get('connected'):raise ValueError('串口尚未打开')
            if s.get('pending')or s.get('ai_running')or self.injection_job_active:raise ValueError('当前任务未结束，不插入状态读取')
            # Existing cmd2 performs one internal capture; it never drives external pins.
            self.worker.sync();self.store.event('连接管理：使用板内采集读取当前设备帧与时钟；不访问外部引脚')
    def disconnect(self):
        with self.lock:
            if self.worker:
                s=self.worker.status()
                if s.get('pending')or s.get('ai_running')or self.injection_job_active:raise ValueError('当前任务未结束，暂不关闭串口')
                self.generation+=1;self.worker.close();self.worker=None
            self.verified=False;self.last_frame=self.last_ai=self.last_rx=None;self.metadata={};self.connection_at=None
            self.store.event('连接管理：已断开UART，历史记录保留')
    def send(self,cfg):
        with self.lock:
            if not self.verified or not self.worker:raise ValueError('尚未收到有效观微芯协议，不能发送采集命令')
            if self.injection_job_active:raise ValueError('串口注入分析尚未完成')
            return self.worker.send(cfg)
    def send_ai(self,body):
        with self.lock:
            if not self.verified or not self.worker:raise ValueError('尚未验证板端协议')
            if self.injection_job_active:raise ValueError('串口注入分析尚未完成')
            return self.worker.send_ai(body)
    def raw_status(self):
        with self.lock:return self.worker.status()if self.worker else dict(connected=False,ready=False,pending=False)
    def send_injection(self,packet):
        with self.lock:
            if not self.verified or not self.worker:raise ValueError('当前连接未验证')
            return self.worker.send_injection(packet)
    def sync(self):return self.probe()
    def reconnect(self):
        if not self.worker:raise ValueError('尚未选择板载UART')
        port=self.worker.port;self.disconnect();return self.connect(port,probe=True,allow_configured=True)
    def close(self):
        with self.lock:
            self.generation+=1
            if self.worker:self.worker.close();self.worker=None
