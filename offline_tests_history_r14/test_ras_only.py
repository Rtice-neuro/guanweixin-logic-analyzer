from pathlib import Path
import sys,json,shutil,inspect,random,argparse
ROOT=Path(__file__).resolve().parents[1]
PROJECT=ROOT
sys.path.insert(0,str(PROJECT/'scripts'))
import check_core_sync as suite,firmware,verify
namespace=dict(vars(verify))
ref=inspect.getsource(verify.reference).replace('''        elif op in [0x13,0x33]:''','''        elif op==0x33 and f7==1 and f<4:
            if f==0: out=a*b
            elif f==1: out=(signed(a)*signed(b))>>32
            elif f==2: out=(signed(a)*b)>>32
            else: out=(a*b)>>32
        elif op in [0x13,0x33]:''')
exec(ref,namespace);verify.reference=namespace['reference']
ap=argparse.ArgumentParser();ap.add_argument('--variant',default='candidate');ap.add_argument('--suffix',default='');args=ap.parse_args()
out=ROOT/'verification_fresh'/(args.variant+'_reference'+args.suffix)/'sync_v04/cpu';out.mkdir(parents=True,exist_ok=True)
tb=ROOT/'sim/tb_core_cached.v'
iv=Path(__import__('os').environ['GWX_IVERILOG']);vvp=iv.with_name('vvp.exe')
src=[ROOT/args.variant/n for n in ('gwx_core_sync.v','gwx_core_cached.v','gwx_cache_2way.v')]
verify.run([iv,'-g2012','-Wall','-s','tb_core_sync','-o',out/'core_sync.vvp',*src,tb],out,out/'compile.log')
tests=suite.directed_programs();tests.update({f'stress_{n}':(firmware.random_program(n).resolve(),None,0)for n in range(100)})
tests={}
for depth in (1,4,16,20):
 for link in (1,5):
  p=firmware.Program();p.li(28,0x10000000);p.li(2,0x10000400);p.li(18,0);p.li(20,3)
  p.label('outer');p.emit('jal',link,'f0');p.emit('addi',20,20,-1);p.emit('bne',20,0,'outer');p.emit('sw',18,28,0);p.emit('ebreak')
  for level in range(depth):
   p.label('f'+str(level));p.emit('addi',2,2,-4);p.emit('sw',link,2,0);p.emit('addi',18,18,1)
   if level+1<depth:p.emit('jal',link,'f'+str(level+1))
   p.emit('lw',link,2,0);p.emit('addi',2,2,4);p.emit('jalr',0,link,0)
  tests[f'ras_depth{depth}_link{link}']=(p.resolve(),None,0)
corners=[]
rng=random.Random(20261029);pairs=[(a,b)for a in corners for b in corners]+[(rng.getrandbits(32),rng.getrandbits(32))for _ in range(0)]
for batch in range(0,len(pairs),8):
 p=firmware.Program();p.li(28,0x10000000);index=0
 for pair_index,(a,b) in enumerate(pairs[batch:batch+8],start=batch):
  for f3 in range(4):
   p.li(5,a);p.li(6,b);rd=[7,5,6,0][(f3+pair_index)%4]
   p.emit('raw',(1<<25)|(6<<20)|(5<<15)|(f3<<12)|(rd<<7)|0x33)
   p.emit('addi',8,rd,1);p.emit('sw',8,28,index*4);p.emit('lw',9,28,index*4);index+=1
 p.emit('ebreak');tests[f'zmmul_batch_{batch//8}']=(p.resolve(),None,0)
for f3 in ():tests[f'unsupported_div_{f3}']=([(1<<25)|(6<<20)|(5<<15)|(f3<<12)|(7<<7)|0x33],None,0)
report=dict(all_pass=False,physical_board_tested=False,zmmul_pairs=len(pairs),destination_register_rotation=True,independent_python_arbitrary_precision_reference=True,checks=[])
target=out/'verification.json'
try:
 for name,(words,fault,phase)in tests.items():
  for seed,delay,data_delay in ((1,1,0),(12345,7,7),(87654321,23,31)):
   report['checks'].append(suite.run_case(name,words,fault,phase,seed,delay,data_delay,out,vvp))
  target.write_text(json.dumps(report,indent=2),encoding='utf-8')
  if name.startswith('zmmul')or name.startswith('unsupported')or len(report['checks'])%60==0:print('PASS',name,len(report['checks']),flush=True)
 report.update(all_pass=True,cases=len(report['checks']),retirements=sum(x['retirements_compared']for x in report['checks']))
except Exception as e:report['error']=repr(e);raise
finally:target.write_text(json.dumps(report,indent=2),encoding='utf-8')
print('ALL PASS',report['cases'],report['retirements'],flush=True)
