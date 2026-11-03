from pathlib import Path
import sys,json,struct,hashlib,numpy as np,torch
sys.stdout.reconfigure(encoding='utf-8');R=Path('F:/脑机项目/guanweixin_demo_v01/development/ai_accuracy_20261030_r14');S=R/'reference_r13';sys.path.insert(0,str(R/'training'));from third_party.model import Transformer,ModelArgs
from llm_io import Tokenizer
from train_diagnostic import pack,evaluate
torch.set_num_threads(4);tok=Tokenizer(R/'training/pretrained/tok512.bin');codeids={c:tok.index[c]for c in 'ABCDEF'};model=Transformer(ModelArgs(dim=64,hidden_dim=172,n_layers=5,n_heads=8,n_kv_heads=4,vocab_size=512,multiple_of=4,max_seq_len=64,dropout=0));w=np.load(R/'artifacts/diagnostic_weights.npz',allow_pickle=False);model.load_state_dict({k:torch.from_numpy(w[k].copy())for k in w.files});model.eval()
report=dict(stage='R14_SELECTED_CHECKPOINT_RECOVERED_AFTER_Q4_EXPORT_IMPORT_ERROR',best_step=100,training_steps=1200,selection='first checkpoint with 10/10 startup regression anchors and 550/550 validation; test not used for selection',architecture_unchanged=True,firmware_runtime_unchanged=True,export_error='missing struct import; FP32 selected weights had already been exported intact',test_used_for_selection=False)
for n in ['validation','anchors','test']:
 cs=[json.loads(l)for l in(R/'data'/f'{n}.jsonl').read_text(encoding='utf-8').splitlines()];d=evaluate(model,cs,pack(cs,tok,codeids),codeids);d.pop('predictions');report[n]=d
s=(S/'train_clean.py').read_text(encoding='utf-8');exec(s[s.index('# Direct Q4 export'):s.index("report.update(stage=")]);report.update(q4_sha256=hashlib.sha256((R/'artifacts/diagnostic_q4.bin').read_bytes()).hexdigest(),model_bytes=(R/'artifacts/diagnostic_q4.bin').stat().st_size)
(R/'reports/training_report.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report,indent=2))
