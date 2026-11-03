`timescale 1ns/1ps
// CPU-controlled 8-channel asynchronous digital acquisition, fixed 64 samples.
// Each input has two synchronizer FFs. This is not a coherent CDC bus protocol:
// unrelated channel transitions near a clock edge can land on adjacent samples.
// No analog input, voltage translation, pre-trigger storage or glitch guarantee.
module gwx_external_capture(
    input wire clk, rst_n,
    input wire [7:0] signal_in,
    input wire [31:0] bus_addr, bus_wdata,
    input wire bus_write,
    input wire [3:0] bus_strb,
    output reg [31:0] bus_rdata,
    output reg bus_error,
    input wire commit,
    input wire [31:0] commit_addr, commit_data,
    output reg armed, capturing, done, aborted,
    output reg [6:0] sample_count,
    output reg [31:0] checksum,
    output wire [7:0] synchronized_in
);
    (* async_reg = "true" *) reg [7:0] sync1, sync2;
    reg [15:0] divider, countdown;
    reg [7:0] trigger_mask, trigger_value;
    reg [1:0] trigger_mode;
    reg previous_match;
    reg [7:0] samples[0:63];
    wire busy = armed || capturing;
    wire match_now = (sync2 & trigger_mask) == (trigger_value & trigger_mask);
    wire trigger_hit = trigger_mode==0 ? match_now :
                       trigger_mode==1 ? (match_now && !previous_match) :
                                         (!match_now && previous_match);
    wire data_window = bus_addr[31:8]==24'h200000;
    assign synchronized_in=sync2;

    // Validation is part of the request snapshot. No side effect before commit.
    always @* begin
        bus_rdata=0; bus_error=0;
        if (bus_addr[1:0]!=0) bus_error=1;
        else if (data_window) begin
            if(bus_write || !done) bus_error=1;
            else bus_rdata={24'b0,samples[bus_addr[7:2]]};
        end else begin
            case(bus_addr)
                32'h40000400: begin
                    if(bus_write && (bus_strb!=15 ||
                       (bus_wdata!=1 && bus_wdata!=2) || (bus_wdata==1 && busy))) bus_error=1;
                end
                32'h40000404: begin
                    bus_rdata={28'b0,aborted,done,capturing,armed}; bus_error=bus_write;
                end
                32'h40000408: begin
                    bus_rdata={16'b0,divider};
                    if(bus_write && (busy || bus_strb!=15 || bus_wdata==0 || bus_wdata>65535)) bus_error=1;
                end
                32'h4000040c: begin
                    bus_rdata={24'b0,trigger_mask};
                    if(bus_write && (busy || bus_strb!=15 || bus_wdata>255)) bus_error=1;
                end
                32'h40000410: begin
                    bus_rdata={24'b0,trigger_value};
                    if(bus_write && (busy || bus_strb!=15 || bus_wdata>255)) bus_error=1;
                end
                32'h40000414: begin
                    bus_rdata={30'b0,trigger_mode};
                    if(bus_write && (busy || bus_strb!=15 || bus_wdata>2)) bus_error=1;
                end
                32'h40000418: begin bus_rdata={25'b0,sample_count}; bus_error=bus_write; end
                32'h4000041c: begin bus_rdata=checksum; bus_error=bus_write; end
                default: bus_error=1;
            endcase
        end
    end
    always @(posedge clk) begin
        if(!rst_n) begin sync1<=0;sync2<=0;end
        else begin sync1<=signal_in;sync2<=sync1;end
    end
    always @(posedge clk) begin
        if(!rst_n) begin
            divider<=1;countdown<=0;trigger_mask<=0;trigger_value<=0;trigger_mode<=0;
            previous_match<=0;armed<=0;capturing<=0;done<=0;aborted<=0;
            sample_count<=0;checksum<=0;
        end else if(commit && commit_addr==32'h40000400) begin
            if(commit_data==2) begin armed<=0;capturing<=0;done<=0;aborted<=1;end
            else if(commit_data==1) begin
                armed<=1;capturing<=0;done<=0;aborted<=0;sample_count<=0;checksum<=0;
                countdown<=divider-1'b1;previous_match<=match_now;
            end
        end else begin
            if(commit) case(commit_addr)
                32'h40000408: divider<=commit_data[15:0];
                32'h4000040c: trigger_mask<=commit_data[7:0];
                32'h40000410: trigger_value<=commit_data[7:0];
                32'h40000414: trigger_mode<=commit_data[1:0];
            endcase
            if(busy) begin
                if(countdown!=0) countdown<=countdown-1'b1;
                else begin
                    countdown<=divider-1'b1;previous_match<=match_now;
                    if(capturing || trigger_hit) begin
                        samples[sample_count[5:0]]<=sync2;
                        checksum<=checksum+{24'b0,sync2};
                        sample_count<=sample_count+1'b1;armed<=0;
                        if(sample_count==63) begin capturing<=0;done<=1;end
                        else capturing<=1;
                    end
                end
            end
        end
    end
endmodule
