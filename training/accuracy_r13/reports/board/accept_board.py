import sys
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
import json,re,time,hashlib,sys
from urllib.request import urlopen,Request
P=Path('F:/脑机项目/guanweixin_demo_v01');R=P/'submission/观微芯_AI精度优化_20261030_r13';OUT=P/'development/ai_accuracy_20261030_r13/reports/board';BASE='http://127.0.0.1:8765'
sys.path.insert(0,str(R/'host'));from ai_workbench import AIFramer;from instrument_protocol import parse_record

def get(path):return json.load(urlopen(BASE+path,timeout=5))
def post(path,body):
 root=urlopen(BASE+'/',timeout=5).read().decode('utf-8');token=json.loads(re.search(r'const token=("[^"]+")',root)[1]);req=Request(BASE+path,data=json.dumps(body).encode(),headers={'Content-Type':'application/json','X-GWX-Control':token},method='POST');return json.load(urlopen(req,timeout=10))
def wait_ready(timeout):
 end=time.monotonic()+timeout
 while time.monotonic()<end:
  s=get('/api/status')
  if not s['connected']or s['error']:raise RuntimeError('Serial state '+str(s))
  if s['ready']and not s['pending']:return s
  time.sleep(.25)
 raise TimeoutError('Board did not return READY; raw data retained, no automatic retry')
def save(name,obj):(OUT/(name+'.json')).write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')

def main():
 config=json.loads((OUT/'configuration_evidence.json').read_text());assert config['sram_configuration_success']and not config['flash_written'];assert config['model_crc32']=='b3889358'
 assert hashlib.sha256(Path(config['bitstream']).read_bytes()).hexdigest()==config['bitstream_sha256']
 status=wait_ready(30);raw=(OUT/'fresh_boot_uart.bin').read_bytes().decode('ascii');assert 'GWX IRQ SELFTEST PASS'in raw and 'SELFTEST FAIL'not in raw
 boot=[parse_record(v)for k,v in AIFramer().feed(raw)if k=='record'];assert len(boot)==33 and all(x['status']=='PASS'and x['source']=='INTERNAL'for x in boot)
 save('boot_acceptance',dict(pass_all=True,machine_irq_selftest=True,acquisition_tests=33,external_signal_tested=False,records=boot));print('PASS real board machine selftest and 33 acquisition cases',flush=True)
 summary=dict(bitstream_sha256=config['bitstream_sha256'],firmware_sha256='17ccef9482873d5c6909263205f3f0b72c488beb9456535f0c3873c73c844ba0',physical_hardware_tested=True,flash_written=False,external_signal_tested=False,clock_independently_calibrated=False,benchmarks=[],ai=[])
 for mode in(0,1):
  before=get('/api/status')['benchmark_count'];post('/api/command',{'cmd':4,'mode':mode});print('START real CoreMark mode',mode,flush=True);wait_ready(120);rows=get('/api/benchmarks');row=next(x for x in rows if x['mode']==mode and x['origin']=='SERIAL');assert row['valid']and row['crc_ok']and row['seconds']>=10;assert get('/api/status')['benchmark_count']==before+1
  summary['benchmarks'].append(row);save('board_acceptance_progress',summary);print('PASS CoreMark',mode,row['coremark_per_mhz'],flush=True)
 for name,mode,ch,software,label in [(n+('_cpu' if sw else ''),m,0,sw,l) for n,m,l in [('normal',0,0),('missing',1,1),('period',2,2),('stuck_high',4,3),('stuck_low',3,4)] for sw in (False,True)]+[('stuck_low_d7',3,7,False,4)]:
  before=get('/api/ai/results')['total'];post('/api/ai/command',{'config':{'mode':mode,'channel':ch},'software':software});print('START real AI',name,flush=True);wait_ready(600);rows=get('/api/ai/results');assert rows['total']==before+1;row=rows['items'][0];f=row['frame'];assert row['origin']=='SERIAL'and f['STATUS']=='PASS'and f['LABEL']==label and f['RUNTIME_VERSION']==2 and f['MODEL_CRC']==0xb3889358 and f['ACCEL']==int(not software)and f['EOS']==2 and f['CHANNEL']==ch
  detail=get('/api/ai/result?id='+str(row['id']));save('ai_'+name,detail);summary['ai'].append(dict(case=name,**row));save('board_acceptance_progress',summary);print('PASS AI',name,f['nominal_inference_seconds'],flush=True)
 accelerated=next(x for x in summary['ai']if x['case']=='stuck_low')['frame'];cpu=next(x for x in summary['ai']if x['case']=='stuck_low_cpu')['frame'];assert all(cpu[k]==accelerated[k]for k in('TOKEN','EOS','LABEL','SCORE_PERMILLE','DOT_GROUPS'));summary['ai_low_acceleration_speedup']=cpu['inference_ticks']/accelerated['inference_ticks'];summary['class_speedups']={}
 for name in ('normal','missing','period','stuck_high','stuck_low'):
  a=next(x for x in summary['ai']if x['case']==name)['frame'];c=next(x for x in summary['ai']if x['case']==name+'_cpu')['frame'];assert all(a[k]==c[k]for k in ('TOKEN','EOS','LABEL','SCORE_PERMILLE','DOT_GROUPS'));summary['class_speedups'][name]=c['inference_ticks']/a['inference_ticks']
 summary['all_pass']=True
 save('board_acceptance',summary);print('ALL automated board acceptance PASS',flush=True)
if __name__=='__main__':main()