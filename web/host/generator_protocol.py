"""Strict r17 digital-generator capability frames and bounded 16-byte commands."""
import math,re

def packet(command,payload=b''):
 if command not in(9,10,11)or len(payload)>11:raise ValueError('发生器命令无效')
 data=bytearray([0xa5,0x5a,1,command])+bytearray(payload)+bytearray(11-len(payload));check=0
 for v in data:check^=v
 return bytes(data+bytes([check]))
def control_packet(mode):
 if mode not in(0,3,5):raise ValueError('输出控制模式无效')
 return packet(10,bytes([mode]))
def query_packet():return packet(11)
def channel_settings(ch,frequency,duty,phase,enabled,clock=27000000):
 if type(ch)is not int or not 0<=ch<8 or type(enabled)is not bool:raise ValueError('通道或使能无效')
 for v in [frequency,duty,phase]:
  if type(v)not in(int,float)or not math.isfinite(v):raise ValueError('发生器参数须为有限数值')
 if clock!=27000000 or not 1<=frequency<=100000 or not 1<=duty<=99 or not 0<=phase<360:raise ValueError('硬件频率1–100000Hz，占空比1–99%，相位0–359°')
 period=round(clock/frequency);high=round(period*duty/100);phase_byte=round(phase/360*256)%256;phase_ticks=(period>>8)*phase_byte+(((period&255)*phase_byte)>>8)
 if not 270<=period<=clock or not 0<high<period:raise ValueError('输出周期或脉宽无法表示')
 payload=bytes([ch])+period.to_bytes(4,'little')+high.to_bytes(4,'little')+bytes([phase_byte,int(enabled)])
 return dict(channel=ch,period=period,high=high,phase_ticks=phase_ticks,phase_byte=phase_byte,enabled=enabled,actual_frequency=clock/period,actual_duty=high/period*100,actual_phase=phase_ticks/period*360,packet=packet(9,payload))
def parse_frame(raw):
 lines=raw.replace('\r\n','\n').splitlines()
 if not lines or lines[0]!='GWX GEN BEGIN'or lines[-1]!='GWX GEN END':raise ValueError('发生器帧不完整')
 fields={}
 for line in lines[1:-1]:
  if '='not in line:raise ValueError('发生器字段无效')
  k,v=line.split('=',1)
  if k in fields:raise ValueError('发生器字段重复')
  fields[k]=v
 expected={'VERSION','SEQUENCE','CLOCK_HZ','CONTROL','ENABLE_MASK','SIGNATURE'}|{f'D{i:02X}'for i in range(8)}
 if set(fields)!=expected:raise ValueError('发生器字段集合无效')
 def n(k):
  if not re.fullmatch('[0-9A-F]{8}',fields[k]):raise ValueError('发生器数值无效')
  return int(fields[k],16)
 result={k.lower():n(k)for k in ['VERSION','SEQUENCE','CLOCK_HZ','CONTROL','ENABLE_MASK','SIGNATURE']}
 if result['version']!=1 or result['signature']!=0x47575831 or result['clock_hz']!=27000000 or result['control']not in(0,3,5)or result['enable_mask']>255:raise ValueError('发生器能力签名或状态无效')
 channels=[]
 for ch in range(8):
  text=fields[f'D{ch:02X}']
  if not re.fullmatch('[0-9A-F]{8}(,[0-9A-F]{8}){2}',text):raise ValueError('发生器通道参数无效')
  period,high,phase=[int(v,16)for v in text.split(',')]
  if not 270<=period<=27000000 or not 0<high<period or not 0<=phase<period:raise ValueError('发生器参数越界')
  channels.append(dict(channel=ch,period=period,high=high,phase_ticks=phase,enabled=bool(result['enable_mask']&(1<<ch)),actual_frequency=27000000/period,actual_duty=high/period*100,actual_phase=phase/period*360))
 return dict(**result,channels=channels,running=bool(result['control']&1),loopback=bool(result['control']&2),external_armed=bool(result['control']&4),watchdog_seconds=2)
