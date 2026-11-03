"""Serialized generator jobs and watchdog keepalive; never enables unsupported firmware."""
import threading,time
from generator_protocol import channel_settings,control_packet,query_packet
class GeneratorController:
 def __init__(self,devices,store):
  self.devices=devices;self.store=store;self.lock=threading.Lock();self.job=None;self.message='等待支持发生器的r17固件';self.stopping=threading.Event();self.thread=threading.Thread(target=self.run,daemon=True);self.heartbeat=0;self.number=0
 def start(self):self.thread.start()
 def status(self):
  s=self.devices.raw_status();verified=self.devices.verified;state=s.get('generator_state')if verified and s.get('connected')else None
  with self.lock:return dict(supported=state is not None,connected=bool(s.get('connected')and verified),ready=bool(s.get('ready')and not s.get('pending')),busy=self.devices.generator_job_active,job=self.number,message=self.message,reported=state,physical_output_requires_pin_confirmation=True)
 def submit(self,body):
  if not isinstance(body,dict):raise ValueError('发生器请求须为对象')
  action=body.get('action')
  if action not in('configure','run_internal','run_external','stop'):raise ValueError('发生器操作无效')
  allowed={'action','channels'}if action=='configure'else{'action','pin_map_confirmed'}if action=='run_external'else{'action'}
  if set(body)-allowed:raise ValueError('发生器字段无效')
  status=self.status()
  if not status['supported']:raise ValueError('尚未收到r17发生器能力帧，禁止发送输出命令')
  if not status['ready']:raise ValueError('板端尚未就绪')
  payload=None
  if action=='configure':
   channels=body.get('channels')
   if not isinstance(channels,list)or len(channels)!=8:raise ValueError('需要完整八路配置')
   payload=[]
   for ch,c in enumerate(channels):
    if not isinstance(c,dict)or set(c)!={'frequency','duty','phase','enabled'}:raise ValueError('通道配置字段无效')
    payload.append(channel_settings(ch,**c))
  if action=='run_external'and body.get('pin_map_confirmed')is not True:raise ValueError('请先核对PMOD引脚和外接电路，明确确认输出')
  if action.startswith('run_')and not status['reported']['enable_mask']:raise ValueError('尚未启用任何发生器通道')
  with self.lock:
   if self.devices.generator_job_active:raise ValueError('发生器配置正在执行')
   self.devices.generator_job_active=True;self.number+=1;self.job=(self.number,self.devices.generation,action,payload);self.message='已排队：'+action
   return dict(accepted=True,job=self.number)
 def exchange(self,packet,generation):
  if generation!=self.devices.generation:raise ValueError('连接会话已改变')
  before=self.devices.raw_status().get('generator_state')or{};baseline=before.get('sequence',0)
  self.devices.send_generator(packet);deadline=time.monotonic()+5
  while not self.stopping.wait(.015):
   if generation!=self.devices.generation:raise ValueError('连接会话已改变')
   s=self.devices.raw_status()
   if not s.get('connected'):raise ValueError('串口断开；硬件看门狗将撤销外部输出')
   g=s.get('generator_state')or{}
   if s.get('ready')and not s.get('pending')and g.get('sequence',0)!=baseline:self.heartbeat=time.monotonic();return g
   if time.monotonic()>deadline:raise ValueError('发生器确认超时；硬件看门狗将撤销外部输出')
  raise ValueError('服务器关闭')
 def execute(self,item):
  number,generation,action,payload=item
  if action=='configure':
   state=self.exchange(control_packet(0),generation)
   for cfg in payload:
    state=self.exchange(cfg['packet'],generation);actual=state['channels'][cfg['channel']]
    if any(actual[k]!=cfg[k]for k in('period','high','phase_ticks','enabled')):raise ValueError('发生器配置读回不一致，未启动输出')
  else:
   mode={'stop':0,'run_internal':3,'run_external':5}[action];state=self.exchange(control_packet(mode),generation)
   if state['control']!=mode:raise ValueError('发生器控制读回不一致')
  self.message=f'任务#{number}完成：{action}；板端已读回确认';self.store.event('发生器 '+self.message)
 def run(self):
  while not self.stopping.wait(.1):
   with self.lock:item=self.job;self.job=None
   if item is not None:
    try:self.execute(item)
    except Exception as exc:
     self.message='发生器操作失败：'+str(exc);self.store.event(self.message)
     # Stop on an acknowledged, still available session; never queue behind a busy CPU.
     try:
      s=self.devices.raw_status()
      if s.get('connected')and s.get('ready')and not s.get('pending'):self.exchange(control_packet(0),self.devices.generation)
     except Exception:pass
    finally:self.devices.generator_job_active=False
   else:
    s=self.devices.raw_status();g=s.get('generator_state')or{}
    if self.devices.verified and s.get('connected')and s.get('ready')and not s.get('pending')and g.get('external_armed')and g.get('running')and time.monotonic()-self.heartbeat>=.65:
     try:self.exchange(query_packet(),self.devices.generation)
     except Exception as exc:self.message='输出保活中断：'+str(exc);self.store.event(self.message)
 def close(self):self.stopping.set();self.thread.join(timeout=2)if self.thread.is_alive()else None
