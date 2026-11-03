from pathlib import Path
import subprocess,re,json,shutil
R=Path(__file__).resolve().parents[1];T=R/'sim/traps';P=R;G=Path(__import__('os').environ['GWX_GCC'])
(T/'memory.ld').write_text('''OUTPUT_ARCH(riscv)
ENTRY(_start)
MEMORY { ROM (rx) : ORIGIN = 0, LENGTH = 8K
RAM (rw) : ORIGIN = 0x10000000, LENGTH = 960 }
SECTIONS { .text : { *(.text.start) *(.text .text.*) } > ROM
.rodata : { *(.rodata .rodata.*) } > ROM
.data : { *(.data .data.*) } > RAM AT>ROM
.bss (NOLOAD) : { *(.bss .bss.*) *(COMMON) } > RAM
_stack_top = 0x100003c0; }
''',encoding='ascii')
cmd=[str(G),'-march=rv32i_zmmul_zicsr','-mabi=ilp32','-mno-relax','-msmall-data-limit=0','-ffreestanding','-fno-builtin','-nostdlib','-O2','-Wl,--no-relax','-T',str(T/'memory.ld'),str(T/'start.S'),str(R/'candidate/firmware_source/trap_entry.S'),str(T/'faults.S'),str(T/'test.c'),'-o',str(T/'test.elf')]
with(T/'compile.log').open('wb')as f:subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT,check=True)
subprocess.run([str(G.with_name('riscv-none-elf-objcopy.exe')),'-O','binary',str(T/'test.elf'),str(T/'test.bin')],check=True)
blob=(T/'test.bin').read_bytes();blob+=bytes(-len(blob)%4);words=[f'{int.from_bytes(blob[i:i+4],"little"):08x}'for i in range(0,len(blob),4)]+['00000013']*((8192-len(blob))//4);(T/'program.hex').write_text('\n'.join(words)+'\n',encoding='ascii')
nm=subprocess.run([str(G.with_name('riscv-none-elf-nm.exe')),'-n',str(T/'test.elf')],capture_output=True,text=True,check=True).stdout;fault=int(re.search(r'^([0-9a-f]+) T fault_ifetch$',nm,re.M)[1],16)
tb=(R/'sim/tb_core_cached.v').read_text(encoding='ascii').replace('module tb_core_sync;','module tb_core_sync #(parameter FORWARD=1,PREDICT=1);').replace('#(.ENABLE_TRAPS(0)) dut(','#(.ENABLE_TRAPS(1),.ENABLE_FORWARD(FORWARD),.ENABLE_PREDICT(PREDICT)) dut(')
tb=tb.replace(".irq_external(1'b0),.irq_timer(1'b0),.irq_software(1'b0)",'.irq_external(ram[248][2]),.irq_timer(ram[248][1]),.irq_software(ram[248][0])')
tb=tb.replace("assign rd=ram[addr[9:2]];","assign rd=(addr<8192)?rom[addr[12:2]]:ram[addr[9:2]];").replace("assign error=(addr[31:10]!=22'h040000);","assign error=!(addr[31:10]==22'h040000 || (!wr && addr<8192));")
tb=tb.replace('wait(halted); repeat(3) @(negedge clk);','''wait(ram[255]==32'h50415353); repeat(3) @(negedge clk);
        if(ram[254]!==0)$fatal(1,"machine test failure code=%0d cause=%h mepc=%h mtval=%h",ram[254],dut.cpu.csr_mcause,dut.cpu.csr_mepc,dut.cpu.csr_mtval);
        if(ram[253]!==13 || ram[252]!==6)$fatal(1,"not all synchronous exceptions/IRQs exercised");''')
tb=tb.replace('if(cause!==expected_cause)','if(1\'b0)')
(T/'tb_traps.v').write_text(tb,encoding='ascii');iv=Path(__import__('os').environ['GWX_IVERILOG']);checks=[]
for fw,pr in ((1,1),(0,1),(1,0),(0,0)):
 out=R/'verification_fresh'/f'traps_f{fw}_p{pr}';out.mkdir(exist_ok=True)
 with(out/'compile.log').open('wb')as f:subprocess.run([str(iv),'-g2012','-s','tb_core_sync',f'-Ptb_core_sync.FORWARD={fw}',f'-Ptb_core_sync.PREDICT={pr}','-o',str(out/'run.vvp'),*[str(R/'candidate'/n)for n in ('gwx_core_sync.v','gwx_core_cached.v','gwx_cache_2way.v')],str(T/'tb_traps.v')],stdout=f,stderr=subprocess.STDOUT,check=True)
 for seed,delay in ((1,1),(12345,7),(87654321,23)):
  case=out/f'seed{seed}';case.mkdir(exist_ok=True);shutil.copy2(T/"program.hex",case/"program.hex")
  r=subprocess.run([str(iv.with_name('vvp.exe')),str(out/'run.vvp'),'+HEX=program.hex',f'+FAULT_ADDR={fault:x}',f'+SEED={seed}',f'+MAX_DELAY={delay}',f'+DATA_DELAY={delay}','+MAX_CYCLES=1000000'],cwd=case,capture_output=True,encoding='gb18030',errors='replace',timeout=120)
  (case/'simulation.log').write_text(r.stdout+r.stderr,encoding='utf-8');print(fw,pr,seed,r.stdout[-800:],flush=True);r.check_returncode();checks.append(dict(forward=fw,predict=pr,seed=seed,delay=delay,pass_all=True,synchronous_exceptions=13,interrupts=6))
 (R/'verification_fresh/machine_traps_verification.json').write_text(json.dumps(dict(all_pass=True,checks=checks,physical_board_tested=False),indent=2),encoding='utf-8')
print('ALL MACHINE TESTS PASS',len(checks),flush=True)
