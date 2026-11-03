"""Independent full FP32/Q8 C comparison and historical internal-capture audit."""
import csv, hashlib, json, sqlite3, subprocess, time
from pathlib import Path
import numpy as np
import torch
from third_party.model import ModelArgs, Transformer
from llm_io import Tokenizer
from signal_data import CODES, LABELS, summarize

ROOT=Path(__file__).resolve().parent
DATABASE=Path('F:/脑机项目/guanweixin_demo_v01/development/logic_workbench_monochrome_20261026_r09/data/instrument.sqlite3')

def linux(path):
    p=Path(path).resolve();return '/mnt/'+p.drive[0].lower()+p.as_posix()[2:]

def run(args,name,timeout=180):
    with (ROOT/'reports'/name).open('wb') as f:
        subprocess.run(['wsl','-d','Ubuntu','--cd',linux(ROOT),'--exec',*args],stdout=f,stderr=subprocess.STDOUT,timeout=timeout,check=True)

def historical_cases():
    # Read-only connection, no copying into or modifying the live evidence DB.
    uri=DATABASE.as_uri()+'?mode=ro'
    c=sqlite3.connect(uri,uri=True);result=[];seen=set();total=0
    for rid,payload in c.execute('SELECT id,payload FROM captures ORDER BY id'):
        r=json.loads(payload)
        if r.get('status')!='PASS' or r.get('source')!='INTERNAL':continue
        total+=1
        cfg=r['config'];expected=(cfg['pmin']+cfg['pmax'])//2
        for ch in range(8):
            if not cfg['monitor']&(1<<ch):continue
            bits=[(v>>ch)&1 for v in r['samples']];key=(tuple(bits),expected)
            if key in seen:continue
            seen.add(key)
            faults=[f for f in r['faults'] if f['channel']==ch]
            label='NORMAL' if not faults else faults[0]['code']
            if label=='STUCK':
                label='STUCK_HIGH' if all(bits) else 'STUCK_LOW' if not any(bits) else 'UNKNOWN'
            if label not in CODES:continue
            s=summarize(bits,expected)
            result.append(dict(id=f'history-{rid}-D{ch}',record_id=rid,channel=ch,label=label,answer=CODES[label],
                               source='HISTORICAL_INTERNAL_SELFTEST',reference='Production CPU rule label; not independent external ground truth',**s))
    c.close();return result,total

