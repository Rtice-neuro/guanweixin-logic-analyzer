`timescale 1ns/1ps
module tb_ram_contract #(parameter RANDOM=0);
reg clk=0,rst_n=0,q=0,w=0;reg[31:0]a=0,v=0;reg[3:0]s=0;always #5 clk=~clk;
gwx_external_soc #(.RANDOM_WAIT(RANDOM),.CPB(8)) dut(.clk(clk),.rst_n(rst_n),.rx(1'b1),.signal_in(8'b0));
integer writes=0,expected_writes=0,reads=0,i,k,latency;reg[31:0]golden[0:63],rng=32'h61239a85,out;
always @(posedge clk)if(rst_n)begin
 if(dut.ram_commit)writes=writes+1;
 if(dut.ram_fast_write && (dut.uart_push || dut.d_commit))$fatal(1,"fast RAM store duplicated MMIO side effect");
end
task trans;input wr;input[31:0]addr,data;input[3:0]mask;input want_error;begin
 @(negedge clk);q=1;w=wr;a=addr;v=data;s=mask;latency=0;
 @(posedge clk);while(!dut.ready)begin latency=latency+1;if(latency>1000)$fatal(1,"deadlock");@(posedge clk);end
 if(dut.error!==want_error)$fatal(1,"incorrect bus error");out=dut.rd;
 if(!RANDOM && wr && addr[31:16]==16'h1000 && latency!=0)$fatal(1,"RAM write not same-edge ACK");
 if(!wr && addr[31:16]==16'h1000 && latency<1)$fatal(1,"RAM read illegally bypassed synchronous port");
 @(negedge clk);q=0;
end endtask
initial begin
 force dut.core.cpu.halted=1'b1;force dut.i_req_valid=1'b0;force dut.i_rsp_ready=1'b0;
 force dut.req=q;force dut.wr=w;force dut.addr=a;force dut.wd=v;force dut.strb=s;
 repeat(4)@(negedge clk);rst_n=1;
 for(i=0;i<64;i=i+1)begin golden[i]=32'h51f01200+i;trans(1,32'h10000000+i*4,golden[i],15,0);expected_writes=expected_writes+1;end
 trans(1,32'h40000100,32'h12345678,15,0);trans(1,32'h10000000,32'hbadc0ffe,15,0);golden[0]=32'hbadc0ffe;expected_writes=expected_writes+1;
 if(dut.gpio!==32'h12345678)$fatal(1,"RAM modified GPIO");
 trans(1,32'h40000000,32'h41,1,0);trans(1,32'h10000004,32'h76543210,15,0);golden[1]=32'h76543210;expected_writes=expected_writes+1;
 trans(0,32'h50000000,0,0,1);trans(1,32'h10000008,32'hf00dbabe,15,0);golden[2]=32'hf00dbabe;expected_writes=expected_writes+1;
 for(i=0;i<512;i=i+1)begin
  rng={rng[30:0],rng[31]^rng[21]^rng[1]^rng[0]};k=rng[7:2];
  if(rng[8])begin
   trans(1,32'h10000000+k*4,rng,rng[15:12],0);expected_writes=expected_writes+1;
   for(integer lane=0;lane<4;lane=lane+1)if(rng[12+lane])golden[k][lane*8+:8]=rng[lane*8+:8];
  end
  trans(0,32'h10000000+k*4,0,0,0);reads=reads+1;
  if(out!==golden[k])$fatal(1,"RAM mismatch index=%0d got=%h expected=%h",k,out,golden[k]);
 end
 if(writes!=expected_writes)$fatal(1,"repeated or missing writes actual=%0d expected=%0d",writes,expected_writes);
 $display("PASS RAM CONTRACT random_wait=%0d writes=%0d reads=%0d",RANDOM,writes,reads);$finish;
end
initial begin #10000000;$fatal(1,"timeout");end
endmodule
