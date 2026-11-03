// DEVELOPMENT branch_v1: prediction metadata follows held requests, pending responses, fetch buffer and EX.
`timescale 1ns/1ps
// v0.4: elastic fetch with response/request turnover and no registered request
// bubble. A fresh request is locked if back-pressured, including across branch
// redirects. One outstanding response plus one returned-instruction buffer.
module gwx_core_sync #(
    parameter ENABLE_FORWARD = 1,
    parameter ENABLE_PREDICT = 1,
    parameter ENABLE_TRAPS = 1
)(
    input wire clk, rst_n,
    input wire irq_external,irq_timer,irq_software,
    output wire [31:0] imem_addr, input wire [31:0] imem_rdata,
    output wire i_req_valid, input wire i_req_ready,
    input wire i_rsp_valid, output wire i_rsp_ready, input wire imem_error,
    output wire d_valid, output reg d_write,
    output reg [31:0] d_addr, d_wdata, output reg [3:0] d_wstrb,
    input wire [31:0] d_rdata, input wire d_ready, d_error,
    output reg halted, output reg [3:0] trap_cause,
    output wire [31:0] debug_pc, output wire debug_flush, debug_stall, debug_forward,
    output wire trace_valid, output wire [31:0] trace_pc, trace_insn,
    output wire trace_we, output wire [4:0] trace_rd, output wire [31:0] trace_data,
    output reg [31:0] cycles, retired, branches, stalls, fetch_stalls,
 output wire [2:0] probe_pipe_valid
);
    reg [31:0] regs[0:31];
    reg x_valid, x_error, w_valid, w_we;
    reg [31:0] x_pc, x_insn, w_pc, w_insn, w_data;
    reg [4:0] w_rd;
    // Explicit ID(F buffer) -> EX(X) -> MEM(M) -> WB(W) boundaries.
    reg [31:0] x_a, x_b;
    reg m_valid, m_mem, m_write, m_we;
    reg [31:0] m_pc,m_insn,m_addr,m_wdata,m_result;
    reg [3:0] m_strb;
    reg [4:0] m_rd;
    reg [2:0] m_f3;
    reg [31:0] ex_addr,ex_wdata;
    reg ex_write;
    reg [3:0] ex_strb;
    reg [31:0] next_pc, fetch_pc;
    reg req_hold, req_discard, fetch_pending, fetch_discard;
    reg [31:0] req_addr;
    reg f_valid, f_error;
    reg [31:0] f_pc, f_insn;
    reg [31:0] req_pred_next, fetch_pred_next, f_pred_next, x_pred_next;
    wire predict_taken;
    wire [31:0] predict_next,predictor_next;
    assign predict_next=ENABLE_PREDICT ? predictor_next : next_pc+32'd4;
    wire resolved=x_valid && !halted && !waiting && !bad && !access_fault && !take_irq;
    wire [31:0] actual_next=jump ? target : x_pc+32'd4;
    gwx_btb #(.INDEX_BITS(6)) predictor(.clk(clk),.rst_n(rst_n),.invalidate(1'b0),
        .query_pc(next_pc),.predicted_taken(predict_taken),.predicted_target(predictor_next),
        .update_valid(resolved),.update_branch(conditional_branch || opcode==7'h6f || opcode==7'h67),
        .update_conditional(conditional_branch),.update_taken(jump),
        .update_pc(x_pc),.update_target(target),
        .update_call((opcode==7'h6f || opcode==7'h67) && (rd==1 || rd==5)),
        .update_return(opcode==7'h67 && rd==0 && (rs1==1 || rs1==5) && imm_i==0));
    wire [4:0] rs1=x_insn[19:15], rs2=x_insn[24:20], rd=x_insn[11:7];
    wire [6:0] opcode=x_insn[6:0], f7=x_insn[31:25];
    wire [2:0] f3=x_insn[14:12];
    wire [31:0] a=x_a,b=x_b;
    // RV32I + Zmmul: one unsigned 32x32 product, signed-high corrections.
    // No DIV/REM claim; software division runtime remains RV32I.
    wire [63:0] multiply_unsigned=a*b;
    wire [31:0] multiply_high_ss=multiply_unsigned[63:32]-(a[31]?b:32'b0)-(b[31]?a:32'b0);
    wire [31:0] multiply_high_su=multiply_unsigned[63:32]-(a[31]?b:32'b0);
    // Explicit borrow/sign logic keeps signed and unsigned comparisons distinct
    // through the vendor synthesizer. In particular 2 < 32'hffffffff is true.
    wire [32:0] branch_difference={1'b0,a}-{1'b0,b};
    wire branch_ltu=branch_difference[32];
    wire branch_lts=(a[31]^b[31])?a[31]:branch_ltu;
    wire [31:0] compare_rhs=opcode==7'h13 ? imm_i : b;
    wire [32:0] alu_difference={1'b0,a}-{1'b0,compare_rhs};
    wire alu_ltu=alu_difference[32];
    wire alu_lts=(a[31]^compare_rhs[31])?a[31]:alu_ltu;
    wire [31:0] imm_i={{20{x_insn[31]}},x_insn[31:20]};
    wire [31:0] imm_s={{20{x_insn[31]}},x_insn[31:25],x_insn[11:7]};
    wire [31:0] imm_b={{19{x_insn[31]}},x_insn[31],x_insn[7],x_insn[30:25],x_insn[11:8],1'b0};
    wire [31:0] imm_j={{11{x_insn[31]}},x_insn[31],x_insn[19:12],x_insn[20],x_insn[30:21],1'b0};
    reg [31:0] result, target, rhs, load_result;
    // Keep one explicitly unsigned barrel shifter. PDS Lite 2022.2 mapped
    // the mixed signed/unsigned >> / >>> case to arithmetic shift for SRL
    // (post-synthesis counterexample: 0x80000001 >> 1 became 0xc0000000).
    // Arithmetic right shift is the logical value OR an explicit sign mask.
    wire [4:0] shift_amount=opcode==7'h13 ? x_insn[24:20] : b[4:0];
    wire [31:0] right_shift=a >> shift_amount;
    wire [31:0] right_sign_mask=~(32'hffffffff >> shift_amount);
    wire [31:0] load_shift=d_rdata >> (8*m_addr[1:0]);
    reg write_rd, mem_op, jump, conditional_branch, bad;
    reg [3:0] fault;
    reg [1:0] size;
    // M-only RV32 machine state. No S/U/PMP/MMU or full privileged certification claim.
    reg[31:0]csr_mstatus,csr_mie,csr_mtvec,csr_mscratch,csr_mepc,csr_mcause,csr_mtval;
    reg[31:0]cycles_high,retired_high,trap_count;
    wire[31:0]mip_value={20'b0,irq_external,3'b0,irq_timer,3'b0,irq_software,3'b0};
    wire[31:0]irq_enabled=csr_mie & mip_value;
    wire[3:0]irq_code=irq_enabled[11]?4'd11:irq_enabled[3]?4'd3:4'd7;
    wire take_irq=ENABLE_TRAPS && csr_mstatus[3] && |irq_enabled && x_valid && !halted && !waiting && !access_fault && !bad;
    wire csr_instruction=opcode==7'h73 && (f3==1||f3==2||f3==3||f3==5||f3==6||f3==7);
    wire[11:0]csr_address=x_insn[31:20];
    wire[31:0]csr_source=f3[2]?{27'b0,rs1}:a;
    wire csr_write_enable=f3[1:0]==1 || rs1!=0;
    reg[31:0]csr_read_value;reg csr_known,csr_read_only;
    wire[31:0]csr_write_value=f3[1:0]==1?csr_source:f3[1:0]==2?(csr_read_value|csr_source):(csr_read_value&~csr_source);
    wire mret_instruction=ENABLE_TRAPS && x_insn==32'h30200073;
    wire[31:0]trap_pc=access_fault?m_pc:x_pc;
    wire[31:0]trap_code=take_irq?(32'h80000000|{28'b0,irq_code}):{28'b0,access_fault?(m_write?4'd7:4'd5):fault};
    wire[31:0]trap_vector={csr_mtvec[31:2],2'b0}+((take_irq && csr_mtvec[1:0]==1)?{26'b0,irq_code,2'b0}:32'b0);
    reg[31:0]trap_value;
    always @*begin
     csr_read_value=0;csr_known=1;csr_read_only=0;
     case(csr_address)
      12'h300:csr_read_value=csr_mstatus;
      12'h301:csr_read_value=32'h40000100; // Zmmul does not set the full-M bit.
      12'h304:csr_read_value=csr_mie;
      12'h305:csr_read_value=csr_mtvec;
      12'h340:csr_read_value=csr_mscratch;
      12'h341:csr_read_value=csr_mepc;
      12'h342:csr_read_value=csr_mcause;
      12'h343:csr_read_value=csr_mtval;
      12'h344:csr_read_value=mip_value;
      12'hb00:csr_read_value=cycles;
      12'hb80:csr_read_value=cycles_high;
      12'hb02:csr_read_value=retired;
      12'hb82:csr_read_value=retired_high;
      12'hc00:begin csr_read_value=cycles;csr_read_only=1;end
      12'hc80:begin csr_read_value=cycles_high;csr_read_only=1;end
      12'hc02:begin csr_read_value=retired;csr_read_only=1;end
      12'hc82:begin csr_read_value=retired_high;csr_read_only=1;end
      12'hf11,12'hf12,12'hf13,12'hf14:begin csr_read_value=0;csr_read_only=1;end
      12'hbc0:csr_read_value=trap_count; // custom machine trap-count register
      default:csr_known=0;
     endcase
    end
    always @*begin
     if(access_fault)trap_value=m_addr;
     else case(fault)
      0:trap_value=target;
      1:trap_value=x_pc;
      2:trap_value=x_insn;
      3:trap_value=x_pc;
      4,6:trap_value=ex_addr;
      default:trap_value=0;
     endcase
     if(take_irq)trap_value=0;
    end
    integer i;
    always @* begin
        case(m_f3)
            0: load_result={{24{load_shift[7]}},load_shift[7:0]};
            1: load_result={{16{load_shift[15]}},load_shift[15:0]};
            2: load_result=load_shift;
            4: load_result={24'b0,load_shift[7:0]};
            5: load_result={16'b0,load_shift[15:0]};
            default: load_result=0;
        endcase
    end
    always @* begin
        result=0; target=0; rhs=0;
        write_rd=0; mem_op=0; jump=0; conditional_branch=0;
        bad=0; fault=2; size=0;
        ex_addr=0; ex_write=0; ex_wdata=0; ex_strb=0;
        case(opcode)
            7'h37: begin write_rd=1; result={x_insn[31:12],12'b0}; end
            7'h17: begin write_rd=1; result=x_pc+{x_insn[31:12],12'b0}; end
            7'h6f: begin write_rd=1; result=x_pc+4; jump=1; target=x_pc+imm_j; end
            7'h67: begin
                write_rd=1; result=x_pc+4; jump=1; target=(a+imm_i)&32'hfffffffe;
                if(f3!=0) bad=1;
            end
            7'h63: begin
                conditional_branch=1; target=x_pc+imm_b;
                case(f3)
                    0: jump=a==b; 1: jump=a!=b;
                    4: jump=branch_lts; 5: jump=!branch_lts;
                    6: jump=branch_ltu; 7: jump=!branch_ltu;
                    default: bad=1;
                endcase
            end
            7'h13,7'h33: begin
                write_rd=1; rhs=opcode==7'h13 ? imm_i : b;
                if(opcode==7'h33 && f7==7'h01 && f3<4)begin
                    case(f3)
                        0:result=multiply_unsigned[31:0];
                        1:result=multiply_high_ss;
                        2:result=multiply_high_su;
                        3:result=multiply_unsigned[63:32];
                    endcase
                end else case(f3)
                    0: result=(opcode==7'h33 && f7==7'h20) ? a-rhs : a+rhs;
                    1: result=a << rhs[4:0];
                    2: result={31'b0,alu_lts};
                    3: result={31'b0,alu_ltu};
                    4: result=a^rhs;
                    5: result=right_shift | ((x_insn[30] && a[31])?right_sign_mask:32'b0);
                    6: result=a|rhs; 7: result=a&rhs;
                endcase
                if(opcode==7'h33 && !(f7==0 || (f7==7'h20 && (f3==0 || f3==5)) || (f7==1 && f3<4))) bad=1;
                if(opcode==7'h13 && f3==1 && f7!=0) bad=1;
                if(opcode==7'h13 && f3==5 && !(f7==0 || f7==7'h20)) bad=1;
            end
            7'h03: begin
                mem_op=1; write_rd=1; ex_addr=a+imm_i; size=f3[1:0];
                if(!(f3==0 || f3==1 || f3==2 || f3==4 || f3==5)) bad=1;
                if(!bad && ((size==1 && ex_addr[0]) || (size==2 && ex_addr[1:0]!=0))) begin bad=1; fault=4; end
            end
            7'h23: begin
                mem_op=1; ex_write=1; ex_addr=a+imm_s; size=f3[1:0];
                ex_wdata=b << (8*ex_addr[1:0]);
                case(f3)
                    0: ex_strb=4'b0001 << ex_addr[1:0];
                    1: ex_strb=4'b0011 << ex_addr[1:0];
                    2: ex_strb=4'b1111;
                    default: bad=1;
                endcase
                if(!bad && ((size==1 && ex_addr[0]) || (size==2 && ex_addr[1:0]!=0))) begin bad=1; fault=6; end
            end
            7'h0f: if(f3!=0) bad=1;
            7'h73: begin
                bad=1;
                if(ENABLE_TRAPS && csr_instruction)begin
                    bad=!csr_known || (csr_read_only && csr_write_enable);write_rd=1;result=csr_read_value;
                end else if(mret_instruction)begin bad=0;jump=1;target=csr_mepc;end
                else if(ENABLE_TRAPS && x_insn==32'h10500073)bad=0; // WFI is a legal no-op implementation.
                else if(x_insn==32'h00000073) fault=11;
                else if(x_insn==32'h00100073) fault=3;
            end
            default: bad=1;
        endcase
        if(jump && !bad && target[1:0]!=0) begin bad=1; fault=0; end
        if(x_error) begin bad=1; fault=1; end
    end
    always @* begin d_addr=m_addr;d_write=m_write;d_wdata=m_wdata;d_wstrb=m_strb;end
    assign d_valid=m_valid && !halted && m_mem;
    wire waiting=d_valid && !d_ready;
    wire access_fault=d_valid && d_ready && d_error;
    wire stop_event=!halted && (access_fault || (x_valid && !waiting && bad) || take_irq);
    wire redirect=x_valid && !halted && !waiting && !bad && !access_fault && !stop_event && actual_next!=x_pred_next;
    wire advance_x=!halted && !waiting && !stop_event && !redirect;
    wire [4:0] id_rs1=f_insn[19:15],id_rs2=f_insn[24:20];
    wire [6:0] id_op=f_insn[6:0];
    wire use_rs1=id_op==7'h67 || id_op==7'h63 || id_op==7'h13 || id_op==7'h33 || id_op==7'h03 || id_op==7'h23 || (id_op==7'h73 && !f_insn[14] && f_insn[13:12]!=0);
    wire use_rs2=id_op==7'h63 || id_op==7'h33 || id_op==7'h23;
    wire x_dep=x_valid && write_rd && rd!=0 && ((use_rs1 && rd==id_rs1)||(use_rs2 && rd==id_rs2));
    wire m_dep=m_valid && m_we && m_rd!=0 && ((use_rs1 && m_rd==id_rs1)||(use_rs2 && m_rd==id_rs2));
    wire w_dep=w_valid && w_we && w_rd!=0 && ((use_rs1 && w_rd==id_rs1)||(use_rs2 && w_rd==id_rs2));
    wire id_hazard=ENABLE_FORWARD ? (x_dep && mem_op) : (x_dep || m_dep || w_dep);
    wire pop_f=advance_x && f_valid && !id_hazard;
    wire [31:0] m_value=m_mem && !m_write ? load_result : m_result;
    wire x_fwd1=ENABLE_FORWARD && x_valid && write_rd && !mem_op && rd!=0 && rd==id_rs1;
    wire x_fwd2=ENABLE_FORWARD && x_valid && write_rd && !mem_op && rd!=0 && rd==id_rs2;
    wire m_fwd1=ENABLE_FORWARD && m_valid && m_we && m_rd!=0 && m_rd==id_rs1;
    wire m_fwd2=ENABLE_FORWARD && m_valid && m_we && m_rd!=0 && m_rd==id_rs2;
    wire w_fwd1=ENABLE_FORWARD && w_valid && w_we && w_rd!=0 && w_rd==id_rs1;
    wire w_fwd2=ENABLE_FORWARD && w_valid && w_we && w_rd!=0 && w_rd==id_rs2;
    wire [31:0] id_a=id_rs1==0 ? 0 : x_fwd1 ? result : m_fwd1 ? m_value : w_fwd1 ? w_data : regs[id_rs1];
    wire [31:0] id_b=id_rs2==0 ? 0 : x_fwd2 ? result : m_fwd2 ? m_value : w_fwd2 ? w_data : regs[id_rs2];
    assign i_rsp_ready=fetch_pending && (halted || fetch_discard || redirect || stop_event || !f_valid || pop_f);
    wire rsp_fire=i_rsp_valid && i_rsp_ready;
    wire live_response=rsp_fire && !fetch_discard && !halted && !redirect && !stop_event;
    wire bypass_response=1'b0; // ID stage may never be bypassed.

    // Turn over a consumed response without waiting for a registered request.
    // No fresh sequential request is presented on an architectural redirect or
    // stop. An already-presented back-pressured request may not be withdrawn.
    wire fresh_request=rst_n && !req_hold && (!fetch_pending || rsp_fire) &&
        (!f_valid || pop_f) && !halted && !redirect && !stop_event;
    assign i_req_valid=rst_n && (req_hold || fresh_request);
    assign imem_addr=req_hold ? req_addr : next_pc;
    wire req_fire=i_req_valid && i_req_ready;

    assign debug_pc=x_pc;
    assign debug_stall=waiting || (f_valid && id_hazard);
    assign debug_flush=redirect || (ENABLE_TRAPS && stop_event);
    assign debug_forward=pop_f && ((use_rs1 && (x_fwd1||m_fwd1||w_fwd1)) || (use_rs2 && (x_fwd2||m_fwd2||w_fwd2)));
    assign trace_valid=w_valid;
    assign trace_pc=w_pc;
    assign trace_insn=w_insn;
    assign trace_we=w_we && w_rd!=0;
    assign trace_rd=w_rd;
    assign trace_data=w_data;
    always @(posedge clk) begin
        if(!rst_n) begin
            req_pred_next<=4; fetch_pred_next<=4; f_pred_next<=4; x_pred_next<=4;
            next_pc<=0; req_hold<=0; req_addr<=0; req_discard<=0;
            fetch_pending<=0; fetch_pc<=0; fetch_discard<=0;
            f_valid<=0; f_pc<=0; f_insn<=32'h13; f_error<=0;
            x_valid<=0; x_pc<=0; x_insn<=32'h13; x_error<=0;
            x_a<=0;x_b<=0;
            m_valid<=0;m_mem<=0;m_write<=0;m_we<=0;m_pc<=0;m_insn<=0;
            m_addr<=0;m_wdata<=0;m_result<=0;m_strb<=0;m_rd<=0;m_f3<=0;
            w_valid<=0; w_we<=0; w_rd<=0; w_pc<=0; w_insn<=0; w_data<=0;
            halted<=0; trap_cause<=0; cycles<=0; retired<=0;
            csr_mstatus<=32'h1800;csr_mie<=0;csr_mtvec<=0;csr_mscratch<=0;csr_mepc<=0;csr_mcause<=0;csr_mtval<=0;
            cycles_high<=0;retired_high<=0;trap_count<=0;
            branches<=0; stalls<=0; fetch_stalls<=0;
            for(i=0;i<32;i=i+1) regs[i]<=0;
        end else begin
            cycles<=cycles+1;
            if(cycles==32'hffffffff)cycles_high<=cycles_high+1'b1;
            if(w_valid && retired==32'hffffffff)retired_high<=retired_high+1'b1;
            if(w_valid) begin
                retired<=retired+1;
                if(w_we && w_rd!=0) regs[w_rd]<=w_data;
            end
            w_valid<=0;

            if(ENABLE_TRAPS && resolved)begin
             if(csr_instruction && csr_write_enable)case(csr_address)
              12'h300:csr_mstatus<=(csr_write_value&32'h88)|32'h1800;
              12'h304:csr_mie<=csr_write_value&32'h888;
              12'h305:csr_mtvec<={csr_write_value[31:2],1'b0,csr_write_value[1:0]==1};
              12'h340:csr_mscratch<=csr_write_value;
              12'h341:csr_mepc<={csr_write_value[31:2],2'b0};
              12'h342:csr_mcause<=csr_write_value;
              12'h343:csr_mtval<=csr_write_value;
              12'hb00:cycles<=csr_write_value;
              12'hb80:cycles_high<=csr_write_value;
              12'hb02:retired<=csr_write_value;
              12'hb82:retired_high<=csr_write_value;
              12'hbc0:trap_count<=csr_write_value;
              default:begin end // fixed misa and externally driven mip are WARL.
             endcase
             if(mret_instruction)begin csr_mstatus[3]<=csr_mstatus[7];csr_mstatus[7]<=1;csr_mstatus[12:11]<=3;end
            end
            if(!halted && !x_valid && !pop_f && !bypass_response) fetch_stalls<=fetch_stalls+1;

            // Reserve the PC when a fresh request is presented at a clock edge,
            // whether accepted now or locked for later acceptance.
            if(fresh_request) begin
                next_pc<=predict_next;
                if(!i_req_ready) begin
                    req_hold<=1; req_addr<=next_pc; req_discard<=0; req_pred_next<=predict_next;
                end
            end
            if(req_hold && req_fire) begin
                req_hold<=0; req_discard<=0;
            end

            // New request wins pending metadata on same-edge turnover. Old
            // response consumers below read old fetch_pc via NBA semantics.
            if(req_fire) begin
                fetch_pending<=1; fetch_pc<=imem_addr;
                fetch_pred_next<=req_hold ? req_pred_next : predict_next;
                fetch_discard<=(req_hold && req_discard) || redirect || stop_event || halted;
            end else if(rsp_fire) fetch_pending<=0;
            if(pop_f) f_valid<=0;
            if(live_response && !bypass_response) begin
                f_valid<=1; f_pc<=fetch_pc; f_insn<=imem_rdata; f_error<=imem_error; f_pred_next<=fetch_pred_next;
            end
            if(!halted) begin
                if(waiting) stalls<=stalls+1;
                if(!waiting) begin
                    w_valid<=m_valid && !access_fault;
                    w_we<=m_we;w_rd<=m_rd;w_pc<=m_pc;w_insn<=m_insn;w_data<=m_value;
                    m_valid<=0;
                end
                if(waiting) begin end
                else if(stop_event) begin
                    x_valid<=0;f_valid<=0;m_valid<=0;
                    trap_cause<=trap_code[3:0];
                    if(ENABLE_TRAPS)begin
                     csr_mepc<={trap_pc[31:2],2'b0};csr_mcause<=trap_code;csr_mtval<=trap_value;
                     csr_mstatus[7]<=csr_mstatus[3];csr_mstatus[3]<=0;csr_mstatus[12:11]<=3;
                     trap_count<=trap_count+1'b1;
                    end else halted<=1;
                end else begin
                    if(x_valid) begin
                        m_valid<=1;m_mem<=mem_op;m_write<=ex_write;m_we<=write_rd;
                        m_rd<=rd;m_pc<=x_pc;m_insn<=x_insn;m_addr<=ex_addr;
                        m_wdata<=ex_wdata;m_strb<=ex_strb;m_result<=result;m_f3<=f3;
                        if(conditional_branch) branches<=branches+1;
                    end
                    x_valid<=0;
                    if(pop_f) begin
                        x_valid<=1; x_pc<=f_pc; x_insn<=f_insn; x_error<=f_error; x_pred_next<=f_pred_next;
                        x_a<=id_a;x_b<=id_b;
                    end else if(bypass_response) begin
                        x_valid<=1; x_pc<=fetch_pc; x_insn<=imem_rdata; x_error<=imem_error; x_pred_next<=fetch_pred_next;
                    end
                end
            end
            if(redirect || stop_event) begin
                f_valid<=0;
                if(ENABLE_TRAPS && stop_event)next_pc<=trap_vector;else if(redirect) next_pc<=actual_next;
                if(req_hold && !req_fire) req_discard<=1;
                if(fetch_pending && !rsp_fire) fetch_discard<=1;
            end
        end
    end
assign probe_pipe_valid={m_valid,x_valid,f_valid};
endmodule

`timescale 1ns/1ps
// Development IP: tagged BTB + per-entry two-bit saturating direction predictor.
// Query is combinational; update occurs only on resolved, non-squashed branches.
// Integration MUST carry predicted next-PC with each fetched instruction and
// flush all younger instructions on actual/predicted next-PC mismatch.
module gwx_btb #(parameter INDEX_BITS=4)(
 input wire clk,rst_n,invalidate,
 input wire[31:0]query_pc,
 output wire predicted_taken,output wire[31:0]predicted_target,
 input wire update_valid,update_branch,update_conditional,update_taken,
 input wire[31:0]update_pc,update_target,
 input wire update_call,update_return
);
 localparam ENTRIES=1<<INDEX_BITS,TAG_BITS=30-INDEX_BITS;
 reg valid[0:ENTRIES-1],conditional[0:ENTRIES-1],return_entry[0:ENTRIES-1];
 // Non-speculative RAS: updates only on resolved, non-faulting instructions.
 // Wrong predictions are recovered by the existing EX redirect path.
 reg[31:0]ras[0:15];reg[3:0]ras_sp;reg[4:0]ras_count;
 wire[3:0]ras_top=ras_sp-1'b1;
 reg[TAG_BITS-1:0]tags[0:ENTRIES-1];
 reg[31:0]targets[0:ENTRIES-1];reg[1:0]counters[0:ENTRIES-1];
 wire[INDEX_BITS-1:0]qi=query_pc[INDEX_BITS+1:2],ui=update_pc[INDEX_BITS+1:2];
 wire hit=valid[qi] && tags[qi]==query_pc[31:INDEX_BITS+2] && query_pc[1:0]==0;
 wire updating_hit=valid[ui] && tags[ui]==update_pc[31:INDEX_BITS+2];
 assign predicted_taken=rst_n && !invalidate && hit && (!conditional[qi] || counters[qi][1]);
 assign predicted_target=predicted_taken?((return_entry[qi] && ras_count!=0)?ras[ras_top]:targets[qi]):query_pc+32'd4;
 integer i;
 always @(posedge clk)begin
  if(!rst_n || invalidate)begin
   ras_sp<=0;ras_count<=0;for(i=0;i<16;i=i+1)ras[i]<=0;
   for(i=0;i<ENTRIES;i=i+1)begin valid[i]<=0;conditional[i]<=1;return_entry[i]<=0;counters[i]<=1;targets[i]<=0;tags[i]<=0;end
  end
  else if(update_valid && update_pc[1:0]==0)begin
   if(update_call)begin
    ras[ras_sp]<=update_pc+32'd4;ras_sp<=ras_sp+1'b1;
    if(ras_count!=16)ras_count<=ras_count+1'b1;
   end else if(update_return && ras_count!=0)begin ras_sp<=ras_sp-1'b1;ras_count<=ras_count-1'b1;end
   if(!update_branch)begin if(updating_hit)valid[ui]<=0;end
   else begin
    valid[ui]<=1;tags[ui]<=update_pc[31:INDEX_BITS+2];
    targets[ui]<=update_target;conditional[ui]<=update_conditional;return_entry[ui]<=update_return;
    if(!update_conditional)counters[ui]<=3;
    else if(!updating_hit || !conditional[ui])counters[ui]<=update_taken?2:1;
    else if(update_taken)begin if(counters[ui]!=3)counters[ui]<=counters[ui]+1'b1;end
    else if(counters[ui]!=0)counters[ui]<=counters[ui]-1'b1;
   end
  end
 end
endmodule
