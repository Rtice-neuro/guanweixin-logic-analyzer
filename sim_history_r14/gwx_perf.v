module gwx_perf(input wire clk,rst_n,rx,output wire tx,halted,finished,
 output wire[3:0]cause,output wire[31:0]pc,cycles,retired,exit_code,
 output wire trace_valid,output wire[31:0]trace_pc,trace_insn,
 output wire[31:0]i_hits,i_misses,d_hits,d_misses,data_stalls,fetch_stalls);
 gwx_external_soc #(.CPB(8),.HAS_EXTERNAL(1))soc(
 .clk(clk),.rst_n(rst_n),.rx(rx),.signal_in(8'b0),.tx(tx),.halted(halted),.cause(cause),
 .finished(finished),.exit_code(exit_code),.pc(pc),.cycles(cycles),.retired(retired),
 .trace_valid(trace_valid),.trace_pc(trace_pc),.trace_insn(trace_insn),
 .data_stalls(data_stalls),.fetch_stalls(fetch_stalls));
 assign i_hits=soc.core.i_hits;assign i_misses=soc.core.i_misses;
 assign d_hits=soc.core.d_hits;assign d_misses=soc.core.d_misses;
 endmodule
