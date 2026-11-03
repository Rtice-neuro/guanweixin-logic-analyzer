from pathlib import Path
import csv,hashlib,json,shutil,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[1]
REFERENCE=ROOT.parent/'diagnostic_transformer_20261028_r01'
def linux(p):
 p=Path(p).resolve();return '/mnt/'+p.drive[0].lower()+p.as_posix()[2:]
def run(args,name,timeout=180):
 with (ROOT/'reports'/name).open('wb')as f:subprocess.run(['wsl','-d','Ubuntu','--cd',linux(ROOT),'--exec',*args],check=True,stdout=f,stderr=subprocess.STDOUT,timeout=timeout)
def main():
 shutil.copy2(REFERENCE/'reports/probe_input.txt',ROOT/'reports/probe_input.txt')
 flags=['-std=c11','-O2','-Wall','-Wextra','-Wno-misleading-indentation','-ffp-contract=off']
 run(['gcc',*flags,'host/probe_q4.c','firmware/gwx_ai.c','-o','host/probe_q4'],'q4_compile.log')
 run(['host/probe_q4','model/diagnostic_q4.bin','reports/probe_input.txt','reports/q4_predictions.csv'],'q4_run.log')
 with (ROOT/'reports/q4_predictions.csv').open()as f:rows=list(csv.DictReader(f))
 with (REFERENCE/'reports/c_q8.csv').open()as f:ref=list(csv.DictReader(f))
 if len(rows)!=730:raise RuntimeError('Incomplete model validation')
 result=dict(scope='Complete allocation-free portable C Transformer; Q4 weights, Q8 activations, FP16 stored KV, software FP32 nonlinear math',
             pc_inference=True,fpga_inference=False,reference_model='Q8 complete C model, not an oracle',splits={})
 for name,begin,end in [('synthetic_test',0,720),('historical_internal',720,len(rows))]:
  group=rows[begin:end];errors=[]
  for i,r in enumerate(group):
   if r['expected_token']!=r['predicted_token']:errors.append(dict(id=r['id'],expected=r['expected_token'],actual=r['predicted_token'],score=float(r['score'])))
  result['splits'][name]=dict(total=len(group),correct=len(group)-len(errors),accuracy=(len(group)-len(errors))/len(group),
     q4_vs_q8_token_differences=sum(r['predicted_token']!=ref[begin+i]['predicted_token']for i,r in enumerate(group)),
     eos_correct=sum(r['eos_token']=='2'for r in group),errors=errors)
 result['synthetic_gate_pass']=result['splits']['synthetic_test']['accuracy']>=.95 and result['splits']['synthetic_test']['eos_correct']==720
 (ROOT/'reports/q4_validation.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
 # Sanitizer reference is a small fixed case set, not a claim of universal safety.
 (ROOT/'reports/sanitizer_input.txt').write_text('\n'.join((ROOT/'reports/probe_input.txt').read_text().splitlines()[:12])+'\n',encoding='ascii')
 run(['gcc','-std=c11','-O1','-g','-fsanitize=address,undefined','-fno-omit-frame-pointer','-ffp-contract=off','host/probe_q4.c','firmware/gwx_ai.c','-o','host/probe_q4_checked'],'q4_sanitizer_compile.log')
 run(['host/probe_q4_checked','model/diagnostic_q4.bin','reports/sanitizer_input.txt','reports/sanitizer_results.csv'],'q4_sanitizer_run.log')
 print(json.dumps(dict(pass_gate=result['synthetic_gate_pass'],results=result['splits']),ensure_ascii=False),flush=True)
 if not result['synthetic_gate_pass']:raise RuntimeError('Q4 not suitable for this board candidate')
if __name__=='__main__':main()
