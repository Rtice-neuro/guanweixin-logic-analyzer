from pathlib import Path
import subprocess,time,json,sys,csv
sys.stdout.reconfigure(encoding='utf-8');r=Path(__file__).resolve().parent;lp='/mnt/'+r.drive[0].lower()+r.as_posix()[2:]
for model in ['baseline_q4','diagnostic_q4']:
 for split in ['validation','test','anchors']:
  name=model+'_'+split;t=time.monotonic();print('START C DEPLOYMENT',name,flush=True)
  proc=subprocess.run(['wsl','-d','Ubuntu','--cd',lp,'--exec','host/probe_q4','artifacts/'+model+'.bin','data/'+split+'_probe.txt','reports/'+name+'.csv'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=300);(r/'reports'/(name+'.log')).write_bytes(proc.stdout);assert proc.returncode==0,(name,proc.returncode,proc.stdout)
  rows=list(csv.DictReader((r/'reports'/(name+'.csv')).open()));good=sum(x['expected_token']==x['predicted_token']for x in rows);eos=sum(x['eos_token']=='2'for x in rows);print('RESULT',name,good,'/',len(rows),'EOS',eos,'seconds',time.monotonic()-t,flush=True)
