"""Fine-tune the user's existing 260K pretrained Llama with response-only LM loss."""
import argparse, copy, hashlib, json, math, time
from pathlib import Path
import numpy as np
import torch
from third_party.model import Transformer, ModelArgs
from llm_io import Tokenizer, load_legacy, export_weights
from signal_data import LABELS, CODES, write_corpus, rule_baseline

ROOT = Path(__file__).resolve().parent

def load_cases(split):
    return [json.loads(x) for x in (ROOT/'data'/f'{split}.jsonl').read_text(encoding='utf-8').splitlines()]

def pack(cases,tok,codeids):
    rows=[]
    for c in cases:
        prefix=tok.encode(c['prompt']); ids=prefix+[codeids[c['answer']],2]
        if len(ids)>128: raise ValueError('Context limit')
        x=ids[:-1]; y=[-1]*(len(prefix)-1)+ids[len(prefix):]
        rows.append((x,y,len(prefix)))
    return rows

def batch(rows, indices):
    n=max(len(rows[i][0]) for i in indices)
    x=torch.zeros((len(indices),n),dtype=torch.long);y=torch.full_like(x,-1)
    for j,i in enumerate(indices):
        a,b,_=rows[i]; x[j,:len(a)]=torch.tensor(a); y[j,:len(b)]=torch.tensor(b)
    return x,y

@torch.no_grad()
def evaluate(model,cases,rows,codeids):
    model.eval(); inverse={v:k for k,v in codeids.items()}; matrix=np.zeros((6,7),dtype=int); bad=[]
    predlist=[]
    for start in range(0,len(rows),64):
        inds=list(range(start,min(start+64,len(rows))));x,y=batch(rows,inds)
        logits=model(x,y)
        for j,i in enumerate(inds):
            predid=int(logits[j,rows[i][2]-1].argmax());code=inverse.get(predid,'?')
            want=cases[i]['answer']; matrix[ord(want)-65, ord(code)-65 if code!='?' else 6]+=1
            predlist.append(code)
            if code!=want and len(bad)<30:bad.append(dict(id=cases[i]['id'],prompt=cases[i]['prompt'],expected=want,predicted=code,token_id=predid))
    correct=sum(matrix[i,i] for i in range(6)); total=len(rows)
    rules=[CODES[rule_baseline(c['samples'],c['expected_period'])] for c in cases]
    return dict(accuracy=correct/total,correct=int(correct),total=total,confusion=matrix.tolist(),
                columns=list(CODES)+['INVALID'],rows=LABELS,
                rule_baseline_accuracy=sum(c['answer']==p for c,p in zip(cases,rules))/total,
                invalid_outputs=sum(p=='?' for p in predlist),errors=bad,predictions=predlist)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--steps',type=int,default=900);ap.add_argument('--threads',type=int,default=4);args=ap.parse_args()
    torch.set_num_threads(args.threads);torch.manual_seed(28028);np.random.seed(28028)
    out=ROOT/'artifacts';out.mkdir(exist_ok=True);logs=ROOT/'reports';logs.mkdir(exist_ok=True)
    write_corpus(ROOT/'data')
    tok=Tokenizer(ROOT/'pretrained/tok512.bin');codeids={c:tok.index[c] for c in 'ABCDEF'}
    model=Transformer(ModelArgs(dim=64,hidden_dim=172,n_layers=5,n_heads=8,n_kv_heads=4,vocab_size=512,multiple_of=4,max_seq_len=128,dropout=0.0))
    source=load_legacy(model,ROOT/'pretrained/stories260K.bin')
    cases={s:load_cases(s) for s in ('train','validation','test')}; rows={s:pack(v,tok,codeids) for s,v in cases.items()}
    val_indices=[i for i in range(0,len(cases['validation']),4)]
    vcases=[cases['validation'][i] for i in val_indices];vrows=[rows['validation'][i] for i in val_indices]
    baseline=evaluate(model,vcases,vrows,codeids);baseline.pop('predictions')
    report=dict(stage='TRAINING',pretrained=source,architecture='5-layer causal Llama, grouped-query attention, RoPE, SwiGLU, tied LM head',
                task='Signal-summary -> one diagnostic token A..F + EOS; no new classifier head',
                codes=CODES,code_token_ids=codeids,inputs_only='high count, edge count, normalized rising-edge gaps, nominal period used for normalization',
                loss='response-only autoregressive language-model cross entropy',training_scope='All pretrained parameters fine-tuned',
                validation_before=baseline,history=[],hardware_inference=False,external_accuracy_measured=False,
                data_provenance='SYNTHETIC_ONLY; historical internal captures held out', max_context=128)
    (out/'model_config.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    opt=torch.optim.AdamW(model.parameters(),lr=6e-4,weight_decay=.01,betas=(.9,.99))
    gen=np.random.default_rng(28028);best=-1;bestloss=1e10;beststate=None;t0=time.perf_counter()
    log=(logs/'training.jsonl').open('w',encoding='utf-8')
    for step in range(1,args.steps+1):
        model.train(); inds=gen.integers(0,len(rows['train']),48).tolist(); x,y=batch(rows['train'],inds)
        lr=6e-4*min(1,step/30)*(.25+.75*.5*(1+math.cos(math.pi*step/args.steps)))
        for g in opt.param_groups:g['lr']=lr
        opt.zero_grad(set_to_none=True);model(x,y);loss=model.last_loss;loss.backward();torch.nn.utils.clip_grad_norm_(model.parameters(),1.0);opt.step()
        if step==1 or step%100==0 or step==args.steps:
            result=evaluate(model,vcases,vrows,codeids);result.pop('predictions')
            item=dict(step=step,loss=float(loss),validation_accuracy=result['accuracy'],elapsed_seconds=time.perf_counter()-t0)
            report['history'].append(item);print(json.dumps(item),flush=True);log.write(json.dumps(item)+'\n');log.flush()
            if (result['accuracy'], -float(loss))>(best,-bestloss):
                best=result['accuracy'];bestloss=float(loss);beststate=copy.deepcopy(model.state_dict());report['best_step']=step
    log.close();model.load_state_dict(beststate);model.eval()
    report['validation']=evaluate(model,cases['validation'],rows['validation'],codeids);report['validation'].pop('predictions')
    report['test']=evaluate(model,cases['test'],rows['test'],codeids)
    predictions=report['test'].pop('predictions')
    with (logs/'test_predictions.jsonl').open('w',encoding='utf-8') as f:
        for c,p in zip(cases['test'],predictions):f.write(json.dumps(dict(id=c['id'],expected=c['answer'],predicted=p,prompt=c['prompt']))+'\n')
    report['export']=export_weights(model,out)
    report.update(stage='HOST_FINE_TUNING_COMPLETE',training_seconds=time.perf_counter()-t0,torch_version=torch.__version__,device='CPU')
    (out/'model_config.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    (logs/'training_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(stage=report['stage'],test_accuracy=report['test']['accuracy'],rule_accuracy=report['test']['rule_baseline_accuracy'],q8_bytes=report['export']['file_bytes'],best_step=report['best_step'])),flush=True)

if __name__=='__main__':main()
