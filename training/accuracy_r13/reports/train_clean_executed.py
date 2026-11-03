"""Independent prompt-group split; preserve frozen old model and hardware runtime."""
from pathlib import Path
import sys,json,hashlib,random,time,copy,math,struct,collections
sys.stdout.reconfigure(encoding='utf-8')
R=Path(__file__).resolve().parent;P=R.parents[1];S=P/'submission/观微芯_实板最终复核_20261030_r12';sys.path.insert(0,str(R/'training'))
import numpy as np,torch
from signal_data import summarize,make_case,LABELS,CODES
from llm_io import Tokenizer,export_weights,load_legacy
from third_party.model import Transformer,ModelArgs
from train_diagnostic import pack,batch,evaluate
torch.set_num_threads(4);torch.manual_seed(3013);np.random.seed(3013)
tok=Tokenizer(R/'training/pretrained/tok512.bin');codeids={c:tok.index[c]for c in 'ABCDEF'}
oldtrain=[json.loads(l)for l in(S/'training/data/train.jsonl').read_text(encoding='utf-8').splitlines()];oldprompts={x['prompt']for x in oldtrain};legacy=json.loads((S/'verification/ai_synthetic_evaluation.json').read_text(encoding='utf-8'))['checks'];reserved={c['prompt']for c in legacy}

def sample(rng,label):
 period=rng.randint(5,16)
 if label=='UNKNOWN':
  bits=[0]*64
  # Insufficient periodic evidence: one/two finite pulses, never constant input.
  starts=[rng.randrange(1,25),rng.randrange(30,55)] if rng.random()<.65 else [rng.randrange(1,52)]
  for t in starts:
   for j in range(t,min(64,t+rng.randint(1,10))):bits[j]=1
  return dict(samples=bits,label=label,answer=CODES[label],**summarize(bits,period))
 c=make_case(rng,period,label);g=c['gaps']
 # Reject sampling aliases/overlapping fault definitions; labels remain generator events.
 if len(g)<2:return None
 if label=='NORMAL' and any(x*100<period*75 or x*100>period*125 for x in g):return None
 if label=='PERIOD' and (any(x*100>=period*160 for x in g) or not any(x*100<period*75 or x*100>period*125 for x in g)):return None
 if label=='MISSING_PULSE' and not any(x*100>=period*160 for x in g):return None
 return c

def write_data():
 rng=random.Random(3013001);allrows={s:[]for s in ['train','validation','test']};seen={};counts={};attempts={}
 targets={'NORMAL':(900,150,150),'MISSING_PULSE':(1200,150,150),'PERIOD':(1200,150,150),'UNKNOWN':(350,100,100)}
 for label,target in targets.items():
  count=[0,0,0];attempt=0
  while any(x<t for x,t in zip(count,target))and attempt<350000:
   attempt+=1;c=sample(rng,label)
   if c is None or c['prompt']in seen or c['prompt']in reserved or len(tok.encode(c['prompt']))>=63:continue
   # A prompt belongs to exactly one split, regardless of capture seed/nominal period.
   h=hashlib.sha256(('gwx-r13-group-v1:'+c['prompt']).encode()).digest()[0];k=0 if h<170 else 1 if h<213 else 2
   if c['prompt']in oldprompts:k=0
   if count[k]>=target[k]:continue
   split=['train','validation','test'][k];c['id']=f'{split}-{label}-{count[k]:05d}';c['label_origin']='synthetic generator event with observable-domain alias rejection';allrows[split].append(c);seen[c['prompt']]=c['answer'];count[k]+=1
  counts[label]=count;attempts[label]=attempt;print('CORPUS',label,count,'attempts',attempt,flush=True)
  assert all(x>=t for x,t in zip(count,target)),(label,count,target)
 # Constant captures have only two possible distinct inputs. Treat as canonical regressions.
 anchors=[]
 for label in ['STUCK_HIGH','STUCK_LOW']:
  bits=[int(label=='STUCK_HIGH')]*64;c=dict(samples=bits,label=label,answer=CODES[label],**summarize(bits,8),id='anchor-'+label);anchors.append(c)
  allrows['train'].append(c)
 sets={s:{c['prompt']for c in v}for s,v in allrows.items()};assert not(sets['train']&sets['test']or sets['train']&sets['validation']or sets['test']&sets['validation']);assert not(sets['test']&oldprompts)
 for s,cs in allrows.items():
  rng.shuffle(cs);(R/'data'/f'{s}.jsonl').write_text(''.join(json.dumps(c)+'\n'for c in cs),encoding='utf-8')
 (R/'data/anchors.jsonl').write_text(''.join(json.dumps(c)+'\n'for c in anchors),encoding='utf-8')
 info=dict(synthetic_only=True,targets=targets,counts=counts,attempts=attempts,train_rows=len(allrows['train']),validation_rows=len(allrows['validation']),test_rows=len(allrows['test']),split_policy='SHA256 of exact model prompt group, all splits pairwise disjoint; test excludes old training prompts and historical evaluation prompts',intersection=0,constant_classes='Only two canonical patterns exist; trained anchors and regression checks, excluded from unseen-prompt accuracy',unknown_definition='Insufficient periodic evidence, one/two pulses; no contradiction with known periodic classes',reserved_historical_prompts=len(reserved),test_used_for_selection=False,case_files_sha256={s:hashlib.sha256((R/'data'/f'{s}.jsonl').read_bytes()).hexdigest()for s in allrows})
 (R/'data/manifest.json').write_text(json.dumps(info,indent=2),encoding='utf-8');return allrows,anchors
