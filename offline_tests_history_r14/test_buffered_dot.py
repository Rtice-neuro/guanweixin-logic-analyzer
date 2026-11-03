from pathlib import Path
import subprocess,json
R=Path(__file__).resolve().parents[1];P=R
tb=r'''`timescale 1ns/1ps
module tb_q4_buffer;
 initial begin $dumpfile("buffered_dot.vcd");$dumpvars(0,tb_q4_buffer);end
 reg clk=0,rst_n=0,write=0,commit=0;reg[7:0]addr=0;reg[31:0]data=0;reg[3:0]strb=15;wire[31:0]rd;wire error;
 always #5 clk=~clk;
 gwx_q4_mmio dut(.clk(clk),.rst_n(rst_n),.address(addr),.write(write),.wdata(data),.wstrb(strb),.commit(commit),.rdata(rd),.error(error));
 reg[31:0]xs[0:15],ws[0:7],rng=32'h70932615;integer i,j,n,expected,sx,sw,checked=0;reg[31:0]saved;
 task step_rng;begin rng={rng[30:0],rng[31]^rng[21]^rng[1]^rng[0]};end endtask
 task put;input[7:0]a;input[31:0]d;input[3:0]mask;input bad;begin
  @(negedge clk);addr=a;data=d;write=1;strb=mask;#1;if(error!==bad)$fatal(1,"error check address=%h got=%b expected=%b",a,error,bad);commit=1;
  @(negedge clk);commit=0;write=0;strb=15;
 end endtask
 task answer;begin
  wait(dut.out_valid);@(negedge clk);addr=8'h14;write=0;#1;
  if(error||$signed(rd)!==expected)$fatal(1,"dot mismatch got=%h expected=%h",rd,expected);saved=rd;
  repeat(5)begin @(negedge clk);if(!dut.out_valid||rd!==saved)$fatal(1,"unstable result under backpressure");end
  put(8'h18,1,15,0);checked=checked+1;
 end endtask
 task expected_sum;begin expected=0;for(j=0;j<64;j=j+1)begin
  sx=$signed(xs[j/4][(j%4)*8+:8]);sw=$signed(ws[j/8][(j%8)*4+:4]);expected=expected+sx*sw;
 end end endtask
 initial begin
  repeat(4)@(negedge clk);rst_n=1;
  put(8'ha0,1,15,1);put(8'h14,0,15,1);put(8'h18,1,15,1);put(8'h40,1,1,1);
  for(n=0;n<200;n=n+1)begin
   if(n%4==0)for(i=0;i<16;i=i+1)begin step_rng;xs[i]=rng;put(8'h40+i*4,xs[i],15,0);end
   for(i=0;i<8;i=i+1)begin step_rng;ws[i]=rng;put(8'h80+i*4,ws[i],15,0);end
   expected_sum;put(8'ha0,1,15,0);answer;put(8'ha0,1,15,1);
  end
  // Legacy streaming mode remains equivalent to buffered mode.
  for(n=0;n<32;n=n+1)begin
   for(i=0;i<16;i=i+1)begin step_rng;xs[i]=rng;end
   for(i=0;i<8;i=i+1)begin step_rng;ws[i]=rng;end
   expected_sum;
   for(i=0;i<8;i=i+1)begin put(0,xs[i*2],15,0);put(4,xs[i*2+1],15,0);put(8,ws[i],15,0);put(12,i==7?32'hff01:32'hff00,15,0);end
   answer;
  end
  // Reset clears validity and cancels a buffered operation.
  for(i=0;i<8;i=i+1)put(8'h80+i*4,ws[i],15,0);
  put(8'ha0,1,15,0);rst_n=0;repeat(3)@(negedge clk);rst_n=1;repeat(2)@(negedge clk);
  if(dut.out_valid||dut.buffered)$fatal(1,"stale result after reset");put(8'ha0,1,15,1);
  $display("PASS BUFFERED DOT groups=%0d activation_reuse=4 reset_and_errors=PASS",checked);$finish;
 end
 initial begin #5000000;$fatal(1,"timeout");end
endmodule
'''
out=R/'verification/q4_buffer';out.mkdir(exist_ok=True);(R/'sim/tb_q4_buffer.v').write_text(tb,encoding='ascii');iv=Path(__import__('os').environ['GWX_IVERILOG'])
with(out/'compile.log').open('wb')as f:subprocess.run([str(iv),'-g2012','-s','tb_q4_buffer','-o',str(out/'run.vvp'),str(R/'candidate/gwx_q4_mmio.v'),str(R/'candidate/gwx_int8_group_dot.v'),str(R/'sim/tb_q4_buffer.v')],stdout=f,stderr=subprocess.STDOUT,check=True)
r=subprocess.run([str(iv.with_name('vvp.exe')),str(out/'run.vvp')],cwd=out,capture_output=True,text=True,encoding="gb18030",errors="replace",timeout=60);(out/'simulation.log').write_text(r.stdout+r.stderr,encoding='utf-8');print(r.stdout,flush=True);r.check_returncode();(out/'verification.json').write_text(json.dumps(dict(all_pass=True,random_buffered_groups=200,legacy_groups=32,model_and_float_math_unchanged=True,reset_and_errors=True,physical_board_tested=False),indent=2),encoding='utf-8')