def main():
    torch.set_num_threads(4)
    out=ROOT/'reports';out.mkdir(exist_ok=True)
    tok=Tokenizer(ROOT/'pretrained/tok512.bin');codeids={code:tok.index[code] for code in 'ABCDEF'}
    test=[json.loads(x) for x in (ROOT/'data/test.jsonl').read_text().splitlines()]
    history,total=historical_cases();cases=test+history
    (out/'historical_cases.json').write_text(json.dumps(dict(original_internal_captures=total,unique_channel_waveforms=len(history),
        external_cases=0,cases=history),ensure_ascii=False,indent=2),encoding='utf-8')
    prompts=[]
    with (out/'probe_input.txt').open('w',encoding='ascii') as f:
        for c in cases:
            ids=tok.encode(c['prompt']);prompts.append(ids)
            if len(ids)>126:raise ValueError('Too long')
            f.write(f"{c['id']} {len(ids)} {codeids[c['answer']]} "+' '.join(map(str,ids))+'\n')
    flags=['-O2','-Wall','-Wextra','-Wno-unknown-pragmas','-Wno-unused-variable']
    run(['gcc',*flags,'-DFP32','probe_model.c','-lm','-o','probe_fp32'],'compile_fp32.log')
    run(['gcc',*flags,'probe_model.c','-lm','-o','probe_q8'],'compile_q8.log')
    run(['./probe_fp32','artifacts/diagnostic_f32.bin','reports/probe_input.txt','reports/c_fp32.csv'],'run_fp32.log')
    run(['./probe_q8','artifacts/diagnostic_q8.bin','reports/probe_input.txt','reports/c_q8.csv'],'run_q8.log')
    fp=list(csv.DictReader((out/'c_fp32.csv').open()));q=list(csv.DictReader((out/'c_q8.csv').open()))
    if len(fp)!=len(cases) or len(q)!=len(cases):raise RuntimeError('Missing C results')
    model=Transformer(ModelArgs(dim=64,hidden_dim=172,n_layers=5,n_heads=8,n_kv_heads=4,vocab_size=512,multiple_of=4,max_seq_len=128,dropout=0))
    with np.load(ROOT/'artifacts/diagnostic_weights.npz',allow_pickle=False) as weights:
        model.load_state_dict({k:torch.from_numpy(weights[k].copy()) for k in weights.files})
    model.eval();errors=[];maxdiff=0.0;predmatch=0
    with torch.no_grad():
        for start in range(0,len(prompts),64):
            group=prompts[start:start+64];n=max(map(len,group));x=torch.zeros((len(group),n),dtype=torch.long)
            for j,p in enumerate(group):x[j,:len(p)]=torch.tensor(p)
            logits=model(x,torch.full_like(x,-1))
            for j,p in enumerate(group):
                i=start+j;ref=logits[j,len(p)-1].numpy();c=np.fromstring(fp[i]['logits'],sep=' ')
                maxdiff=max(maxdiff,float(np.max(np.abs(ref-c))))
                predmatch+=int(int(ref.argmax())==int(fp[i]['predicted_token']))
    report=dict(scope='Full Transformer host execution, not FPGA; C FP32 padding equivalence and Q8 end-to-end task check',
                cases=len(cases),synthetic_test_cases=len(test),historical_unique_channel_waveforms=len(history),
                historical_original_capture_count=total,external_cases=0,fp32_c_vs_pytorch_max_abs_logit_error=maxdiff,
                fp32_c_vs_pytorch_predictions_equal=predmatch==len(cases),matrix_group=64,padded_ffn=192,
                full_integer_inference=False,model_runs_on_fpga=False,results={})
    for name,rows in [('synthetic_test',q[:len(test)]),('historical_internal',q[len(test):])]:
        cm=np.zeros((6,7),int);inv={v:k for k,v in codeids.items()};eosok=0;accepted=0;correctaccepted=0;ms=[];disagree=0
        base=0 if name=='synthetic_test' else len(test)
        for i,row in enumerate(rows):
            c=cases[base+i];pred=inv.get(int(row['predicted_token']),'?');want=c['answer']
            cm[ord(want)-65,ord(pred)-65 if pred!='?' else 6]+=1
            eosok+=int(row['eos_token']=='2');ms.append(float(row['host_ms']))
            disagree+=int(row['predicted_token']!=fp[base+i]['predicted_token'])
            # Fixed engineering threshold, not a calibrated real-world probability.
            if float(row['top_score'])>=.8 and pred!='?' and row['eos_token']=='2':
                accepted+=1;correctaccepted+=int(pred==want)
            if pred!=want:errors.append(dict(id=c['id'],expected=want,predicted=pred,score=float(row['top_score'])))
        n=len(rows)
        report['results'][name]=dict(total=n,correct=int(np.trace(cm[:,:6])),accuracy=float(np.trace(cm[:,:6]))/n if n else None,
            confusion=cm.tolist(),eos_correct=eosok,q8_vs_fp32_label_disagreements=disagree,
            score_threshold=.8,accepted=accepted,accepted_correct=correctaccepted,host_mean_ms=float(np.mean(ms)) if ms else None,
            host_p95_ms=float(np.percentile(ms,95)) if ms else None)
    report['errors']=errors
    report['equivalence_gate_pass']=maxdiff<.0005 and predmatch==len(cases)
    (out/'full_model_validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    # Timing is workstation C code only; never use this as FPGA/CPU speedup evidence.
    print(json.dumps({k:v for k,v in report.items() if k not in ('errors','results')},ensure_ascii=False),flush=True)
    print(json.dumps(report['results'],ensure_ascii=False),flush=True)
    if not report['equivalence_gate_pass']:raise RuntimeError('Independent FP32 equivalence failed')

if __name__=='__main__':main()