cases,anchors=write_data();rows={s:pack(cs,tok,codeids)for s,cs in cases.items()};arows=pack(anchors,tok,codeids)
model=Transformer(ModelArgs(dim=64,hidden_dim=172,n_layers=5,n_heads=8,n_kv_heads=4,vocab_size=512,multiple_of=4,max_seq_len=64,dropout=0.0));load_legacy(model,R/'training/pretrained/stories260K.bin');start=np.load(R/'artifacts/start_weights.npz',allow_pickle=False);model.load_state_dict({k:torch.from_numpy(start[k].copy())for k in start.files})
report=dict(stage='TRAINING',seed=3013,architecture_unchanged=True,firmware_runtime_unchanged=True,loss='Response-only LM loss; six balanced training classes; no rule outputs as model input',history=[],test_used_for_selection=False)
def ev(cs,rs):
 d=evaluate(model,cs,rs,codeids);d.pop('predictions');return d
# Validation only drives checkpoint selection. Frozen test is evaluated after checkpoint selection.
report['validation_before']=ev(cases['validation'],rows['validation']);print('VALIDATION BEFORE',report['validation_before']['accuracy'],flush=True)
groups=[[i for i,c in enumerate(cases['train'])if c['label']==l]for l in LABELS];rng=np.random.default_rng(3013);opt=torch.optim.AdamW(model.parameters(),lr=3e-4,weight_decay=.005,betas=(.9,.99));best=-1;beststate=None;t0=time.perf_counter();steps=2200
for step in range(1,steps+1):
 model.train();inds=[int(rng.choice(g))for g in groups for _ in range(8)];rng.shuffle(inds);x,y=batch(rows['train'],inds)
 lr=3e-4*min(1,step/30)*(.2+.8*.5*(1+math.cos(math.pi*step/steps)))
 for g in opt.param_groups:g['lr']=lr
 opt.zero_grad(set_to_none=True);model(x,y);loss=model.last_loss;loss.backward();torch.nn.utils.clip_grad_norm_(model.parameters(),1.0);opt.step()
 if step==1 or step%200==0 or step==steps:
  d=ev(cases['validation'],rows['validation']);a=ev(anchors,arows);item=dict(step=step,loss=float(loss),validation_accuracy=d['accuracy'],anchor_accuracy=a['accuracy'],elapsed=time.perf_counter()-t0);report['history'].append(item);print(json.dumps(item),flush=True)
  with(R/'reports/training.jsonl').open('a',encoding='utf-8')as f:f.write(json.dumps(item)+'\n')
  if(d['accuracy'],a['accuracy'])>(best,report.get('best_anchor',-1)):
   best=d['accuracy'];report['best_anchor']=a['accuracy'];report['best_step']=step;beststate=copy.deepcopy(model.state_dict())
model.load_state_dict(beststate);model.eval();report['validation']=ev(cases['validation'],rows['validation']);report['test']=ev(cases['test'],rows['test']);report['anchors']=ev(anchors,arows);report['export']=export_weights(model,R/'artifacts',context=64)
# Direct Q4 export from FP32 weights with the deployed GWQ4 header/layout.
def arr(t):return t.detach().cpu().numpy().astype('<f4')
norms=[arr(l.attention_norm.weight)for l in model.layers]+[arr(l.ffn_norm.weight)for l in model.layers]+[arr(model.norm.weight)];tensors=[('embedding',arr(model.tok_embeddings.weight))]
for name in ['wq','wk','wv','wo']:
 tensors += [(f'layer{i}.{name}',arr(getattr(l.attention,name).weight))for i,l in enumerate(model.layers)]
for name in ['w1','w2','w3']:
 for i,l in enumerate(model.layers):
  a=arr(getattr(l.feed_forward,name).weight);a=np.pad(a,((0,0),(0,20)))if name=='w2'else np.pad(a,((0,20),(0,0)));tensors.append((f'layer{i}.{name}',a))
q=R/'artifacts/diagnostic_q4.bin'
with q.open('wb')as f:
 header=struct.pack('<8I',0x34515747,64,192,5,8,4,512,64);f.write(header+bytes(256-len(header)))
 for a in norms:f.write(a.tobytes())
 for name,a in tensors:
  a=a.reshape(-1,64);scale=(np.max(np.abs(a),axis=1)/7).astype('<f4');scale=np.where(scale==0,1.,scale).astype('<f4');v=np.rint(a/scale[:,None]).clip(-7,7).astype('i1').reshape(-1);n=v.astype('u1')&15;packed=n[::2]|(n[1::2]<<4);f.write(packed.tobytes());f.write(scale.tobytes())
assert q.stat().st_size==159744
report.update(stage='HOST_TRAINED_Q4_AWAITING_C_VALIDATION',seconds=time.perf_counter()-t0,q4_sha256=hashlib.sha256(q.read_bytes()).hexdigest(),model_bytes=q.stat().st_size)
(R/'reports/training_report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
# Identical locked test tokens for baseline and new model C runtime.
for name,cs in [('test',cases['test']),('validation',cases['validation']),('anchors',anchors)]:
 with(R/'data'/f'{name}_probe.txt').open('w',encoding='ascii')as f:
  for c in cs:
   ts=tok.encode(c['prompt']);f.write(f"{c['id']} {len(ts)} {codeids[c['answer']]} "+' '.join(map(str,ts))+'\n')
print('FINAL FP32',json.dumps(dict(test_accuracy=report['test']['accuracy'],validation_accuracy=report['validation']['accuracy'],anchors=report['anchors']['accuracy'],best_step=report['best_step'],seconds=report['seconds'])),flush=True)
