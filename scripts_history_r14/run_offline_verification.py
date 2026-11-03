from pathlib import Path
import argparse,os,subprocess,sys,json,time,shutil
sys.stdout.reconfigure(encoding='utf-8');os.environ['PYTHONIOENCODING']='utf-8'
R=Path(__file__).resolve().parents[1];p=argparse.ArgumentParser();p.add_argument('--tools',type=Path,default=Path('F:/脑机项目/guanweixin_demo_v01/tools'));a=p.parse_args();iv=a.tools/'iverilog/app/bin/iverilog.exe';gcc=next((a.tools/'riscv').glob('*/bin/riscv-none-elf-gcc.exe'));node=shutil.which('node');assert iv.is_file()and gcc.is_file()and node
os.environ['GWX_IVERILOG']=str(iv);os.environ['GWX_GCC']=str(gcc);out=R/'verification_fresh';out.mkdir(exist_ok=True);steps=[];resume=os.environ.get('GWX_RESUME_FROM','');previous=json.loads((out/'suite_status.json').read_text())['steps'] if resume else [];started=not bool(resume)
def run(name,cmd,cwd=R,timeout=600):
 global started
 if not started and name!=resume:
  old=next(x for x in previous if x['name']==name);assert old['exit_code']==0;steps.append(old);print('REUSE UNCHANGED PASS',name,flush=True);return
 started=True
 print('START',name,flush=True);t=time.monotonic()
 r=subprocess.run(list(map(str,cmd)),cwd=cwd,capture_output=True,timeout=timeout)
 (out/(name+'.log')).write_bytes(r.stdout+r.stderr)
 steps.append(dict(name=name,exit_code=r.returncode,seconds=time.monotonic()-t));(out/'suite_status.json').write_text(json.dumps(dict(all_pass=False,steps=steps),indent=2))
 if r.returncode:print((r.stdout+r.stderr).decode('utf-8',errors='replace')[-3500:],flush=True);r.check_returncode()
 print('PASS',name,round(time.monotonic()-t,2),flush=True)
run('cpu_reference',[sys.executable,'-B',R/'offline_tests/test_legacy_cpu.py','--variant','candidate'])
run('return_stack',[sys.executable,'-B',R/'offline_tests/test_ras_only.py','--variant','candidate','--suffix','_ras'])
run('exceptions_interrupts',[sys.executable,'-B',R/'offline_tests/test_machine_r05_20261030.py'])
run('q4_accelerator',[sys.executable,'-B',R/'offline_tests/test_buffered_dot.py'])
for seed in(1,12345,87654321):
 v=out/f'cache_{seed}.vvp';run(f'cache_compile_{seed}',[iv,'-g2012','-s','tb_cache_2way',f'-Ptb_cache_2way.SEED={seed}','-o',v,R/'candidate/gwx_cache_2way.v',R/'sim/tb_cache_fast.v'])
 run(f'cache_run_{seed}',[iv.with_name('vvp.exe'),v],cwd=out)
run('web_runtime2',[sys.executable,'-B',R/'offline_tests/test_web_v2.py'])
run('web_ai_boundaries',[sys.executable,'-B','-m','unittest','test_ai_workbench'],cwd=R/'host')
run('web_http_ui',[sys.executable,'-B',R/'host/test_instrument_web.py',R/'fixtures/boot33.txt','--node',node])
run('web_serial_recovery',[sys.executable,'-B',R/'host/test_serial_worker.py',R/'fixtures/boot33.txt'])
run('web_history_search',[sys.executable,'-B',R/'host/test_studio_search.py',R/'fixtures/boot33.txt'])
(out/'suite_status.json').write_text(json.dumps(dict(all_pass=True,physical_board_accessed=False,steps=steps),indent=2));print('ALL OFFLINE VERIFICATION PASS',flush=True)
