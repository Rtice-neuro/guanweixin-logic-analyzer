from pathlib import Path
import argparse,hashlib,json,shutil,subprocess
ROOT=Path(__file__).resolve().parents[1]
PROJECT=ROOT
ap=argparse.ArgumentParser();ap.add_argument('variant',choices=['candidate','baseline']);ap.add_argument('--compiler',required=True);a=ap.parse_args()
case=ROOT/a.variant;ROOT_SOURCE=case/'firmware_source';work=case/'firmware';work.mkdir(exist_ok=True)
compiler=Path(a.compiler)
vendor=PROJECT/'third_party/coremark'
for name in ('core_list_join.c','core_main.c','core_matrix.c','core_state.c','core_util.c','coremark.h'):shutil.copy2(vendor/name,work/name)
for name in ('core_portme.h','ee_printf.c'):shutil.copy2(PROJECT/'coremark_port'/name,work/name)
shutil.copy2(PROJECT/'coremark_port/core_portme.c',work/'core_portme.c')
isa='rv32i_zmmul_zicsr'
base=[f'-march={isa}','-mabi=ilp32','-mno-relax','-ffreestanding','-fno-builtin','-fno-pic','-fno-stack-protector','-msmall-data-limit=0','-ffunction-sections','-fdata-sections','-nostdlib','-Wall','-Wextra','-Wno-misleading-indentation',
 '-I.', '-I'+str(ROOT_SOURCE),'-DCLOCK_HZ=27000000','-DITERATIONS=0','-DTOTAL_DATA_SIZE=2000',f'-DFLAGS_STR="CoreMark -O2; app -Os; {isa}; 64KiB RAM"']
objects=[]
with (ROOT/'verification'/f'{a.variant}_firmware_build.log').open('wb')as log:
 for path in [*(ROOT_SOURCE/n for n in ('start.S','trap_entry.S','machine_runtime.c','zmmul_runtime.S','instrument.c','ai_application.c','gwx_ai.c','freestanding.c')),*(work/n for n in ('core_list_join.c','core_matrix.c','core_state.c','core_util.c','core_portme.c','ee_printf.c','core_main.c'))]:
  if a.variant=='baseline' and path.name=='zmmul_runtime.S':continue
  flags=['-O2']if path.name.startswith('core_')else['-Os']
  if path.name=='core_main.c':flags+=['-Dmain=gwx_coremark_run']
  obj=work/(path.stem+'.o');objects.append(obj)
  subprocess.run([str(compiler),*base,*flags,'-c',str(path),'-o',str(obj)],cwd=work,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=60)
 runtime=compiler.parent.parent/'lib/gcc/riscv-none-elf/15.2.0/rv32i/ilp32/libgcc.a'
 subprocess.run([str(compiler),*base,'-Wl,--no-relax','-Wl,--build-id=none','-Wl,--gc-sections','-T',str(ROOT_SOURCE/'memory.ld'),*map(str,objects),str(runtime),'-Wl,-Map=app.map','-o','app.elf'],cwd=work,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=60)
 subprocess.run([str(compiler.with_name('riscv-none-elf-objcopy.exe')),'-O','binary','app.elf','app.bin'],cwd=work,stdout=log,stderr=subprocess.STDOUT,check=True)
blob=(work/'app.bin').read_bytes();assert len(blob)<=49152,len(blob)
blob+=bytes(-len(blob)%4);words=[f'{int.from_bytes(blob[i:i+4],"little"):08x}'for i in range(0,len(blob),4)]+['ffffffff']*((49152-len(blob))//4)
(case/'program.hex').write_text('\n'.join(words)+'\n',encoding='ascii')
for i in range(24):(case/'rom_banks'/f'program_{i:02d}.hex').write_text('\n'.join(words[i*512:(i+1)*512])+'\n',encoding='ascii')
report=dict(isa=isa,firmware_bytes=len(blob),coremark_flags='-O2',application_flags='-Os',hardware_multiplier=isa!='rv32i',firmware_sha256=hashlib.sha256((case/'program.hex').read_bytes()).hexdigest(),model_sha256=hashlib.sha256((ROOT/"model.bin").read_bytes()).hexdigest(),algorithm_sources_unmodified=all((vendor/n).read_bytes()==(work/n).read_bytes()for n in ('core_list_join.c','core_main.c','core_matrix.c','core_state.c','core_util.c')))
(case/'firmware_manifest.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report),flush=True)

# Keep the portable PDS ROM image synchronized after a firmware rebuild.
if a.variant=="candidate":
 for f in (case/"rom_banks").glob("program_*.hex"):shutil.copy2(f,ROOT/"pds/rom_banks"/f.name)
