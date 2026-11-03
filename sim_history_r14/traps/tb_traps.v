`timescale 1ns/1ps
// v0.4 memory model allows consuming an old response and accepting a new
// request on one edge. No second uncompleted response may accumulate.
module tb_core_sync #(parameter FORWARD=1,PREDICT=1);
    reg clk=0, rst_n=0;
    always #5 clk=~clk;
    reg [31:0] rom[0:2047], ram[0:255];
    reg [31:0] rng=1;
    wire [31:0] ia, addr, wd, rd, pc, tpc, ti, td;
    wire [31:0] cycles, retired, branches, stalls, fetch_stalls;
    wire req_valid, req_ready, rsp_ready;
    reg rsp_valid=0, rsp_error=0;
    reg [31:0] rsp_data=0;
    wire valid, wr, ready, error, halted, tv, tw, flush, stall, fwd;
    wire [3:0] strb, cause;
    wire [4:0] tr;
    reg pending=0;
    reg [31:0] pending_addr=0;
    integer remaining=0;
    integer i, lane, fd, busfd, ramfd, seed, writes=0, expected_cause, ignored;
    integer requests=0, responses=0, fault_responses=0, turnover_accepts=0;
    integer wall_cycles=0, max_cycles=200000, max_delay=12, reset_phase=0;
    integer data_delay=0, data_remaining=0;
    reg data_pending=0;
    integer req_wait_cycles=0, rsp_wait_cycles=0, data_wait_cycles=0;
    integer redirects_req_fire=0, redirects_rsp_fire=0, redirects_pending=0;
    integer redirects_buffered_fault=0, error_rsp_wait_cycles=0;
    reg reset_performed=0;
    reg [31:0] fault_addr=32'hffffffff;
    reg [2047:0] filename;
    reg req_held=0, data_held=0, rsp_held=0;
    reg [31:0] held_ia, held_addr, held_wd, held_rsp;
    reg held_wr, held_error;
    reg [3:0] held_strb;

    assign req_ready=!pending && (!rsp_valid || rsp_ready) && (rng[1] || rng[5]);
    assign rd=(addr<8192)?rom[addr[12:2]]:ram[addr[9:2]];
    assign ready=(reset_phase==3 && !reset_performed) ? 1'b0 :
        data_delay>0 ? (data_pending && data_remaining==0) : (rng[0] || rng[2]);
    assign error=!(addr[31:10]==22'h040000 || (!wr && addr<8192));

    gwx_core_cached #(.ENABLE_TRAPS(1),.ENABLE_FORWARD(FORWARD),.ENABLE_PREDICT(PREDICT)) dut(.clk(clk), .rst_n(rst_n),
        .irq_external(ram[248][2]),.irq_timer(ram[248][1]),.irq_software(ram[248][0]),.imem_addr(ia), .imem_rdata(rsp_data), .imem_error(rsp_error),
        .i_req_valid(req_valid), .i_req_ready(req_ready),
        .i_rsp_valid(rsp_valid), .i_rsp_ready(rsp_ready),
        .d_valid(valid), .d_write(wr), .d_addr(addr), .d_wdata(wd), .d_wstrb(strb),
        .d_rdata(rd), .d_ready(ready), .d_error(error),
        .halted(halted), .trap_cause(cause), .debug_pc(pc),
        .debug_flush(flush), .debug_stall(stall), .debug_forward(fwd),
        .trace_valid(tv), .trace_pc(tpc), .trace_insn(ti),
        .trace_we(tw), .trace_rd(tr), .trace_data(td),
        .cycles(cycles), .retired(retired), .branches(branches), .stalls(stalls),
        .fetch_stalls(fetch_stalls));

    task clear_memory;
        begin
            for(i=0;i<256;i=i+1) ram[i]=0;
            writes=0;
        end
    endtask

    initial begin
        filename="program.hex"; expected_cause=3; seed=1;
        ignored=$value$plusargs("HEX=%s",filename);
        ignored=$value$plusargs("TRAP=%d",expected_cause);
        ignored=$value$plusargs("SEED=%d",seed);
        ignored=$value$plusargs("FAULT_ADDR=%h",fault_addr);
        ignored=$value$plusargs("MAX_DELAY=%d",max_delay);
        ignored=$value$plusargs("DATA_DELAY=%d",data_delay);
        ignored=$value$plusargs("MAX_CYCLES=%d",max_cycles);
        ignored=$value$plusargs("RESET_PHASE=%d",reset_phase);
        if(max_delay<1) $fatal(1,"Instruction memory must have at least one-cycle latency");
        rng=seed;
        clear_memory;
        $readmemh(filename,rom);
        fd=$fopen("core_trace.csv","w");
        busfd=$fopen("instruction_bus.csv","w");
        $fwrite(busfd,"cycle,event,address,error,reset_n\n");
        repeat(4) @(negedge clk); rst_n=1;
        if(reset_phase!=0) begin
            if(reset_phase==1) wait(pending);
            else if(reset_phase==2) wait(rsp_valid);
            else if(reset_phase==3) wait(valid && !ready);
            else $fatal(1,"Unknown reset phase");
            @(negedge clk);
            rst_n=0;
            reset_performed=1;
            clear_memory;
            $fclose(fd); fd=$fopen("core_trace.csv","w");
            $fwrite(busfd,"%0d,reset,00000000,0,0\n",wall_cycles);
            repeat(4) @(negedge clk); rst_n=1;
        end
        wait(ram[255]==32'h50415353); repeat(3) @(negedge clk);
        if(ram[254]!==0)$fatal(1,"machine test failure code=%0d cause=%h mepc=%h mtval=%h",ram[254],dut.cpu.csr_mcause,dut.cpu.csr_mepc,dut.cpu.csr_mtval);
        if(ram[253]!==13 || ram[252]!==6)$fatal(1,"not all synchronous exceptions/IRQs exercised");
        if(1'b0)
            $fatal(1,"Wrong trap: expected %0d got %0d",expected_cause,cause);
        if(dut.cpu.regs[0]!==0) $fatal(1,"x0 corrupted");
        if(requests==0 || responses==0) $fatal(1,"No actual instruction-bus activity");
        ramfd=$fopen("ram_final.hex","w");
        for(i=0;i<256;i=i+1) $fdisplay(ramfd,"%08x",ram[i]);
        $fclose(ramfd);
        $display("PASS CORE SYNC trap=%0d retired=%0d writes=%0d stalls=%0d fetch_stalls=%0d requests=%0d responses=%0d fault_responses=%0d reset_phase=%0d req_wait_cycles=%0d rsp_wait_cycles=%0d data_wait_cycles=%0d redirects_req_fire=%0d redirects_rsp_fire=%0d redirects_pending=%0d redirects_buffered_fault=%0d error_rsp_wait_cycles=%0d turnover_accepts=%0d i_hits=%0d i_misses=%0d d_hits=%0d d_misses=%0d",cause,retired,writes,stalls,fetch_stalls,requests,responses,fault_responses,reset_phase,req_wait_cycles,rsp_wait_cycles,data_wait_cycles,redirects_req_fire,redirects_rsp_fire,redirects_pending,redirects_buffered_fault,error_rsp_wait_cycles,turnover_accepts,dut.i_hits,dut.i_misses,dut.d_hits,dut.d_misses);
        $fclose(fd); $fclose(busfd); $finish;
    end

    always @(posedge clk) begin
        wall_cycles=wall_cycles+1;
        if(wall_cycles>max_cycles) $fatal(1,"Synchronous-fetch CPU timeout");
        if(!rst_n) begin
            pending<=0; rsp_valid<=0; rsp_error<=0; rsp_data<=0; remaining<=0;
            data_pending<=0; data_remaining<=0;
            req_held<=0; data_held<=0; rsp_held<=0;
        end else begin
            rng<={rng[30:0],rng[31]^rng[21]^rng[1]^rng[0]};
            // A held request remains binding even after an architectural halt.
            if(req_held && (!req_valid || ia!==held_ia))
                $fatal(1,"Instruction request changed while back-pressured");
            if(data_held && (!valid || addr!==held_addr || wr!==held_wr ||
                wd!==held_wd || strb!==held_strb))
                $fatal(1,"Data request changed while back-pressured");
            if(rsp_held && (!rsp_valid || rsp_data!==held_rsp || rsp_error!==held_error))
                $fatal(1,"Instruction response changed while back-pressured");
            req_held<=req_valid && !req_ready;
            data_held<=valid && !ready;
            rsp_held<=rsp_valid && !rsp_ready;
            held_ia<=ia; held_addr<=addr; held_wr<=wr; held_wd<=wd; held_strb<=strb;
            held_rsp<=rsp_data; held_error<=rsp_error;
            if(req_valid && !req_ready) req_wait_cycles=req_wait_cycles+1;
            if(rsp_valid && !rsp_ready) rsp_wait_cycles=rsp_wait_cycles+1;
            if(rsp_valid && rsp_error && !rsp_ready) error_rsp_wait_cycles=error_rsp_wait_cycles+1;
            if(valid && !ready) data_wait_cycles=data_wait_cycles+1;
            if(flush && req_valid && req_ready) redirects_req_fire=redirects_req_fire+1;
            if(flush && rsp_valid && rsp_ready) redirects_rsp_fire=redirects_rsp_fire+1;
            if(flush && pending) redirects_pending=redirects_pending+1;
            if(flush && dut.cpu.f_valid && dut.cpu.f_error) redirects_buffered_fault=redirects_buffered_fault+1;
            if(data_delay>0 && valid) begin
                if(!data_pending) begin
                    data_pending<=1; data_remaining<=1+(rng[23:16]%data_delay);
                end else if(data_remaining>0) data_remaining<=data_remaining-1;
                else if(ready) data_pending<=0;
            end

            if(req_valid && req_ready) begin
                if(pending || (rsp_valid && !rsp_ready))
                    $fatal(1,"More than one outstanding instruction read");
                // On turnover the old response below logs OLD pending_addr;
                // this nonblocking assignment becomes the new request address.
                pending<=1; pending_addr<=ia;
                remaining<=(rng[15:8]%max_delay);
                requests=requests+1;
                if(rsp_valid && rsp_ready) turnover_accepts=turnover_accepts+1;
                $fwrite(busfd,"%0d,request,%08x,0,1\n",wall_cycles,ia);
            end
            if(pending) begin
                if(remaining>0) remaining<=remaining-1;
                else begin
                    pending<=0; rsp_valid<=1;
                    rsp_error<=(pending_addr==fault_addr || pending_addr>=8192 || pending_addr[1:0]!=0);
                    rsp_data<=pending_addr<8192 ? rom[pending_addr[12:2]] : 32'hffffffff;
                end
            end
            if(rsp_valid && rsp_ready) begin
                rsp_valid<=0; responses=responses+1;
                if(rsp_error) fault_responses=fault_responses+1;
                $fwrite(busfd,"%0d,response,%08x,%0d,1\n",wall_cycles,pending_addr,rsp_error);
            end
            if(tv) $fwrite(fd,"%08x,%08x,%0d,%0d,%08x\n",tpc,ti,tw,tr,td);
            if(valid && wr && ready && !error) begin
                writes=writes+1;
                for(lane=0;lane<4;lane=lane+1)
                    if(strb[lane]) ram[addr[9:2]][8*lane +: 8]<=wd[8*lane +: 8];
            end
        end
    end
endmodule
