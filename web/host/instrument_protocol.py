"""Strict v0.2 acquisition records and bounded 16-byte CPU commands."""
import re

HEADER='GWX DET8 v0.2'
NAMES={'NONE','MISSING_PULSE','PERIOD','STUCK'}


def configuration(values):
    defaults=dict(cmd=2,divider=270,mask=255,value=16,trigger=0,monitor=255,
                  pmin=6,pmax=10,missing=14,mode=0,channel=0)
    if set(values)-set(defaults):raise ValueError('未知配置字段')
    for key,value in values.items():
        if type(value) is not int:raise ValueError('配置必须为整数')
        defaults[key]=value
    c=defaults
    if not (1<=c['cmd']<=4 and 1<=c['divider']<=65535 and 0<=c['mask']<=255
            and 0<=c['value']<=255 and 0<=c['trigger']<=2 and 1<=c['monitor']<=255
            and 2<=c['pmin']<=c['pmax']<c['missing']<=63
            and 0<=c['mode']<=4 and 0<=c['channel']<=7):
        raise ValueError('配置超出可用范围')
    if c['cmd']==4 and c['mode']>1:raise ValueError('CoreMark只能选择性能组或验证组')
    return c


def command_packet(values):
    c=configuration(values)
    p=bytearray([0xa5,0x5a,1,c['cmd'],c['divider']&255,c['divider']>>8,
                 c['mask'],c['value'],c['trigger'],c['monitor'],c['pmin'],c['pmax'],
                 c['missing'],c['mode'],c['channel']])
    check=0
    for b in p:check^=b
    p.append(check)
    return bytes(p)


def parse_record(raw):
    lines=raw.replace('\r\n','\n').splitlines()
    if not lines or lines[0]!=HEADER or lines[-1]!='END':raise ValueError('记录头尾不完整')
    fields={};traces=[]
    for line in lines[1:-1]:
        if '=' not in line:raise ValueError('记录包含无效行')
        key,value=line.split('=',1)
        if key=='TRACE':traces.append(value);continue
        if key in fields:raise ValueError('记录字段重复')
        fields[key]=value
    def number(key,width=8):
        value=fields.get(key,'')
        if not re.fullmatch(f'[0-9A-F]{{{width}}}',value):raise ValueError('数值字段无效: '+key)
        return int(value,16)
    result={'board_id':number('ID'),'status':fields.get('CAPTURE'),'source':fields.get('SOURCE','UNKNOWN'),
            'raw':raw,'faults':[],'samples':[],'trace':[]}
    result['clock_hz']=number('CLOCK_HZ')if 'CLOCK_HZ'in fields else 27000000
    if result['clock_hz']not in(27000000,60000000):raise ValueError('未验证的采样时钟配置')
    if result['status'] in ('TIMEOUT','CONFIG_ERROR'):
        if result['status']=='CONFIG_ERROR' and fields.get('ERROR') not in ('BAD_PACKET','RANGE','SOURCE_UNAVAILABLE'):
            raise ValueError('配置错误类型无效')
        result['error']=fields.get('ERROR',result['status']);return result
    data=fields.get('DATA','')
    if not re.fullmatch('[0-9A-F]{128}',data):raise ValueError('采样数据必须为64字节')
    result['samples']=list(bytes.fromhex(data))
    if result['source']=='INJECTED':
        result['injection_id']=number('INJECTION_ID')
        if fields.get('TIMEBASE')!='VIRTUAL_SAMPLE_GRID':raise ValueError('注入记录时间基准无效')
        result['timebase_kind']='VIRTUAL_SAMPLE_GRID'
    if result['status']=='FAIL':return result
    if result['status']!='PASS':raise ValueError('采集状态无效')
    if number('COUNT')!=64 or number('SUM')!=sum(result['samples']) or number('UART_SUM'if result['source']=='INJECTED'else'HW_SUM')!=number('SUM'):
        raise ValueError('计数/校验失败')
    if result['source'] not in ('INTERNAL','EXTERNAL','INJECTED'):raise ValueError('信号来源无效')
    monitor=number('MONITOR_MASK',2)
    cfg=configuration(dict(cmd=1 if result['source']=='EXTERNAL' else 2,divider=number('DIVIDER'),
                           mask=number('TRIGGER_MASK'),value=number('TRIGGER_VALUE'),trigger=number('TRIGGER_MODE'),
                           monitor=monitor,pmin=number('PERIOD_MIN'),pmax=number('PERIOD_MAX'),missing=number('MISSING_GAP'),
                           mode=number('SCENARIO'),channel=number('INJECT_CHANNEL')))
    result['config']=cfg
    result['input_kind']='UART_INJECTION'if result['source']=='INJECTED'else'INTERNAL_SELFTEST'if result['source']=='INTERNAL'else'EXTERNAL'
    for ch in range(8):
        parts=fields.get(f'CH{ch:02X}','').split(',')
        if len(parts)!=3 or parts[0] not in NAMES or any(not re.fullmatch('[0-9A-F]{8}',x)for x in parts[1:]):
            raise ValueError('通道故障字段无效')
        code,index,gap=parts[0],int(parts[1],16),int(parts[2],16)
        if code=='NONE':
            if index!=0xffffffff or gap:raise ValueError('正常通道位置字段无效')
        else:
            if not (monitor&(1<<ch)) or index>=64 or gap>63:raise ValueError('异常通道或位置越界')
            result['faults'].append(dict(channel=ch,code=code,index=index,gap=gap))
    if len(result['faults'])!=number('FAULT_COUNT'):raise ValueError('故障数量不一致')
    result['analysis']={k:number('ANALYSIS_'+k.upper())for k in (
        'cycles','retired','branches','data_stalls','fetch_stalls','forward_events','flush_events')}
    if not 0<result['analysis']['retired']<=result['analysis']['cycles']:raise ValueError('性能计数无效')
    result['cpu_options']=number('CPU_OPTIONS')
    if result['cpu_options']>3:raise ValueError('CPU选项无效')
    if len(traces)!=number('TRACE_COUNT') or not 0<len(traces)<=16:raise ValueError('追踪数量无效')
    for value in traces:
        if not re.fullmatch('[0-9A-F]{8}(,[0-9A-F]{8}){3}',value):raise ValueError('追踪数据无效')
        pc,insn,data,meta=[int(x,16)for x in value.split(',')]
        if pc%4 or meta>63:raise ValueError('追踪元数据无效')
        result['trace'].append(dict(pc=pc,instruction=insn,data=data,write=bool(meta&1),rd=meta>>1))
    return result


