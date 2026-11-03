// Application derivative of submission/rtl/gwx_submission_soc.v.
// Independent fork: unchanged CPU/memory handshake plus validated capture MMIO.
// Kept separate to preserve source hashes of the running CoreMark benchmark.
`timescale 1ns/1ps

// AI fork: one shared synchronous program ROM, independently held responses.
// Model ROM uses every bit of 36-bit DRM words, with two interleaved banks.
module gwx_external_program_memory #(parameter ROM_FILE="",parameter integer WORDS=12288)(
 input wire clk,input wire en_a,input wire[13:0]addr_a,output reg[31:0]q_a,
 input wire en_b,input wire[13:0]addr_b,output reg[31:0]q_b);
 wire[31:0]read_data;reg pending=0,owner=0;
 gwx_program_banks #(.PREFIX(ROM_FILE))banks(.clk(clk),.en(en_a||en_b),.addr(en_b?addr_b:addr_a),.q(read_data));
 always @(posedge clk)begin
  pending<=en_a||en_b;owner<=en_b;
  if(pending)begin if(owner)q_b<=read_data;else q_a<=read_data;end
 end
endmodule

module gwx_external_data_memory #(
    parameter integer WORDS = 16384
)(
    input wire clk,
    input wire read_en, input wire [13:0] read_addr,
    output reg [31:0] read_data,
    input wire write_en, input wire [13:0] write_addr,
    input wire [31:0] write_data, input wire [3:0] write_strb
);
    reg [31:0] ram [0:WORDS-1];
    integer lane;
    always @(posedge clk) begin
        if (read_en) read_data <= ram[read_addr];
        if (write_en)
            for (lane = 0; lane < 4; lane = lane + 1)
                if (write_strb[lane])
                    ram[write_addr][lane*8 +: 8] <= write_data[lane*8 +: 8];
    end
endmodule

// v0.4: remove redundant post-memory response registers. Each memory's output
// already holds the sampled word. Backpressure disables further reads, so the
// memory output itself is the stable response register.
// IF permits response acceptance and a new request on the same edge, while
// retaining a single outstanding slot. Data writes still commit ONLY at the
// CPU response-acceptance edge, never at the initial request-capture edge.
module gwx_external_soc #(
    parameter integer CPB = 8,
    parameter integer RANDOM_WAIT = 0,
    parameter ROM_FILE = "",
    parameter MODEL_PREFIX = "rom_banks/",
    parameter HAS_EXTERNAL=0,
    parameter ENABLE_FORWARD=1,ENABLE_PREDICT=1
)(
    input wire clk, input wire rst_n,
    input wire [7:0] signal_in,
    input wire rx,
    output wire tx,
    output wire halted, output wire [3:0] cause,
    output reg finished, output reg [31:0] exit_code,
    output wire [31:0] pc, cycles, retired,
    output reg [63:0] ticks,
    output wire [31:0] fetch_stalls,
    output wire [31:0] gpio_out, branches, data_stalls,
    output wire debug_flush, debug_stall, debug_forward,
    output wire trace_valid, trace_we,
    output wire [31:0] trace_pc, trace_insn, trace_data,
    output wire [4:0] trace_rd,
 output wire [179:0] probe_bus
);
    localparam [1:0] I_IDLE = 2'd0, I_DELAY = 2'd2, I_RESP = 2'd3;
    localparam [1:0] D_IDLE = 2'd0, D_RESP = 2'd3;
    localparam [2:0] KIND_ROM = 2'd0, KIND_RAM = 2'd1,
                     KIND_MMIO = 2'd2, KIND_BAD = 3'd3, KIND_MODEL=3'd4;
    wire [31:0] ia, insn;
    wire i_req_valid, i_req_ready, i_rsp_valid, i_rsp_ready, imem_error;
    wire [31:0] addr, wd, rd;
    wire req, wr, ready, error;
    wire [3:0] strb;
    wire busy;
    wire [7:0] rx_data;
    wire rx_byte_valid,rx_frame_error;
    reg[7:0] rx_fifo[0:31];
    reg[4:0] rx_read_ptr,rx_write_ptr;
    reg[5:0] rx_count;
    reg rx_overflow,rx_bad_frame;
    wire rx_pop=d_commit&&!d_write&&d_aligned==32'h40000008&&rx_count!=0;
    wire rx_push=rx_byte_valid&&(rx_count<32||rx_pop);
    gwx_uart_rx #(.CLKS_PER_BIT(CPB)) receiver(
        .clk(clk),.rst_n(rst_n),.rx(rx),.data(rx_data),.valid(rx_byte_valid),.frame_error(rx_frame_error));
    reg[6:0] test_config;
    reg[15:0] test_divider;
    reg test_restart;
    wire[7:0] internal_sample;
    gwx_test_source generator(.clk(clk),.rst_n(rst_n),.restart(test_restart),.armed(capture_armed),
        .divider(test_divider),.mode(test_config[3:1]),.channel(test_config[6:4]),.sample(internal_sample));
    wire[7:0] effective_signal=test_config[0]?internal_sample:signal_in;
    reg[31:0] forward_events,flush_events;
    reg trace_enabled;
    reg[4:0] trace_count;
    reg[31:0] trace_pcs[0:15],trace_insns[0:15],trace_values[0:15],trace_meta[0:15];
    reg [31:0] rng;

    reg i_pending, i_pending_error;
    reg [2:0] i_delay;
    wire [1:0] i_state = !i_pending ? I_IDLE : i_delay != 0 ? I_DELAY : I_RESP;
    wire i_address_good = ia < 32'h0000c000 && ia[1:0] == 2'b00;
    wire i_accept = i_req_valid && i_req_ready;
    wire i_response_accept = i_rsp_valid && i_rsp_ready;
    wire [31:0] rom_i_data, rom_d_data, ram_data;
    wire [31:0] i_response_data = i_pending_error ? 32'b0 : rom_i_data;
    wire i_response_error = i_pending_error;

    reg [1:0] d_state;reg[2:0]d_kind;
    reg [2:0] d_delay;
    reg [31:0] d_addr, d_wdata, d_mmio_snapshot, d_timer_high;
    reg [3:0] d_strb;
    reg d_write, d_pending_error;
    reg [31:0] gpio, high_latched;
    reg[63:0]mtimecmp;reg msip,external_irq_test;
    wire [31:0] aligned = {addr[31:2], 2'b00};
    wire [31:0] d_aligned = {d_addr[31:2], 2'b00};
    wire d_rom_sel = addr < 32'h0000c000;
    wire d_model_sel=addr>=32'h30000000 && addr<32'h30027000;
    wire d_ram_sel = addr[31:16] == 16'h1000;
    wire d_capture = rst_n && d_state == D_IDLE && req;
    wire d_uart_write = d_write && d_aligned == 32'h40000000 && d_strb[0];
    wire d_commit = rst_n && req && ready && !error;
    wire uart_push = d_commit && d_uart_write;
    wire ram_commit = d_commit && d_write && d_kind == KIND_RAM;
    wire d_response_error = d_pending_error;
    wire [31:0] d_response_data = d_write || d_pending_error ? 32'b0 :
        d_kind == KIND_ROM ? rom_d_data :
        d_kind == KIND_RAM ? ram_data : d_kind==KIND_MODEL ? model_data : d_mmio_snapshot;

    reg [31:0] capture_mmio_data;
    reg capture_mmio_error;
    reg [2:0] capture_kind;
    reg capture_error;
    integer lane;
    integer trace_reset_index;
    wire capture_selected = aligned[31:8]==24'h400004 || aligned[31:8]==24'h200000;
    wire [31:0] peripheral_rdata;
    wire peripheral_error;
    wire peripheral_commit = d_commit && d_write &&
        (d_aligned[31:8]==24'h400004 || d_aligned[31:8]==24'h200000);
    wire capture_armed,capture_active,capture_done,capture_aborted;
    wire [6:0] capture_count;
    wire [31:0] capture_checksum;
    wire [7:0] synchronized_in;
    gwx_external_capture capture_unit(
        .clk(clk),.rst_n(rst_n),.signal_in(effective_signal),
        .bus_addr(aligned),.bus_wdata(wd),.bus_write(wr),.bus_strb(strb),
        .bus_rdata(peripheral_rdata),.bus_error(peripheral_error),
        .commit(peripheral_commit),.commit_addr(d_aligned),.commit_data(d_wdata),
        .armed(capture_armed),.capturing(capture_active),.done(capture_done),
        .aborted(capture_aborted),.sample_count(capture_count),
        .checksum(capture_checksum),.synchronized_in(synchronized_in)
    );

    // No combinational path from i_req_valid to i_rsp_valid: the response slot
    // is registered. Turnover is legal only if its old response is consumable.
    assign gpio_out = gpio;
    assign i_rsp_valid = rst_n && i_pending && i_delay == 0;
    assign i_req_ready = rst_n && (!i_pending || (i_delay == 0 && i_rsp_ready)) && !(d_capture && d_rom_sel && !wr);
    assign insn = i_response_data;
    assign imem_error = i_response_error;
    assign rd = d_response_data;
    assign error = d_response_error;
    assign ready = rst_n && d_state == D_RESP && d_delay == 0 &&
                   (!d_uart_write || d_response_error || !busy);

    gwx_external_program_memory #(.ROM_FILE(ROM_FILE)) program_store (
        .clk(clk), .en_a(rst_n && i_accept && i_address_good),
        .addr_a(ia[15:2]), .q_a(rom_i_data),
        .en_b(d_capture && d_rom_sel && !wr),
        .addr_b(addr[15:2]), .q_b(rom_d_data)
    );

    wire[31:0]model_data;
    wire[18:0]scaled_index={addr[17:2],3'b0};
    wire[15:0]chunk_index=scaled_index/19'd9;
    wire[20:0]byte_bit_index={addr[17:2],5'b0};
    wire[20:0]base_bit_index=chunk_index*21'd36;
    wire[5:0]model_shift=byte_bit_index-base_bit_index;
    wire[35:0]model_even_q,model_odd_q;
    gwx_model_banks #(.PREFIX(MODEL_PREFIX))model_banks(.clk(clk),.en(d_capture&&d_model_sel&&!wr),
      .even_addr((chunk_index+16'd1)>>1),.odd_addr(chunk_index>>1),.even_q(model_even_q),.odd_q(model_odd_q));
    reg model_parity_q;reg[5:0]model_shift_q;
    always @(posedge clk)if(d_capture&&d_model_sel&&!wr)begin
      model_parity_q<=chunk_index[0];model_shift_q<=model_shift;
    end
    wire[71:0]model_pair=model_parity_q?{model_even_q,model_odd_q}:{model_odd_q,model_even_q};
    assign model_data=model_pair>>model_shift_q;
    wire[31:0]ai_mmio_data;wire ai_mmio_error;
    gwx_q4_mmio ai_accelerator(.clk(clk),.rst_n(rst_n),
      .address(aligned[7:0]),.write(wr),.wdata(wd),.wstrb(strb),
      .commit(d_commit&&d_write&&d_aligned[31:8]==24'h400007),
      .rdata(ai_mmio_data),.error(ai_mmio_error));

    gwx_external_data_memory data_store (
        .clk(clk), .read_en(d_capture && d_ram_sel && !wr),
        .read_addr(addr[15:2]), .read_data(ram_data),
        .write_en(ram_commit), .write_addr(d_addr[15:2]),
        .write_data(d_wdata), .write_strb(d_strb)
    );
    gwx_core_cached #(.ENABLE_FORWARD(ENABLE_FORWARD),.ENABLE_PREDICT(ENABLE_PREDICT)) core (
        .clk(clk), .rst_n(rst_n), .irq_external((rx_count!=0)||external_irq_test),
        .irq_timer(ticks>=mtimecmp),.irq_software(msip), .imem_addr(ia),
        .i_req_valid(i_req_valid), .i_req_ready(i_req_ready),
        .i_rsp_valid(i_rsp_valid), .i_rsp_ready(i_rsp_ready),
        .imem_rdata(insn), .imem_error(imem_error),
        .d_valid(req), .d_write(wr), .d_addr(addr),
        .d_wdata(wd), .d_wstrb(strb), .d_rdata(rd),
        .d_ready(ready), .d_error(error),
        .halted(halted), .trap_cause(cause), .debug_pc(pc),
        .probe_pipe_valid(probe_pipe_valid),.debug_flush(debug_flush), .debug_stall(debug_stall), .debug_forward(debug_forward),
        .trace_valid(trace_valid), .trace_pc(trace_pc), .trace_insn(trace_insn),
        .trace_we(trace_we), .trace_rd(trace_rd), .trace_data(trace_data),
        .cycles(cycles), .retired(retired), .branches(branches), .stalls(data_stalls),
        .fetch_stalls(fetch_stalls)
    );
    gwx_uart_tx #(.CLKS_PER_BIT(CPB)) uart (
        .clk(clk), .rst_n(rst_n), .valid(uart_push),
        .data(d_wdata[7:0]), .tx(tx), .busy(busy)
    );

    // Passive sample-report probe; does not drive or delay the CPU/UART bus.
    wire [2:0] probe_pipe_valid;
wire [7:0] probe_replay_data;
wire [5:0] probe_replay_index;
wire probe_replay_valid;
wire probe_replay_start;
wire [31:0] probe_record_id;
wire [31:0] probe_injection_id;
wire [7:0] probe_fault_mask;
wire [15:0] probe_fault_codes;
wire [1:0] probe_source;
wire probe_frame_ok;
wire probe_frame_error;
gwx_report_debug report_monitor (
      .clk(clk),.rst_n(rst_n),.byte_valid(uart_push),.byte_data(d_wdata[7:0]),
      .replay_data(probe_replay_data),.replay_index(probe_replay_index),.replay_valid(probe_replay_valid),.replay_start(probe_replay_start),
      .record_id(probe_record_id),.injection_id(probe_injection_id),.fault_mask(probe_fault_mask),.fault_codes(probe_fault_codes),
      .source(probe_source),.frame_ok(probe_frame_ok),.frame_error(probe_frame_error)
    ) /* synthesis syn_noprune=1 */;

    always @* begin
        capture_kind = KIND_BAD;
        capture_error = 0;
        capture_mmio_data = 0;
        capture_mmio_error = 0;
        if (d_rom_sel) begin
            capture_kind = KIND_ROM;
            capture_error = wr;
        end else if (d_ram_sel) capture_kind = KIND_RAM;
        else if(d_model_sel)begin capture_kind=KIND_MODEL;capture_error=wr;end
        else if(aligned[31:8]==24'h400007)begin
            capture_kind=KIND_MMIO;capture_mmio_data=ai_mmio_data;capture_error=ai_mmio_error;
        end
        else if (capture_selected) begin
            capture_kind = KIND_MMIO;
            capture_mmio_data = peripheral_rdata;
            capture_mmio_error = peripheral_error;
            capture_error = peripheral_error;
        end else if(aligned[31:8]==24'h200010)begin
            capture_kind=KIND_MMIO;capture_error=wr||aligned[7:4]>=trace_count;
            case(aligned[3:2])
              0:capture_mmio_data=trace_pcs[aligned[7:4]];
              1:capture_mmio_data=trace_insns[aligned[7:4]];
              2:capture_mmio_data=trace_values[aligned[7:4]];
              3:capture_mmio_data=trace_meta[aligned[7:4]];
            endcase
        end else begin
            capture_kind = KIND_MMIO;
            case (aligned)
                32'h40000000: capture_mmio_data = 0;
                32'h40000004: begin
                    capture_mmio_data = {31'b0, busy}; capture_mmio_error = wr;
                end
                32'h40000008:begin capture_mmio_data=rx_count!=0?{24'b0,rx_fifo[rx_read_ptr]}:0;capture_mmio_error=wr;end
                32'h4000000c:begin capture_mmio_data={18'b0,rx_count,5'b0,rx_bad_frame,rx_overflow,(rx_count!=0)};capture_mmio_error=wr;end
                32'h40000100: capture_mmio_data = gpio;
                32'h40000200: begin
                    capture_mmio_data = ticks[31:0]; capture_mmio_error = wr;
                end
                32'h40000204: begin
                    capture_mmio_data = high_latched; capture_mmio_error = wr;
                end
                32'h40000208: begin
                    capture_mmio_data = ticks[63:32]; capture_mmio_error = wr;
                end
                32'h40000300: begin
                    capture_mmio_data = retired; capture_mmio_error = wr;
                end
                32'h40000310:begin capture_mmio_data=cycles;capture_mmio_error=wr;end
                32'h40000314:begin capture_mmio_data=branches;capture_mmio_error=wr;end
                32'h40000318:begin capture_mmio_data=data_stalls;capture_mmio_error=wr;end
                32'h4000031c:begin capture_mmio_data=fetch_stalls;capture_mmio_error=wr;end
                32'h40000320:begin capture_mmio_data={31'b0,trace_enabled};capture_mmio_error=wr&&(strb!=15||wd>1);end
                32'h40000324:begin capture_mmio_data={27'b0,trace_count};capture_mmio_error=wr;end
                32'h40000328:begin capture_mmio_data=forward_events;capture_mmio_error=wr;end
                32'h4000032c:begin capture_mmio_data=flush_events;capture_mmio_error=wr;end
                32'h40000330:begin capture_mmio_data={30'b0,(ENABLE_PREDICT!=0),(ENABLE_FORWARD!=0)};capture_mmio_error=wr;end
                32'h40000600:begin
                    capture_mmio_data={25'b0,test_config};
                    capture_mmio_error=wr&&(strb!=15||wd>127||wd[3:1]>4||(!HAS_EXTERNAL&&!wd[0]));
                end
                32'h40000604:begin capture_mmio_data=HAS_EXTERNAL?3:1;capture_mmio_error=wr;end
                32'h40000608:begin capture_mmio_data={16'b0,test_divider};capture_mmio_error=wr&&(strb!=15||wd==0||wd>65535);end
                32'h40000800:begin capture_mmio_data=mtimecmp[31:0];capture_mmio_error=wr&&strb!=15;end
                32'h40000804:begin capture_mmio_data=mtimecmp[63:32];capture_mmio_error=wr&&strb!=15;end
                32'h40000808:begin capture_mmio_data={31'b0,msip};capture_mmio_error=wr&&(strb!=15||wd>1);end
                32'h4000080c:begin capture_mmio_data={31'b0,external_irq_test};capture_mmio_error=wr&&(strb!=15||wd>1);end
                32'h40000500: capture_mmio_data = exit_code;
                default: begin
                    capture_kind = KIND_BAD; capture_mmio_error = 1;
                end
            endcase
            capture_error = capture_mmio_error;
        end
    end

    always @(posedge clk) begin
        if (!rst_n) begin
            rx_read_ptr<=0;rx_write_ptr<=0;rx_count<=0;rx_overflow<=0;rx_bad_frame<=0;
            test_config<=1;test_divider<=270;test_restart<=0;
            forward_events<=0;flush_events<=0;trace_enabled<=0;trace_count<=0;
            // Resettable trace storage intentionally uses FFs, not LUT RAM:
            // this removes the short FF->distributed-RAM write-data hold path.
            for(trace_reset_index=0;trace_reset_index<16;trace_reset_index=trace_reset_index+1)begin
                trace_pcs[trace_reset_index]<=0;trace_insns[trace_reset_index]<=0;
                trace_values[trace_reset_index]<=0;trace_meta[trace_reset_index]<=0;
            end
            ticks <= 0; gpio <= 0; high_latched <= 0;mtimecmp<=64'hffffffffffffffff;msip<=0;external_irq_test<=0;
            finished <= 0; exit_code <= 32'hffffffff;
            rng <= 32'h12345678;
            i_pending <= 0; i_pending_error <= 0; i_delay <= 0;
            d_state <= D_IDLE; d_kind <= KIND_BAD; d_delay <= 0;
            d_addr <= 0; d_wdata <= 0; d_strb <= 0; d_write <= 0;
            d_mmio_snapshot <= 0; d_timer_high <= 0; d_pending_error <= 0;
        end else begin
            test_restart<=0;
            if(rx_push)begin rx_fifo[rx_write_ptr]<=rx_data;rx_write_ptr<=rx_write_ptr+1'b1;end
            if(rx_pop)rx_read_ptr<=rx_read_ptr+1'b1;
            case({rx_push,rx_pop})2'b10:rx_count<=rx_count+1'b1;2'b01:rx_count<=rx_count-1'b1;endcase
            if(rx_byte_valid&&!rx_push)rx_overflow<=1;
            if(rx_frame_error)rx_bad_frame<=1;
            if(debug_forward)forward_events<=forward_events+1'b1;
            if(debug_flush)flush_events<=flush_events+1'b1;
            if(trace_enabled&&trace_valid&&trace_count<16)begin
                trace_pcs[trace_count[3:0]]<=trace_pc;trace_insns[trace_count[3:0]]<=trace_insn;
                trace_values[trace_count[3:0]]<=trace_data;trace_meta[trace_count[3:0]]<={26'b0,trace_rd,trace_we};
                trace_count<=trace_count+1'b1;
            end
            if(d_commit&&d_write)case(d_aligned)
                32'h40000600:begin test_config<=d_wdata[6:0];test_restart<=1;end
                32'h40000608:test_divider<=d_wdata[15:0];
                32'h40000800:mtimecmp[31:0]<=d_wdata;
                32'h40000804:mtimecmp[63:32]<=d_wdata;
                32'h40000808:msip<=d_wdata[0];
                32'h4000080c:external_irq_test<=d_wdata[0];
                32'h40000320:begin trace_enabled<=d_wdata[0];if(d_wdata[0])trace_count<=0;end
            endcase
            ticks <= ticks + 1'b1;
            rng <= {rng[30:0], rng[31] ^ rng[21] ^ rng[1] ^ rng[0]};
            if (i_accept) begin
                // This takes priority over old-response acceptance: preserve
                // the newly admitted transaction in the same single slot.
                i_pending <= 1;
                i_pending_error <= !i_address_good;
                i_delay <= RANDOM_WAIT ? ({1'b0, rng[2:1]}+3'd1) : 3'd1;
            end else if (i_response_accept) i_pending <= 0;
            else if (i_pending && i_delay != 0) i_delay <= i_delay - 1'b1;

            if (d_state == D_IDLE && req) begin
                d_addr <= addr; d_wdata <= wd; d_strb <= strb;
                d_write <= wr; d_kind <= capture_kind;
                d_mmio_snapshot <= capture_mmio_data;
                d_timer_high <= ticks[63:32]; d_pending_error <= capture_error;
                d_delay <= RANDOM_WAIT ? ({1'b0, rng[5:4]}+3'd1) : (d_ram_sel ? 3'd0 : 3'd1);
                d_state <= D_RESP;
            end else if (d_state == D_RESP) begin
                if (d_delay != 0) d_delay <= d_delay - 1'b1;
                if (req && ready) begin
                    d_state <= D_IDLE;
                    if (!d_response_error) begin
                        if (!d_write && d_aligned == 32'h40000200)
                            high_latched <= d_timer_high;
                        if (d_write && d_aligned == 32'h40000100)
                            for (lane = 0; lane < 4; lane = lane + 1)
                                if (d_strb[lane])
                                    gpio[lane*8 +: 8] <= d_wdata[lane*8 +: 8];
                        if (d_write && d_aligned == 32'h40000500 && d_strb == 4'b1111) begin
                            exit_code <= d_wdata; finished <= 1;
                        end
                    end
                end
            end
        end
    end

assign probe_bus[0]=probe_replay_data[0];
assign probe_bus[1]=probe_replay_data[1];
assign probe_bus[2]=probe_replay_data[2];
assign probe_bus[3]=probe_replay_data[3];
assign probe_bus[4]=probe_replay_data[4];
assign probe_bus[5]=probe_replay_data[5];
assign probe_bus[6]=probe_replay_data[6];
assign probe_bus[7]=probe_replay_data[7];
assign probe_bus[8]=probe_replay_index[0];
assign probe_bus[9]=probe_replay_index[1];
assign probe_bus[10]=probe_replay_index[2];
assign probe_bus[11]=probe_replay_index[3];
assign probe_bus[12]=probe_replay_index[4];
assign probe_bus[13]=probe_replay_index[5];
assign probe_bus[14]=probe_replay_valid;
assign probe_bus[15]=probe_replay_start;
assign probe_bus[16]=probe_record_id[0];
assign probe_bus[17]=probe_record_id[1];
assign probe_bus[18]=probe_record_id[2];
assign probe_bus[19]=probe_record_id[3];
assign probe_bus[20]=probe_record_id[4];
assign probe_bus[21]=probe_record_id[5];
assign probe_bus[22]=probe_record_id[6];
assign probe_bus[23]=probe_record_id[7];
assign probe_bus[24]=probe_record_id[8];
assign probe_bus[25]=probe_record_id[9];
assign probe_bus[26]=probe_record_id[10];
assign probe_bus[27]=probe_record_id[11];
assign probe_bus[28]=probe_record_id[12];
assign probe_bus[29]=probe_record_id[13];
assign probe_bus[30]=probe_record_id[14];
assign probe_bus[31]=probe_record_id[15];
assign probe_bus[32]=probe_record_id[16];
assign probe_bus[33]=probe_record_id[17];
assign probe_bus[34]=probe_record_id[18];
assign probe_bus[35]=probe_record_id[19];
assign probe_bus[36]=probe_record_id[20];
assign probe_bus[37]=probe_record_id[21];
assign probe_bus[38]=probe_record_id[22];
assign probe_bus[39]=probe_record_id[23];
assign probe_bus[40]=probe_record_id[24];
assign probe_bus[41]=probe_record_id[25];
assign probe_bus[42]=probe_record_id[26];
assign probe_bus[43]=probe_record_id[27];
assign probe_bus[44]=probe_record_id[28];
assign probe_bus[45]=probe_record_id[29];
assign probe_bus[46]=probe_record_id[30];
assign probe_bus[47]=probe_record_id[31];
assign probe_bus[48]=probe_injection_id[0];
assign probe_bus[49]=probe_injection_id[1];
assign probe_bus[50]=probe_injection_id[2];
assign probe_bus[51]=probe_injection_id[3];
assign probe_bus[52]=probe_injection_id[4];
assign probe_bus[53]=probe_injection_id[5];
assign probe_bus[54]=probe_injection_id[6];
assign probe_bus[55]=probe_injection_id[7];
assign probe_bus[56]=probe_injection_id[8];
assign probe_bus[57]=probe_injection_id[9];
assign probe_bus[58]=probe_injection_id[10];
assign probe_bus[59]=probe_injection_id[11];
assign probe_bus[60]=probe_injection_id[12];
assign probe_bus[61]=probe_injection_id[13];
assign probe_bus[62]=probe_injection_id[14];
assign probe_bus[63]=probe_injection_id[15];
assign probe_bus[64]=probe_injection_id[16];
assign probe_bus[65]=probe_injection_id[17];
assign probe_bus[66]=probe_injection_id[18];
assign probe_bus[67]=probe_injection_id[19];
assign probe_bus[68]=probe_injection_id[20];
assign probe_bus[69]=probe_injection_id[21];
assign probe_bus[70]=probe_injection_id[22];
assign probe_bus[71]=probe_injection_id[23];
assign probe_bus[72]=probe_injection_id[24];
assign probe_bus[73]=probe_injection_id[25];
assign probe_bus[74]=probe_injection_id[26];
assign probe_bus[75]=probe_injection_id[27];
assign probe_bus[76]=probe_injection_id[28];
assign probe_bus[77]=probe_injection_id[29];
assign probe_bus[78]=probe_injection_id[30];
assign probe_bus[79]=probe_injection_id[31];
assign probe_bus[80]=probe_fault_mask[0];
assign probe_bus[81]=probe_fault_mask[1];
assign probe_bus[82]=probe_fault_mask[2];
assign probe_bus[83]=probe_fault_mask[3];
assign probe_bus[84]=probe_fault_mask[4];
assign probe_bus[85]=probe_fault_mask[5];
assign probe_bus[86]=probe_fault_mask[6];
assign probe_bus[87]=probe_fault_mask[7];
assign probe_bus[88]=probe_fault_codes[0];
assign probe_bus[89]=probe_fault_codes[1];
assign probe_bus[90]=probe_fault_codes[2];
assign probe_bus[91]=probe_fault_codes[3];
assign probe_bus[92]=probe_fault_codes[4];
assign probe_bus[93]=probe_fault_codes[5];
assign probe_bus[94]=probe_fault_codes[6];
assign probe_bus[95]=probe_fault_codes[7];
assign probe_bus[96]=probe_fault_codes[8];
assign probe_bus[97]=probe_fault_codes[9];
assign probe_bus[98]=probe_fault_codes[10];
assign probe_bus[99]=probe_fault_codes[11];
assign probe_bus[100]=probe_fault_codes[12];
assign probe_bus[101]=probe_fault_codes[13];
assign probe_bus[102]=probe_fault_codes[14];
assign probe_bus[103]=probe_fault_codes[15];
assign probe_bus[104]=trace_pc[0];
assign probe_bus[105]=trace_pc[1];
assign probe_bus[106]=trace_pc[2];
assign probe_bus[107]=trace_pc[3];
assign probe_bus[108]=trace_pc[4];
assign probe_bus[109]=trace_pc[5];
assign probe_bus[110]=trace_pc[6];
assign probe_bus[111]=trace_pc[7];
assign probe_bus[112]=trace_pc[8];
assign probe_bus[113]=trace_pc[9];
assign probe_bus[114]=trace_pc[10];
assign probe_bus[115]=trace_pc[11];
assign probe_bus[116]=trace_pc[12];
assign probe_bus[117]=trace_pc[13];
assign probe_bus[118]=trace_pc[14];
assign probe_bus[119]=trace_pc[15];
assign probe_bus[120]=trace_pc[16];
assign probe_bus[121]=trace_pc[17];
assign probe_bus[122]=trace_pc[18];
assign probe_bus[123]=trace_pc[19];
assign probe_bus[124]=trace_pc[20];
assign probe_bus[125]=trace_pc[21];
assign probe_bus[126]=trace_pc[22];
assign probe_bus[127]=trace_pc[23];
assign probe_bus[128]=trace_pc[24];
assign probe_bus[129]=trace_pc[25];
assign probe_bus[130]=trace_pc[26];
assign probe_bus[131]=trace_pc[27];
assign probe_bus[132]=trace_pc[28];
assign probe_bus[133]=trace_pc[29];
assign probe_bus[134]=trace_pc[30];
assign probe_bus[135]=trace_pc[31];
assign probe_bus[136]=trace_insn[0];
assign probe_bus[137]=trace_insn[1];
assign probe_bus[138]=trace_insn[2];
assign probe_bus[139]=trace_insn[3];
assign probe_bus[140]=trace_insn[4];
assign probe_bus[141]=trace_insn[5];
assign probe_bus[142]=trace_insn[6];
assign probe_bus[143]=trace_insn[7];
assign probe_bus[144]=trace_insn[8];
assign probe_bus[145]=trace_insn[9];
assign probe_bus[146]=trace_insn[10];
assign probe_bus[147]=trace_insn[11];
assign probe_bus[148]=trace_insn[12];
assign probe_bus[149]=trace_insn[13];
assign probe_bus[150]=trace_insn[14];
assign probe_bus[151]=trace_insn[15];
assign probe_bus[152]=trace_insn[16];
assign probe_bus[153]=trace_insn[17];
assign probe_bus[154]=trace_insn[18];
assign probe_bus[155]=trace_insn[19];
assign probe_bus[156]=trace_insn[20];
assign probe_bus[157]=trace_insn[21];
assign probe_bus[158]=trace_insn[22];
assign probe_bus[159]=trace_insn[23];
assign probe_bus[160]=trace_insn[24];
assign probe_bus[161]=trace_insn[25];
assign probe_bus[162]=trace_insn[26];
assign probe_bus[163]=trace_insn[27];
assign probe_bus[164]=trace_insn[28];
assign probe_bus[165]=trace_insn[29];
assign probe_bus[166]=trace_insn[30];
assign probe_bus[167]=trace_insn[31];
assign probe_bus[168]=trace_valid;
assign probe_bus[169]=trace_we;
assign probe_bus[170]=debug_forward;
assign probe_bus[171]=debug_flush;
assign probe_bus[172]=debug_stall;
assign probe_bus[173]=probe_pipe_valid[0];
assign probe_bus[174]=probe_pipe_valid[1];
assign probe_bus[175]=probe_pipe_valid[2];
assign probe_bus[176]=probe_source[0];
assign probe_bus[177]=probe_source[1];
assign probe_bus[178]=probe_frame_ok;
assign probe_bus[179]=probe_frame_error;
endmodule
