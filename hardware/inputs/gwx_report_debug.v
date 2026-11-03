`timescale 1ns/1ps
// Passive observer of CPU-committed UART report bytes. No bus/pin outputs.
// The ILA observes a REPLAY of the same 64 bytes sent to the host, NOT GPIO time.
// Latest validated frame repeats every 1024 clocks; first 512 clocks contain
// 64 samples held for 8 clocks each. Arm AFTER the website upload completes.
module gwx_report_debug(
 input wire clk,input wire rst_n,input wire byte_valid,input wire [7:0] byte_data,
 output reg [7:0] replay_data /* synthesis syn_preserve=1 */,output reg [5:0] replay_index /* synthesis syn_preserve=1 */,
 output reg replay_valid /* synthesis syn_preserve=1 */,output reg replay_start /* synthesis syn_preserve=1 */,
 output reg [31:0] record_id /* synthesis syn_preserve=1 */,output reg [31:0] injection_id /* synthesis syn_preserve=1 */,
 output reg [7:0] fault_mask /* synthesis syn_preserve=1 */,output reg [15:0] fault_codes /* synthesis syn_preserve=1 */,
 output reg [1:0] source /* synthesis syn_preserve=1 */,output reg frame_ok /* synthesis syn_preserve=1 */,output reg frame_error /* synthesis syn_preserve=1 */
);
 reg [127:0] prefix;
 reg [7:0] pos;
 reg numeric_active,numeric_good,data_line;
 reg [7:0] digits;
 reg [31:0] number;
 reg active,bad;
 reg [31:0] pending_id,pending_injection,expected_sum;
 reg [1:0] pending_source;
 reg [7:0] pending_mask,channels_seen;
 reg [15:0] pending_codes;
 reg seen_id,seen_injection,seen_source,seen_count,seen_sum,seen_wire_sum,seen_pass,seen_data;
 reg [7:0] memory [0:63];
 reg [7:0] nibbles;
 reg [3:0] high_nibble;
 reg [31:0] data_sum;
 reg [9:0] replay_tick;
 wire hex_valid=(byte_data>="0"&&byte_data<="9")||(byte_data>="A"&&byte_data<="F")||(byte_data>="a"&&byte_data<="f");
 wire [3:0] hex_digit=(byte_data<="9")?(byte_data-8'h30):((byte_data<=8'h46)?(byte_data-8'h37):(byte_data-8'h57));
 wire good_number=numeric_active&&numeric_good&&digits==8;
 always @(posedge clk) begin
  if(!rst_n)begin
   prefix<=0;pos<=0;numeric_active<=0;numeric_good<=1;data_line<=0;digits<=0;number<=0;
   active<=0;bad<=0;pending_id<=0;pending_injection<=0;expected_sum<=0;pending_source<=0;
   pending_mask<=0;channels_seen<=0;pending_codes<=0;
   seen_id<=0;seen_injection<=0;seen_source<=0;seen_count<=0;seen_sum<=0;seen_wire_sum<=0;seen_pass<=0;seen_data<=0;
   nibbles<=0;high_nibble<=0;data_sum<=0;replay_tick<=0;
   replay_data<=0;replay_index<=0;replay_valid<=0;replay_start<=0;
   record_id<=0;injection_id<=0;fault_mask<=0;fault_codes<=0;source<=0;frame_ok<=0;frame_error<=0;
  end else begin
   replay_start<=0;replay_valid<=0;
   if(frame_ok)begin
    replay_tick<=replay_tick+1'b1;
    replay_start<=replay_tick==0;
    replay_valid<=!replay_tick[9];
    replay_index<=replay_tick[8:3];
    replay_data<=memory[replay_tick[8:3]];
   end
   if(byte_valid&&byte_data!=8'h0d)begin
    if(byte_data==8'h0a)begin
     if(pos==13&&prefix[127:24]=="GWX DET8 v0.2")begin
      active<=1;bad<=0;frame_ok<=0;frame_error<=0;replay_valid<=0;replay_start<=0;
      pending_id<=0;pending_injection<=0;pending_source<=0;pending_mask<=0;pending_codes<=0;channels_seen<=0;
      seen_id<=0;seen_injection<=0;seen_source<=0;seen_count<=0;seen_sum<=0;seen_wire_sum<=0;seen_pass<=0;seen_data<=0;
      nibbles<=0;data_sum<=0;expected_sum<=0;
     end else if(active)begin
      if(prefix[127:104]=="ID=")begin
       if(pos==11&&good_number&&!seen_id)begin pending_id<=number;seen_id<=1;end else bad<=1;
      end else if(prefix[127:24]=="INJECTION_ID=")begin
       if(pos==21&&good_number&&!seen_injection)begin pending_injection<=number;seen_injection<=1;end else bad<=1;
      end else if(prefix[127:72]=="SOURCE=")begin
       seen_source<=1;
       if(pos==15&&prefix[127:8]=="SOURCE=INJECTED")pending_source<=1;
       else if(pos==15&&prefix[127:8]=="SOURCE=INTERNAL")pending_source<=2;
       else if(pos==15&&prefix[127:8]=="SOURCE=EXTERNAL")pending_source<=3;
       else bad<=1;
      end else if(prefix[127:88]=="DATA=")begin
       if(pos==133&&data_line&&nibbles==128&&!seen_data)seen_data<=1;else bad<=1;
      end else if(prefix[127:80]=="COUNT=")begin
       if(pos==14&&good_number&&number==64&&!seen_count)seen_count<=1;else bad<=1;
      end else if(prefix[127:96]=="SUM=")begin
       if(pos==12&&good_number&&!seen_sum)begin seen_sum<=1;expected_sum<=number;end else bad<=1;
      end else if(prefix[127:56]=="UART_SUM="||prefix[127:72]=="HW_SUM=")begin
       if(good_number&&number==data_sum&&!seen_wire_sum)seen_wire_sum<=1;else bad<=1;
      end else if(prefix[127:64]=="CAPTURE=")begin
       if(pos==12&&prefix[127:32]=="CAPTURE=PASS")seen_pass<=1;else bad<=1;
      end else if(prefix[127:112]=="CH")begin
       if(prefix[111:104]=="0"&&prefix[103:96]>="0"&&prefix[103:96]<="7"&&prefix[95:88]=="=" )begin
        // CH00=value: channel units byte 3, separator byte 4, value byte 5.
        if(!channels_seen[prefix[98:96]]&&
          (prefix[87:56]=="NONE"||prefix[87:48]=="STUCK"||prefix[87:40]=="PERIOD"||prefix[87:0]=="MISSING_PUL"))begin
         channels_seen[prefix[98:96]]<=1;
         pending_mask[prefix[98:96]]<=prefix[87:80]!="N";
         case(prefix[87:80])
          "N":pending_codes[prefix[98:96]*2+:2]<=0;
          "S":pending_codes[prefix[98:96]*2+:2]<=1;
          "M":pending_codes[prefix[98:96]*2+:2]<=2;
          "P":pending_codes[prefix[98:96]*2+:2]<=3;
         endcase
        end else bad<=1;
       end else bad<=1;
      end else if(pos==3&&prefix[127:104]=="END")begin
       active<=0;
       if(!bad&&seen_id&&seen_source&&seen_count&&seen_sum&&seen_wire_sum&&seen_pass&&seen_data&&channels_seen==8'hff&&expected_sum==data_sum&&(pending_source!=1||seen_injection))begin
        record_id<=pending_id;injection_id<=pending_injection;source<=pending_source;
        fault_mask<=pending_mask;fault_codes<=pending_codes;frame_ok<=1;frame_error<=0;replay_tick<=0;
       end else begin frame_ok<=0;frame_error<=1;end
      end
     end
     prefix<=0;pos<=0;numeric_active<=0;numeric_good<=1;digits<=0;number<=0;data_line<=0;
    end else begin
     if(pos<16)prefix[127-pos*8-:8]<=byte_data;
     if(pos<255)pos<=pos+1'b1;else if(active)bad<=1;
     if(byte_data=="=")begin numeric_active<=1;numeric_good<=1;digits<=0;number<=0;end
     else if(numeric_active)begin
      if(hex_valid)begin if(digits<255)digits<=digits+1'b1;number<={number[27:0],hex_digit};end
      else numeric_good<=0;
     end
     if(active&&pos==4&&prefix[127:96]=="DATA"&&byte_data=="=")begin data_line<=1;nibbles<=0;data_sum<=0;end
     else if(active&&data_line)begin
      if(!hex_valid||nibbles>=128)bad<=1;
      else begin
       nibbles<=nibbles+1'b1;
       if(!nibbles[0])high_nibble<=hex_digit;
       else begin memory[nibbles[6:1]]<={high_nibble,hex_digit};data_sum<=data_sum+{high_nibble,hex_digit};end
      end
     end
    end
   end
  end
 end
endmodule