class Framer:
    def __init__(self):self.pending='';self.frame=[];self.benchmark=[];self.dropped=0
    def feed(self,chunk):
        self.pending+=chunk;events=[]
        while '\n' in self.pending:
            line,self.pending=self.pending.split('\n',1);line=line.rstrip('\r')
            # FPGA SRAM reconfiguration can leave idle UART as a NUL before
            # the first header. Recover only a known frame boundary; data
            # fields remain strict and the original wire stream is preserved.
            boundary=line.lstrip('\x00')
            if boundary!=line and boundary in (HEADER,'GWX READY v0.2','GWX COREMARK BEGIN'):
                line=boundary;self.dropped+=1
            # A reset can interrupt CoreMark: resynchronize, never consume boot
            # records as benchmark text or manufacture a completed benchmark.
            if self.benchmark and line in (HEADER,'GWX READY v0.2'):
                self.benchmark=[];self.dropped+=1
            if line=='GWX COREMARK BEGIN':self.benchmark=[line]
            elif self.benchmark:
                self.benchmark.append(line)
                if sum(map(len,self.benchmark))>32768:self.benchmark=[];self.dropped+=1
                elif line=='GWX COREMARK END':events.append(('benchmark','\r\n'.join(self.benchmark)+'\r\n'));self.benchmark=[]
            elif line==HEADER:
                if self.frame:self.dropped+=1
                self.frame=[line]
            elif self.frame:
                self.frame.append(line)
                if sum(map(len,self.frame))>16384:self.frame=[];self.dropped+=1
                elif line=='END':events.append(('record','\r\n'.join(self.frame)+'\r\n'));self.frame=[]
            elif line=='GWX READY v0.2':events.append(('ready',line))
        if len(self.pending)>16384:self.pending='';self.frame=[];self.dropped+=1
        return events


def parse_benchmark(raw):
    if not raw.startswith('GWX COREMARK BEGIN\r\n') or not raw.endswith('GWX COREMARK END\r\n'):
        raise ValueError('CoreMark记录不完整')
    def hex_field(name):
        values=re.findall(r'^'+name+r'=([0-9A-F]{8})\r?$',raw,re.M)
        if len(values)!=1:raise ValueError('CoreMark字段无效: '+name)
        return int(values[0],16)
    mode=hex_field('MODE');clock=hex_field('CLOCK_HZ');options=hex_field('CPU_OPTIONS')
    ticks=(hex_field('TICKS_HIGH')<<32)|hex_field('TICKS_LOW')
    if mode not in (0,1) or clock not in(27000000,60000000) or options>3 or ticks<=0:raise ValueError('CoreMark配置/计时无效')
    crcs={}
    for name in ('seedcrc','crclist','crcmatrix','crcstate'):
        values=re.findall(name+r'\s*:\s*0x([0-9a-fA-F]+)',raw)
        if len(values)!=1:raise ValueError('CoreMark CRC缺失/重复')
        crcs[name]=values[0].lower().zfill(4)
    want=dict(zip(crcs,('e9f5','e714','1fd7','8e3a')if mode==0 else ('18f2','e3c1','0747','8d84')))
    matches=re.findall(r'Iterations\s*:\s*(\d+)',raw)
    if len(matches)!=1 or int(matches[0])<=0:raise ValueError('CoreMark迭代数无效')
    iterations=int(matches[0]);seconds=ticks/clock
    crc_ok=crcs==want
    valid=crc_ok and seconds>=10 and hex_field('COREMARK_RETURN')==0 and 'Correct operation validated'in raw and 'ERROR!'not in raw
    return dict(mode=mode,clock_hz=clock,ticks=ticks,seconds=seconds,iterations=iterations,
                cpu_options=options,crcs=crcs,crc_ok=crc_ok,valid=valid,
                iterations_per_second=iterations/seconds if valid else None,
                coremark_per_mhz=iterations/seconds/(clock/1000000) if valid else None,raw=raw)
