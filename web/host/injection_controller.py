"""Serializes injection packets, checks board ACKs and exact returned samples."""
import threading,time,secrets
from injection_protocol import prepare
class InjectionController:
 def __init__(self,devices,store):
  self.devices=devices;self.store=store;self.lock=threading.Lock();self.job=None;self.result=None;self.message='连接r18固件后可送板分析';self.progress=0;self.phase='idle';self.stopping=threading.Event();self.thread=threading.Thread(target=self.run,daemon=True)
 def start(self):self.thread.start()
 def status(self):
  s=self.devices.raw_status();ack=s.get('injection_state')if self.devices.verified and s.get('connected')else None
  with self.lock:
   connected=bool(self.devices.verified and s.get('connected'));current=self.result if connected and self.result and self.result.get('generation')==self.devices.generation and ack and ack.get('request_id')==self.result['request_id']else None
   phase='idle'if self.phase=='complete'and current is None else self.phase
   return dict(supported=ack is not None,connected=connected,ready=bool(s.get('ready')and not s.get('pending')),busy=self.devices.injection_job_active,phase=phase,uploaded=self.progress if current or self.devices.injection_job_active else 0,message=self.message if phase!='idle'else'连接r18固件并生成64点数字波形后，可送板分析',result=current,physical_input_used=False)
 def submit(self,body):
  status=self.status()
  if not status['supported']:raise ValueError('当前固件未回传r18注入能力，不发送数据；需更新独立r18版本')
  if not status['ready']:raise ValueError('板端尚未就绪')
  request_id=secrets.randbits(32)or 1;data=prepare(body,request_id)
  with self.devices.lock,self.lock:
   fresh=self.devices.raw_status()
   if not fresh.get('connected')or not fresh.get('ready')or fresh.get('pending')or fresh.get('ai_running'):raise ValueError('板端状态已改变，未建立注入任务')
   if self.devices.injection_job_active:raise ValueError('已有注入任务')
   self.devices.injection_job_active=True;self.job=(self.devices.generation,data);self.result=None;self.progress=0;self.phase='queued';self.message='已排队，等待上传至板卡'
  return dict(accepted=True,request_id=request_id,effective_sample_rate=data['effective_sample_rate'],sample_count=64)
 def exchange(self,packet,generation,request_id,count):
  if generation!=self.devices.generation:raise ValueError('连接会话已改变')
  before=self.devices.raw_status().get('injection_state')or{};seq=before.get('sequence',0)
  self.devices.send_injection(packet);deadline=time.monotonic()+8
  while not self.stopping.wait(.01):
   if generation!=self.devices.generation:raise ValueError('连接会话已改变')
   s=self.devices.raw_status();ack=s.get('injection_state')or{}
   if not s.get('connected'):raise ValueError('串口断开，停止上传')
   if s.get('ready')and not s.get('pending')and ack.get('sequence')!=seq:
    if ack.get('request_id')!=request_id or ack.get('count')!=count or ack.get('active')!=(packet[4]!=2):raise ValueError('板端注入确认不匹配，停止上传')
    return s
   if time.monotonic()>deadline:raise ValueError('等待注入确认超时，不自动重复发送')
  raise ValueError('服务器关闭，停止上传')
 def execute(self,generation,data):
  for n,packet in enumerate(data['packets']):
   self.phase='uploading'if n<9 else'analyzing';self.message='正在上传八路数据'if n<9 else'等待板上RISC-V CPU分析并回传'
   count=0 if n==0 else n*8 if n<=8 else 64
   s=self.exchange(packet,generation,data['request_id'],count);self.progress=count
  returned=s.get('last_injected_record')or{}
  if returned.get('request_id')!=data['request_id']or returned.get('status')!='PASS'or returned.get('samples')!=data['samples']or not returned.get('analysis')or returned.get('source')!='INJECTED'or returned.get('clock_hz')!=27000000 or any(returned.get('config',{}).get(k)!=data['config'][k]for k in ('divider','monitor','pmin','pmax','missing')):raise ValueError('未收到匹配且逐字节一致的板端分析记录')
  self.result=dict(generation=generation,request_id=data['request_id'],record_id=returned['capture_id'],samples_verified=True,checksum=data['checksum'],effective_sample_rate=data['effective_sample_rate'],label=data['label'],execution='FPGA_RV32I',transport='UART_INJECTION')
  self.phase='complete';self.message='板端分析完成，64字节回读一致；可查看返回波形与异常位置';self.store.event('串口注入闭环完成 '+str(self.result))
 def run(self):
  while not self.stopping.wait(.05):
   with self.lock:item=self.job;self.job=None
   if item is None:continue
   try:self.execute(*item)
   except Exception as e:self.phase='error';self.message='注入失败：'+str(e);self.store.event(self.message)
   finally:
    with self.devices.lock:self.devices.injection_job_active=False
 def close(self):self.stopping.set();self.thread.join(timeout=2)if self.thread.is_alive()else None
