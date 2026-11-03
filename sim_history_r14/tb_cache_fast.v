`timescale 1ns/1ps
module tb_cache_2way #(parameter SEED=32'h1a2b3c4d);
 reg clk=0,rst_n=0,invalidate=0;
 always #5 clk=~clk;
 reg req_valid=0,req_write=0,req_cacheable=1;
 reg [31:0] req_addr=0,req_wdata=0;reg [3:0] req_wstrb=0;
 wire req_ready,rsp_valid,rsp_error;reg rsp_ready=0;wire[31:0]rsp_data;
 wire mv,mw,mrr;reg mr=0,rv=0,re=0,rl=0;wire[31:0]ma,md;wire[3:0]ms;wire[2:0]ml;
 reg[31:0]rd=0;wire[31:0]hits,misses;
 gwx_cache_2way #(.SET_BITS(2))dut(clk,rst_n,invalidate,req_valid,req_ready,
  req_write,req_cacheable,req_addr,req_wdata,req_wstrb,rsp_valid,rsp_ready,
  rsp_data,rsp_error,mv,mr,mw,ma,md,ms,ml,rv,mrr,rd,re,rl,hits,misses);
 reg[31:0]memory[0:1023],golden[0:1023],rng=SEED;
 reg active=0,cmd_write=0;integer at=0,nbeats=0,index=0,mode=0,fault_mode=0;
 integer sent,got,steps; reg[31:0] expected_queue[0:255];
 integer transactions=0,commands=0,i,j,k,before_count;reg[31:0]last_data;
 reg held=0;reg[71:0]held_command;
 always @(posedge clk)begin
  if(!rst_n)begin active<=0;rv<=0;mr<=0;held<=0;end
  else begin
   rng<={rng[30:0],rng[31]^rng[21]^rng[1]^rng[0]};
   mr<=!active && !rv && rng[2:0]!=0;
   if(held && (!mv || {mw,ma,md,ms,ml}!==held_command))$fatal(1,"unstable backend request");
   held<=mv && !mr;held_command<={mw,ma,md,ms,ml};
   if(mv && mr)begin
    if(active || rv)$fatal(1,"multiple commands outstanding");
    commands<=commands+1;active<=1;at<=ma>>2;index<=0;cmd_write<=mw;mode<=fault_mode;
    nbeats<=mw?1:((fault_mode==2)?2:((fault_mode==3)?5:ml));
    if(mw && fault_mode!=4)for(k=0;k<4;k=k+1)if(ms[k])memory[ma>>2][k*8+:8]<=md[k*8+:8];
   end
   if(active && !rv && rng[4:3]!=0)begin
    rv<=1;rd<=memory[at+index];re<=(mode==1 && index==1)||(mode==4);rl<=index==nbeats-1;
   end
   if(rv && mrr)begin
    rv<=0;
    if(rl)active<=0;else index<=index+1;
   end
  end
 end
 task transaction;
  input writing,cacheable;input[31:0]address,data;input[3:0]strobes;input expected_error;
  reg[31:0]wanted,held_data;reg held_error;integer z;
  begin
   wanted=golden[address>>2];
   @(negedge clk);req_valid=1;req_write=writing;req_cacheable=cacheable;
   req_addr=address;req_wdata=data;req_wstrb=strobes;rsp_ready=0;
   @(posedge clk);while(!req_ready)@(posedge clk);
   @(negedge clk);req_valid=0;
   wait(rsp_valid);@(negedge clk);held_data=rsp_data;held_error=rsp_error;
   if(rsp_error!==expected_error)$fatal(1,"wrong error address=%h got=%b expected=%b",address,rsp_error,expected_error);
   if(!writing && !expected_error && rsp_data!==wanted)$fatal(1,"read mismatch address=%h got=%h wanted=%h",address,rsp_data,wanted);
   repeat(4)begin @(negedge clk);if(!rsp_valid || rsp_data!==held_data || rsp_error!==held_error)$fatal(1,"response backpressure instability");end
   rsp_ready=1;@(posedge clk);@(negedge clk);rsp_ready=0;
   if(writing && !expected_error)for(z=0;z<4;z=z+1)if(strobes[z])golden[address>>2][z*8+:8]=data[z*8+:8];
   last_data=held_data;transactions=transactions+1;
  end
 endtask
 initial begin
  $dumpfile("cache_2way.vcd");$dumpvars(1,tb_cache_2way);
  for(i=0;i<1024;i=i+1)begin memory[i]=32'h60000000^(i*32'h10203);golden[i]=memory[i];end
  repeat(4)@(negedge clk);rst_n=1;
  // Both ways coexist; true LRU replaces the least recently touched way.
  transaction(0,1,0,0,0,0);before_count=commands;
  transaction(0,1,4,0,0,0);if(commands!=before_count)$fatal(1,"same-line hit missed");
  transaction(0,1,64,0,0,0);transaction(0,1,0,0,0,0);
  transaction(0,1,128,0,0,0);before_count=commands;
  transaction(0,1,0,0,0,0);if(commands!=before_count)$fatal(1,"LRU evicted recent line");
  transaction(0,1,64,0,0,0);if(commands!=before_count+1)$fatal(1,"LRU did not evict old line");
  // Exercise sustained hit turnover and randomly stalled response consumer.
  transaction(0,1,0,0,0,0);sent=0;got=0;steps=0;
  while(got<256)begin
   @(negedge clk);req_valid=sent<256;req_write=0;req_cacheable=1;
   req_addr=(sent%4)*4;rsp_ready=rng[8] || rng[11];
   @(posedge clk);
   if(rsp_valid && rsp_ready)begin
    if(got>=sent || rsp_error || rsp_data!==expected_queue[got])$fatal(1,"turnover scoreboard mismatch sent=%0d got=%0d",sent,got);
    got=got+1;
   end
   if(req_valid && req_ready)begin expected_queue[sent]=golden[req_addr>>2];sent=sent+1;end
   steps=steps+1;if(steps>5000)$fatal(1,"turnover deadlock");
  end
  @(negedge clk);req_valid=0;rsp_ready=0;
  $display("PASS HIT STREAM requests=%0d responses=%0d steps=%0d",sent,got,steps);
  // Hit writes update byte lanes; miss writes do not allocate.
  transaction(1,1,64,32'habcdef12,4'b0101,0);before_count=commands;
  transaction(0,1,64,0,0,0);if(commands!=before_count)$fatal(1,"write hit lost line");
  transaction(1,1,512,32'h12345678,4'b1111,0);before_count=commands;
  transaction(0,1,512,0,0,0);if(commands!=before_count+1)$fatal(1,"write miss policy");
  // MMIO bypass never hits the cache even on repeated addresses.
  before_count=commands;transaction(0,0,768,0,0,0);transaction(0,0,768,0,0,0);
  if(commands!=before_count+2)$fatal(1,"uncacheable read was cached");
  transaction(1,0,768,32'hfeed0011,4'b1111,0);transaction(0,0,768,0,0,0);
  // Malformed/error bursts are drained and never installed as valid lines.
  fault_mode=1;transaction(0,1,1600,0,0,0);fault_mode=0;before_count=commands;
   transaction(0,1,1600,0,0,0);if(commands!=before_count+1)$fatal(1,"noncritical error line installed");
   for(j=1;j<=3;j=j+1)begin
   fault_mode=j;transaction(0,1,1024+j*64+((j==1)?4:0),0,0,1);fault_mode=0;before_count=commands;
   transaction(0,1,1024+j*64+((j==1)?4:0),0,0,0);if(commands!=before_count+1)$fatal(1,"bad line installed");
  end
  transaction(0,1,2048,0,0,0);fault_mode=4;transaction(1,1,2048,32'h12345678,15,1);
  fault_mode=0;before_count=commands;transaction(0,1,2048,0,0,0);
  if(commands!=before_count+1)$fatal(1,"errored write hit not invalidated");
  transaction(1,1,2048,32'h22334455,15,0);transaction(0,1,2048,0,0,0);
  before_count=commands;transaction(0,1,3,0,0,1);if(commands!=before_count)$fatal(1,"misaligned request reached backend");
  for(j=0;j<600;j=j+1)begin
   transaction(rng[6:5]==0,1,{20'b0,rng[11:2],2'b0},rng, rng[15:12],0);
  end
  @(negedge clk);invalidate=1;@(negedge clk);invalidate=0;
  before_count=commands;transaction(0,1,0,0,0,0);if(commands!=before_count+1)$fatal(1,"invalidate failed");
  // Reset cancels an in-flight fill in both cache and its backend contract.
  @(negedge clk);req_valid=1;req_write=0;req_cacheable=1;req_addr=3072;
  @(posedge clk);while(!req_ready)@(posedge clk);
  @(negedge clk);req_valid=0;wait(dut.state==3);
  @(negedge clk);rst_n=0;repeat(3)@(negedge clk);rst_n=1;
  repeat(2)@(negedge clk);if(rsp_valid)$fatal(1,"stale response after reset");
  before_count=commands;transaction(0,1,0,0,0,0);if(commands!=before_count+1)$fatal(1,"reset did not invalidate");
  $display("PASS CACHE transactions=%0d commands=%0d hits=%0d misses=%0d",transactions,commands,hits,misses);$finish;
 end
 initial begin #10000000;$fatal(1,"cache timeout");end
endmodule
