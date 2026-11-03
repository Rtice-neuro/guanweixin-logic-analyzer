"""UART-injected digital test vectors: host data, board-executed analysis."""
import math,re
from instrument_protocol import configuration
SIGNATURE=0x47574931

def packet(op,payload=b''):
 if op not in(0,1,2)or len(payload)>10:raise ValueError('注入包无效')
 data=bytearray([0xa5,0x5a,1,12,op])+bytearray(payload)+bytearray(10-len(payload));check=0
 for b in data:check^=b
 return bytes(data+bytes([check]))
def prepare(body,request_id):
 if not isinstance(body,dict)or set(body)-{'samples','sample_rate','rules','label'}:raise ValueError('注入字段无效')
 samples=body.get('samples');rate=body.get('sample_rate')
 if not isinstance(samples,list)or len(samples)!=64 or any(type(v)is not int or not 0<=v<=255 for v in samples):raise ValueError('需要64个八路数字采样字节，每项0至255')
 if type(rate)not in(int,float)or not math.isfinite(rate)or rate<=0:raise ValueError('虚拟采样率无效')
 divider=round(27000000/rate)
 if not 1<=divider<=65535:raise ValueError('虚拟采样率超出27MHz时基可表示范围')
 rules=body.get('rules',{})
 if not isinstance(rules,dict)or set(rules)-{'monitor','pmin','pmax','missing'}:raise ValueError('检测规则无效')
 cfg=configuration(dict(cmd=2,divider=divider,mask=0,value=0,**rules));label=body.get('label','网页数字波形')
 if not isinstance(label,str)or len(label)>80:raise ValueError('标签过长')
 begin=packet(0,request_id.to_bytes(4,'little')+divider.to_bytes(2,'little')+bytes([cfg['monitor'],cfg['pmin'],cfg['pmax'],cfg['missing']]))
 chunks=[packet(1,bytes([offset])+bytes(samples[offset:offset+8])+bytes([0]))for offset in range(0,64,8)]
 checksum=sum(samples);run=packet(2,request_id.to_bytes(4,'little')+checksum.to_bytes(4,'little')+bytes([0,0]))
 return dict(request_id=request_id,samples=list(samples),checksum=checksum,requested_sample_rate=rate,effective_sample_rate=27000000/divider,divider=divider,config=cfg,label=label,packets=[begin,*chunks,run])
def parse_ack(raw):
 lines=raw.replace('\r\n','\n').splitlines()
 if not lines or lines[0]!='GWX INJECT BEGIN'or lines[-1]!='GWX INJECT END':raise ValueError('注入确认帧不完整')
 fields={}
 for l in lines[1:-1]:
  if '='not in l:raise ValueError('注入确认字段无效')
  k,v=l.split('=',1)
  if k in fields or not re.fullmatch('[0-9A-F]{8}',v):raise ValueError('注入确认重复或数值无效')
  fields[k]=int(v,16)
 if set(fields)!={'VERSION','SEQUENCE','SIGNATURE','INJECTION_ID','COUNT','ACTIVE'}or fields['VERSION']!=1 or fields['SIGNATURE']!=SIGNATURE or fields['ACTIVE']not in(0,1)or fields['COUNT']not in range(0,65,8):raise ValueError('注入能力或进度无效')
 return dict(version=1,sequence=fields['SEQUENCE'],signature=SIGNATURE,request_id=fields['INJECTION_ID'],count=fields['COUNT'],active=bool(fields['ACTIVE']))
