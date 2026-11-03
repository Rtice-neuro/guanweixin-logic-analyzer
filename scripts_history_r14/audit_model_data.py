from pathlib import Path
import json,hashlib,zlib,re,sys
sys.stdout.reconfigure(encoding="utf-8");P=Path(__file__).resolve().parents[1];R=P/"training/accuracy_r14"
def load(p):return json.loads(p.read_text(encoding="utf-8"))
def rows(p):return [json.loads(l)for l in p.read_text(encoding="utf-8").splitlines()]
m=load(R/"data/manifest.json");c=load(R/"reports/c_validation.json");sets={n:{r["prompt"]for r in rows(R/"data"/(n+".jsonl"))}for n in ("train","validation","test")};inter={a+"/"+b:len(sets[a]&sets[b])for a,b in (("train","validation"),("train","test"),("validation","test"))};assert not any(inter.values())
labels={}
for r in rows(R/"data/train.jsonl"):labels.setdefault(r["prompt"],set()).add(r["answer"])
conflicts=sum(len(v)>1 for v in labels.values());assert conflicts==0
for n,h in m["case_files_sha256"].items():assert hashlib.sha256((R/"data"/(n+".jsonl")).read_bytes()).hexdigest()==h
prior=set()
for n in ("train","validation","test"):prior|={r["prompt"]for r in rows(R/"reference_r13/data"/(n+".jsonl"))}
assert not(sets["test"]&prior)
b=(P/"model.bin").read_bytes();sha=hashlib.sha256(b).hexdigest();assert sha=="ce27bf8fbc7e9db9faddf6cc9a8bafa9024a306fb8378681b3c4206afaae3ad6"and zlib.crc32(b)==0x2a52a97d
assert(P/"training/artifacts/diagnostic_q4.bin").read_bytes()==b
out=dict(revision="r14",model_sha256=sha,model_crc32="2a52a97d",model_bytes=len(b),prompt_split_intersections=inter,training_conflicts=conflicts,new_test_r13_prompt_overlap=0,quantized_new_synthetic_test=c["diagnostic_q4_test"],quantized_startup_regression=c["diagnostic_q4_anchors"],r13_new_startup_regression=c["baseline_q4_anchors"],prior_r13_test_regression=c["diagnostic_q4_r13_test_regression"],test_used_for_selection=False,synthetic_only=True,external_measurements=False,trained_constant_and_settling_anchors_excluded_from_independent_accuracy=True,score_is_calibrated_probability=False)
(P/"verification_fresh/model_data_audit.json").write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8");print(json.dumps(out,ensure_ascii=False,indent=2))
