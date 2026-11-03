`timescale 1ns/1ps
// 8N1 RX. Two synchronizers; sample at each bit centre; reject invalid stop.
module gwx_uart_rx #(parameter integer CLKS_PER_BIT=234)(
    input wire clk,rst_n,rx,
    output reg valid,frame_error,
    output reg [7:0] data
);
    (* async_reg="true" *) reg sync1,sync2;
    reg [1:0] state;
    reg [15:0] count;
    reg [2:0] bit_index;
    reg [7:0] shift;
    always @(posedge clk) begin
        if(!rst_n)begin sync1<=1;sync2<=1;end
        else begin sync1<=rx;sync2<=sync1;end
    end
    always @(posedge clk)begin
        if(!rst_n)begin state<=0;count<=0;bit_index<=0;shift<=0;data<=0;valid<=0;frame_error<=0;end
        else begin
            valid<=0;frame_error<=0;
            case(state)
            0:if(!sync2)begin state<=1;count<=CLKS_PER_BIT/2-1;end
            1:if(count!=0)count<=count-1'b1;
              else if(!sync2)begin state<=2;count<=CLKS_PER_BIT-1;bit_index<=0;end
              else state<=0;
            2:if(count!=0)count<=count-1'b1;
              else begin
                  shift[bit_index]<=sync2;count<=CLKS_PER_BIT-1;
                  if(bit_index==7)state<=3;else bit_index<=bit_index+1'b1;
              end
            3:if(count!=0)count<=count-1'b1;
              else begin
                  if(sync2)begin data<=shift;valid<=1;end else frame_error<=1;
                  state<=0;
              end
            endcase
        end
    end
endmodule
