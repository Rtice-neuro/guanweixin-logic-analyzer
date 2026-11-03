#include "Vgwx_perf.h"
#include "verilated.h"
#include <cstdio>
#include <cstdint>
#include <string>
#include <vector>
#include <deque>
#include <cstdlib>
int main(int argc,char**argv){
 Verilated::commandArgs(argc,argv);Vgwx_perf d;
 const int mode=argc>1?std::atoi(argv[1]):0;
 if(mode<0||mode>1)return 4;
 std::string raw_name="uart_ai.bin";
 FILE* raw=std::fopen(raw_name.c_str(),"wb");if(!raw)return 5;
 std::string line;bool measuring=false;uint64_t measured=0,ret=0,ds=0,fs=0;uint32_t last_pc=0;
 std::string line_copy;int ready=0,rxstate=0,rxwait=0,rxbit=0,value=0,previous=1;
 uint64_t send_start=0;bool sent=false;std::vector<int>bits;
 uint8_t command[16]={0xa5,0x5a,1,4,14,1,255,16,0,255,6,10,14,0,0,0};command[3]=5;command[13]=3;
 uint8_t checksum=0;for(int i=0;i<15;i++)checksum^=command[i];
 for(int i=0;i<16;i++){uint8_t b=i==15?checksum:command[i];bits.push_back(0);for(int j=0;j<8;j++)bits.push_back((b>>j)&1);bits.push_back(1);}
 std::deque<std::pair<uint32_t,uint32_t>>recent;
 std::vector<uint64_t> pc_cycles(12288),pc_retired(12288);
 for(uint64_t n=0;n<2000000000ULL;n++){
  d.rst_n=n>=12;d.rx=1;
  if(send_start && n>=send_start){uint64_t k=(n-send_start)/8;if(k<bits.size())d.rx=bits[k];else sent=true;}
  d.clk=0;d.eval();d.clk=1;d.eval();
  if(d.trace_valid)last_pc=d.trace_pc;
  if(measuring){measured++;if(d.trace_valid){ret++;if(d.trace_pc/4<pc_retired.size())pc_retired[d.trace_pc/4]++;}if(d.pc/4<pc_cycles.size())pc_cycles[d.pc/4]++;}
  if(d.trace_valid){recent.emplace_back(d.trace_pc,d.trace_insn);if(recent.size()>20)recent.pop_front();}
  if(n>12){
   if(!rxstate && previous && !d.tx){rxstate=1;rxwait=12;rxbit=0;value=0;}
   else if(rxstate && --rxwait==0){
    if(rxbit<8){value|=(d.tx?1:0)<<rxbit++;rxwait=8;}
    else{rxstate=0;std::putchar(value);std::fputc(value,raw);if(value=='\n'){
      if(line=="GWX AI BEGIN\r"){measuring=true;ds=d.data_stalls;fs=d.fetch_stalls;}
      if(line=="GWX AI END\r"){measuring=false;ds=d.data_stalls-ds;fs=d.fetch_stalls-fs;}
      if(line=="GWX READY v0.2\r"){ready++;if(ready==1)send_start=n+80;if(ready==2){std::fclose(raw);std::fflush(stdout);
       FILE*p=std::fopen("profile.csv","w");std::fprintf(p,"pc,cycles,retired\n");
       for(size_t i=0;i<pc_cycles.size();i++)if(pc_cycles[i])std::fprintf(p,"%08x,%llu,%llu\n",unsigned(i*4),(unsigned long long)pc_cycles[i],(unsigned long long)pc_retired[i]);std::fclose(p);
       std::fprintf(stderr,"PROFILE measured=%llu retired=%llu data_stalls=%llu fetch_stalls=%llu i_hits=%u i_misses=%u d_hits=%u d_misses=%u\n",(unsigned long long)measured,(unsigned long long)ret,(unsigned long long)ds,(unsigned long long)fs,d.i_hits,d.i_misses,d.d_hits,d.d_misses);
       std::fprintf(stderr,"PASS complete full-model RTL mode=%d cycles=%llu retired=%u\n",mode,(unsigned long long)n,d.retired);return 0;}}
      line.clear();
     }else line.push_back(char(value));}
   }
  }
  previous=d.tx;
  if(d.halted){std::fprintf(stderr,"HALTED cycle=%llu pc=%08x cause=%u retired=%u sent=%d\n",(unsigned long long)n,d.pc,d.cause,d.retired,sent);for(auto r:recent)std::fprintf(stderr,"TRACE %08x %08x\n",r.first,r.second);return 2;}
  if(n && n%10000000ULL==0){std::fflush(stdout);std::fprintf(stderr,"PROGRESS cycle=%llu pc=%08x retired=%u ready=%d\n",(unsigned long long)n,d.pc,d.retired,ready);}
 }
 std::fprintf(stderr,"TIMEOUT pc=%08x retired=%u ready=%d\n",d.pc,d.retired,ready);return 3;
}
