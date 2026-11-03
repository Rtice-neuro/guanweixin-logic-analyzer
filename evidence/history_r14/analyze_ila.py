from pathlib import Path
import json,re,csv,subprocess,bisect,hashlib,sys
sys.stdout.reconfigure(encoding='utf-8')
P=Path('F:/脑机项目/guanweixin_demo_v01');O=P/'submission/观微芯_AI精度优化_20261030_r14';E=P/'development/ai_accuracy_20261030_r14/reports/board';W=Path('F:/FPGA_Work/gwx_ai_r14')
vcd=W/'coremark_r14.vcd';elf=O/'candidate/firmware/app.elf';obj=P/'tools/riscv/xpack-riscv-none-elf-gcc-15.2.0-1/bin/riscv-none-elf-objdump.exe'
dis=subprocess.check_output([str(obj),'-d',str(elf)],text=True,encoding='gbk',errors='replace');(E/'firmware_disassembly.txt').write_text(dis,encoding='utf-8')
ins={};sym=[]
for l in dis.splitlines():
 m=re.match(r'^([0-9a-f]+) <([^>]+)>:',l)
 if m:sym.append((int(m[1],16),m[2]))
 m=re.match(r'^\s*([0-9a-f]+):\s+([0-9a-f]{8})\s+(.*)',l)
 if m:ins[int(m[1],16)]=(int(m[2],16),m[3])
sym.sort();starts=[a for a,b in sym];bits={};stamp=None;snaps=[]
for l in vcd.read_text(encoding='utf-8').splitlines():
 if re.fullmatch(r'#\d+',l):
  if stamp is not None:snaps.append((stamp,bits.copy()))
  stamp=int(l[1:])
 else:
  m=re.fullmatch(r'([01])n(\d+)',l)
  if m and int(m[2])<112:bits[int(m[2])]=int(m[1])
if stamp is not None:snaps.append((stamp,bits.copy()))
assert len(snaps)==512 and all(len(b)==112 for _,b in snaps)
rows=[];mismatches=[];functions={}
for n,(t,b)in enumerate(snaps):
 def word(a,z):return sum(b[i]<<(i-a)for i in range(a,z))
 pc=word(0,32);i=word(32,64);idx=bisect.bisect_right(starts,pc)-1;fn=sym[idx][1]if idx>=0 else '?';valid=b[96]
 if valid:
  functions[fn]=functions.get(fn,0)+1
  if pc not in ins or ins[pc][0]!=i:mismatches.append(dict(sample=n,pc=hex(pc),captured=hex(i),elf=hex(ins[pc][0])if pc in ins else None))
 rows.append(dict(sample=n,export_timestamp=t,pc=f'{pc:08x}',instruction=f'{i:08x}',cycle=word(64,96),retire_valid=valid,write=b[97],flush=b[98],forward=b[99],waiting=b[100],f_valid=b[101],x_valid=b[102],m_valid=b[103],source8=f'{word(104,112):02x}',function=fn,assembly=ins.get(pc,('', '?'))[1]))
with(E/'ila_decoded.csv').open('w',encoding='utf-8',newline='')as f:w=csv.DictWriter(f,fieldnames=rows[0].keys());w.writeheader();w.writerows(rows)
retired=sum(r['retire_valid']for r in rows)
a=dict(capture_time='2026-10-30T18:12:26+08:00',scope='r14 CoreMark performance run, real FPGA PDS ILA',samples=len(rows),data_bits=112,retire_valid=retired,firmware_instruction_matches=retired-len(mismatches),mismatches=mismatches,functions=functions,local_ipc=retired/len(rows),forward_cycles=sum(r['forward']for r in rows),flush_cycles=sum(r['flush']for r in rows),waiting_cycles=sum(r['waiting']for r in rows),cycle_counter_contiguous=all((rows[i]['cycle']-rows[i-1]['cycle'])&0xffffffff==1 for i in range(1,len(rows))),vcd_export_timescale_is_not_clock_calibration=True,elf_sha256=hashlib.sha256(elf.read_bytes()).hexdigest(),vcd_sha256=hashlib.sha256(vcd.read_bytes()).hexdigest(),not_whole_coremark_average=True)
(E/'ila_analysis.json').write_text(json.dumps(a,ensure_ascii=False,indent=2),encoding='utf-8');assert retired>0 and not mismatches;print(json.dumps(a,ensure_ascii=False,indent=2))
