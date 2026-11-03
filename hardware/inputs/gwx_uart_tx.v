`timescale 1ns/1ps
module gwx_uart_tx #(parameter integer CLKS_PER_BIT=434)(
    input wire clk, input wire rst_n, input wire valid,
    input wire [7:0] data, output reg tx, output reg busy
);
    reg [31:0] count;
    reg [3:0] bit_index;
    reg [9:0] frame;
    always @(posedge clk) begin
        if(!rst_n) begin tx<=1; busy<=0; count<=0; bit_index<=0; frame<=10'h3ff; end
        else if(!busy) begin
            tx<=1;
            if(valid) begin
                frame<={1'b1,data,1'b0}; tx<=0; busy<=1;
                count<=CLKS_PER_BIT-1; bit_index<=0;
            end
        end else if(count!=0) count<=count-1;
        else if(bit_index==9) begin tx<=1; busy<=0; end
        else begin
            bit_index<=bit_index+1; frame<={1'b1,frame[9:1]};
            tx<=frame[1]; count<=CLKS_PER_BIT-1;
        end
    end
endmodule
