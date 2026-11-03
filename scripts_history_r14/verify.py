"""Build, simulate, compare instruction retirement against a Python RV32I model.
All generated files remain inside this project. No external upload is performed.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
import firmware

ROOT=Path(__file__).resolve().parents[1]
RESULTS=ROOT/'results'
MASK=0xffffffff
def signed(n,bits=32):
    n &= (1<<bits)-1
    return n-(1<<bits) if n & (1<<(bits-1)) else n

def reference(words):
    regs=[0]*32; memory=bytearray(1024); pc=0; trace=[]; writes=0
    for _ in range(30000):
        insn=words[pc//4] if pc%4==0 and pc//4<len(words) else MASK
        op=insn&127; rd=(insn>>7)&31; f=(insn>>12)&7
        a=regs[(insn>>15)&31]; b=regs[(insn>>20)&31]; f7=insn>>25
        imm=signed(insn>>20,12); next_pc=(pc+4)&MASK
        out=None; trap=None
        if op==0x37: out=insn&0xfffff000
        elif op==0x17: out=pc+(insn&0xfffff000)
        elif op in [0x13,0x33]:
            rhs=imm&MASK if op==0x13 else b
            if op==0x33 and not(f7==0 or (f7==32 and f in [0,5])): trap=2
            elif op==0x13 and f==1 and f7!=0: trap=2
            elif op==0x13 and f==5 and f7 not in [0,32]: trap=2
            elif f==0: out=a-rhs if op==0x33 and f7==32 else a+rhs
            elif f==1: out=a<<(rhs&31)
            elif f==2: out=int(signed(a)<signed(rhs))
            elif f==3: out=int(a<rhs)
            elif f==4: out=a^rhs
            elif f==5: out=signed(a)>>(rhs&31) if f7==32 else a>>(rhs&31)
            elif f==6: out=a|rhs
            elif f==7: out=a&rhs
        elif op==0x6f:
            offset=((insn>>31)<<20)|(((insn>>12)&255)<<12)|(((insn>>20)&1)<<11)|(((insn>>21)&1023)<<1)
            next_pc=(pc+signed(offset,21))&MASK; out=pc+4
            if next_pc%4: trap=0
        elif op==0x67:
            if f: trap=2
            else:
                next_pc=((a+imm)&MASK)&~1; out=pc+4
                if next_pc%4: trap=0
        elif op==0x63:
            conditions={0:a==b,1:a!=b,4:signed(a)<signed(b),5:signed(a)>=signed(b),6:a<b,7:a>=b}
            if f not in conditions: trap=2
            elif conditions[f]:
                offset=((insn>>31)<<12)|(((insn>>7)&1)<<11)|(((insn>>25)&63)<<5)|(((insn>>8)&15)<<1)
                next_pc=(pc+signed(offset,13))&MASK
                if next_pc%4: trap=0
        elif op in [3,0x23]:
            store=op==0x23
            offset=signed(((insn>>25)<<5)|((insn>>7)&31),12) if store else imm
            address=(a+offset)&MASK
            if f not in ([0,1,2] if store else [0,1,2,4,5]): trap=2
            else:
                width=1<<(f&3)
                if address%width: trap=6 if store else 4
                elif not(0x10000000<=address and address+width<=0x10000400): trap=7 if store else 5
                else:
                    index=address-0x10000000
                    if store:
                        memory[index:index+width]=(b&((1<<(width*8))-1)).to_bytes(width,'little'); writes+=1
                    else:
                        out=int.from_bytes(memory[index:index+width],'little',signed=f in [0,1])
        elif op==0x0f:
            if f: trap=2
        elif op==0x73: trap=3 if insn==0x00100073 else 11 if insn==0x00000073 else 2
        else: trap=2
        if trap is not None: return trace,trap,writes
        if out is not None and rd: regs[rd]=out&MASK
        trace.append((pc,insn,int(out is not None and rd!=0),rd,(out or 0)&MASK))
        regs[0]=0; pc=next_pc
    raise AssertionError('reference exceeded instruction limit')

def find_tools(override=None):
    candidates=[Path(override)] if override else []
    candidates += [ROOT/'tools/iverilog/app/bin']
    executable=shutil.which('iverilog')
    if executable: candidates.append(Path(executable).parent)
    for folder in candidates:
        suffix='.exe' if os.name=='nt' else ''
        if (folder/('iverilog'+suffix)).exists() and (folder/('vvp'+suffix)).exists():
            return folder/('iverilog'+suffix),folder/('vvp'+suffix)
    raise SystemExit('Icarus not found. Pass --iverilog-dir PATH or add iverilog/vvp to PATH.')

def run(command,cwd,log):
    proc=subprocess.run([str(x) for x in command],cwd=cwd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=90)
    output=proc.stdout.decode('utf-8',errors='replace')
    log.write_text(output,encoding='utf-8')
    if proc.returncode: raise RuntimeError(f'{command[0]} failed ({proc.returncode}):\n{output}')
    return output

def bundle():
    folder=ROOT/'upload'; folder.mkdir(exist_ok=True)
    names=['gwx_core.v','gwx_uart_tx.v','gwx_capture.v','gwx_rom.v','gwx_soc.v','top.v']
    text='// GUANWEIXIN v0.1. Generated from rtl/. Upload ONLY this design file.\n'
    text+='\n'.join((ROOT/'rtl'/name).read_text(encoding='utf-8') for name in names)
    (folder/'guanweixin_top.v').write_text(text,encoding='utf-8')

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--iverilog-dir'); args=parser.parse_args()
    RESULTS.mkdir(exist_ok=True); firmware.build(); bundle()
    iv,vvp=find_tools(args.iverilog_dir)
    version=run([iv,'-V'],ROOT,RESULTS/'tool_version.log').splitlines()[0]
    design=ROOT/'upload/guanweixin_top.v'
    checks=[]
    for name,cpb in [('fast',8),('50mhz_uart',434),('27mhz_uart',234)]:
        folder=RESULTS/('demo_'+name); folder.mkdir(exist_ok=True)
        run([iv,'-g2012','-Wall','-s','tb_demo',f'-Ptb_demo.CPB={cpb}','-o','demo.vvp',design,ROOT/'sim/tb_demo.v'],folder,folder/'compile.log')
        output=run([vvp,'demo.vvp'],folder,folder/'simulation.log')
        # Text-mode $fwrite on Windows may translate LF to CRLF. RTL pin bytes are checked by TB.
        checks.append({'test':'demo_'+name,'clocks_per_bit':cpb,'pass':True,'summary':output[output.index('PASS DEMO:'):].splitlines()[:3]})
        print('PASS demo',name)
    folder=RESULTS/'cpu'; folder.mkdir(exist_ok=True)
    run([iv,'-g2012','-Wall','-s','tb_core','-o',folder/'core.vvp',ROOT/'rtl/gwx_core.v',ROOT/'sim/tb_core.v'],ROOT,folder/'compile.log')
    tests=json.loads((ROOT/'firmware/tests.json').read_text())
    for name,meta in tests.items():
        words=[int(x,16) for x in (ROOT/'firmware'/f'{name}.hex').read_text().splitlines()]
        expected,trap,writes=reference(words)
        assert trap==meta['trap'],(name,trap,meta)
        for seed in [1,12345,87654321]:
            work=folder/f'{name}_seed{seed}'; work.mkdir(exist_ok=True)
            shutil.copy2(ROOT/'firmware'/(name+'.hex'),work/'program.hex')
            output=run([vvp,folder/'core.vvp','+HEX=program.hex',f'+TRAP={trap}',f'+SEED={seed}'],work,work/'simulation.log')
            actual=[]
            for line in (work/'core_trace.csv').read_text().splitlines():
                row=line.split(','); actual.append((int(row[0],16),int(row[1],16),int(row[2]),int(row[3]),int(row[4],16)))
            assert len(actual)==len(expected),(name,seed,'trace length',len(actual),len(expected))
            for i,(got,want) in enumerate(zip(actual,expected)):
                assert got[:3]==want[:3] and (not want[2] or got[3:]==want[3:]),(name,seed,i,got,want)
            measured_writes=int(re.search(r'writes=(\d+)',output).group(1))
            assert measured_writes==writes,(name,'duplicate/missing stores',measured_writes,writes)
            checks.append({'test':name,'memory_seed':seed,'retired_compared':len(actual),'stores':writes,'trap':trap,'pass':True})
        print('PASS CPU',name, 'retirements:',len(expected),'x 3 latency seeds')
    folder=RESULTS/'board_wrapper'; folder.mkdir(exist_ok=True)
    run([iv,'-g2012','-Wall','-s','tb_top','-o','top.vvp',design,ROOT/'sim/tb_top.v'],folder,folder/'compile.log')
    output=run([vvp,'top.vvp'],folder,folder/'simulation.log'); print(output.strip())
    checks.append({'test':'board_wrapper_reset_repeat','pass':True})
    summary={'generated':datetime.now().astimezone().isoformat(),'tool':version,
             'design_sha256':hashlib.sha256(design.read_bytes()).hexdigest(),
             'check_count':len(checks),'all_pass':True,'checks':checks,
             'scope':'RTL simulation and independent Python retirement comparison; no PDS place/route or remote board execution.'}
    (RESULTS/'verification.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('ALL PASS:',len(checks),'checks; results/verification.json')

if __name__=='__main__': main()
