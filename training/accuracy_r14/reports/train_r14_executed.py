from pathlib import Path
import sys,json,random,hashlib,copy,time,collections
import numpy as np,torch
sys.stdout.reconfigure(encoding='utf-8');R=Path(__file__).resolve().parent;S=R.with_name('ai_accuracy_20261030_r13');sys.path.insert(0,str(R/'training'))
from signal_data import summarize,make_case,LABELS,CODES
from llm_io import Tokenizer,export_weights,load_legacy
from train_diagnostic import pack,batch,evaluate
from third_party.model import Transformer,ModelArgs
torch.set_num_threads(4);torch.manual_seed(3014);np.random.seed(3014);tok=Tokenizer(R/'training/pretrained/tok512.bin');codeids={c:tok.index[c]for c in 'ABCDEF'}
def read(p):return [json.loads(l)for l in p.read_text(encoding='utf-8').splitlines()]
train=read(S/'data/train.jsonl');val=read(S/'data/validation.jsonl');oldtest=read(S/'data/test.jsonl');seen={c['prompt']for c in train+val+oldtest};anchors=[]
for lab in ['STUCK_HIGH','STUCK_LOW']:
 for k in range(5):
  steady=int(lab=='STUCK_HIGH');bits=[1-steady]*k+[steady]*(64-k);c=dict(samples=bits,label=lab,answer=CODES[lab],**summarize(bits,8),id=f'train-settling-{lab}-{k}',label_origin='Synthetic known startup settling interval 0..4 samples, then >=60 stable samples');anchors.append(c)
  if c['prompt']not in seen:train.append(c);seen.add(c['prompt'])
assert len({c['prompt']for c in train})==len(train)
assert not({c['prompt']for c in train}&{c['prompt']for c in val})
reserved={c['prompt']for c in json.loads((S/'reference_r12/verification/ai_synthetic_evaluation.json').read_text(encoding='utf-8'))['checks']};seen|=reserved
rng=random.Random(301401);test=[]
for lab,target in [('NORMAL',150),('MISSING_PULSE',150),('PERIOD',150),('UNKNOWN',100)]:
 n=0
 for attempt in range(750000):
  p=rng.randint(5,16)
  if lab=='UNKNOWN':
   bits=[0]*64;starts=[rng.randrange(1,25),rng.randrange(30,55)]if rng.random()<.65 else[rng.randrange(1,52)]
   for t in starts:
    for j in range(t,min(64,t+rng.randint(1,10))):bits[j]=1
   c=dict(samples=bits,label=lab,answer=CODES[lab],**summarize(bits,p))
  else:
   c=make_case(rng,p,lab);g=c['gaps']
   if len(g)<2:continue
   if lab=='NORMAL'and any(x*100<p*75 or x*100>p*125 for x in g):continue
   if lab=='MISSING_PULSE'and not any(x*100>=p*160 for x in g):continue
   if lab=='PERIOD'and(not any(x*100<p*75 or x*100>p*125 for x in g)or any(x*100>=p*160 for x in g)):continue
  if c['prompt']in seen or len(tok.encode(c['prompt']))>=63:continue
  c.update(id=f'r14-unseen-{lab}-{n:04d}',label_origin='New synthetic generator event, frozen before r14 training');test.append(c);seen.add(c['prompt']);n+=1
  if n==target:break
 assert n==target,(lab,n)
 print('FROZEN NEW TEST',lab,n,flush=True)
rng.shuffle(train)
for n,cs in [('train',train),('validation',val),('test',test),('anchors',anchors),('r13_test_regression',oldtest)]:
 (R/'data'/f'{n}.jsonl').write_text(''.join(json.dumps(c)+'\n'for c in cs),encoding='utf-8')
 with(R/'data'/f'{n}_probe.txt').open('w',encoding='ascii')as f:
  for c in cs:
   ids=tok.encode(c['prompt']);f.write(f"{c['id']} {len(ids)} {codeids[c['answer']]} "+' '.join(map(str,ids))+'\n')
manifest=dict(synthetic_only=True,train_rows=len(train),validation_rows=len(val),test_rows=len(test),startup_anchor_cases=len(anchors),constant_and_startup_anchors_excluded_from_unseen_accuracy=True,new_test_disjoint_from_all_r13_train_validation_test_and_historical_evaluation=True,test_frozen_before_training=True,test_used_for_selection=False,limits='Start-settling STUCK classes cover <=4 initial inverse samples followed by >=60 stable samples; trained regression anchors, not independent accuracy samples',case_files_sha256={n:hashlib.sha256((R/'data'/f'{n}.jsonl').read_bytes()).hexdigest()for n in ['train','validation','test','anchors','r13_test_regression']})
(R/'data/manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
rows=pack(train,tok,codeids);vr=pack(val,tok,codeids);ar=pack(anchors,tok,codeids);tr=pack(test,tok,codeids)
model=Transformer(ModelArgs(dim=64,hidden_dim=172,n_layers=5,n_heads=8,n_kv_heads=4,vocab_size=512,multiple_of=4,max_seq_len=64,dropout=0));start=np.load(R/'artifacts/start_weights.npz',allow_pickle=False);model.load_state_dict({k:torch.from_numpy(start[k].copy())for k in start.files})
def ev(cs,rs):
 d=evaluate(model,cs,rs,codeids);d.pop('predictions');return d
report=dict(stage='TRAINING',reason='r13 actual board stuck-high capture is 0 followed by 63 highs; synthetic exact-constant anchors omitted startup transient',architecture_unchanged=True,firmware_runtime_unchanged=True,history=[],test_used_for_selection=False);print('BEFORE',ev(anchors,ar)['accuracy'],flush=True)
groups=[[i for i,c in enumerate(train)if c['label']==lab]for lab in LABELS];nr=np.random.default_rng(3014);opt=torch.optim.AdamW(model.parameters(),lr=1e-4,weight_decay=.005);best=(-1,-1);beststate=None;t0=time.perf_counter();steps=1200
for step in range(1,steps+1):
 model.train();inds=[int(nr.choice(g))for g in groups for _ in range(8)];nr.shuffle(inds);x,y=batch(rows,inds);opt.zero_grad(set_to_none=True);model(x,y);loss=model.last_loss;loss.backward();torch.nn.utils.clip_grad_norm_(model.parameters(),1);opt.step()
 if step==1 or step%100==0:
  v=ev(val,vr);a=ev(anchors,ar);key=(a['accuracy'],v['accuracy']);row=dict(step=step,loss=float(loss),validation_accuracy=v['accuracy'],startup_anchor_accuracy=a['accuracy']);report['history'].append(row);print(json.dumps(row),flush=True)
  if key>best:best=key;beststate=copy.deepcopy(model.state_dict());report['best_step']=step
model.load_state_dict(beststate);model.eval();report.update(validation=ev(val,vr),anchors=ev(anchors,ar),test=ev(test,tr),seconds=time.perf_counter()-t0,export=export_weights(model,R/'artifacts',context=64))
# Same Q4 layout and quantizer as audited r13; no changes to deployed math.
s=(S/'train_clean.py').read_text(encoding='utf-8');code=s[s.index('# Direct Q4 export'):s.index("report.update(stage=")];exec(code)
report.update(stage='R14_TRAINED_AWAITING_C_VALIDATION',q4_sha256=hashlib.sha256((R/'artifacts/diagnostic_q4.bin').read_bytes()).hexdigest(),model_bytes=(R/'artifacts/diagnostic_q4.bin').stat().st_size)
(R/'reports/training_report.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print('DONE',report['best_step'],report['test']['accuracy'],report['anchors']['accuracy'],flush=True)
