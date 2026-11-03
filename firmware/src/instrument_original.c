/* RV32I instrument. Packet: A5 5A 01 CMD DIVlo DIVhi MASK VALUE TRIG MONITOR
 * PMIN PMAX MISSING MODE CHANNEL XOR. CMD 1 external, 2 internal, 3 suite.
 * The instrument never drives an external sampling-header output.
 */
typedef unsigned int u32;
typedef unsigned char u8;
#define REG(a) (*(volatile u32 *)(a))
#ifndef CLOCK_HZ
#define CLOCK_HZ 27000000u
#endif
#define CAP(a) REG(0x40000400u+(a))
#define NO_INDEX 0xffffffffu
#ifndef EXIT_AFTER_SUITE
#define EXIT_AFTER_SUITE 0
#endif
#ifndef BOOT_SUITE
#define BOOT_SUITE 1
#endif
#ifndef COREMARK_ITERATIONS
#define COREMARK_ITERATIONS 0
#endif
extern int gwx_coremark_run(void);
extern volatile int seed1_volatile,seed2_volatile,seed3_volatile,seed4_volatile;
extern unsigned long long get_time(void);
enum {NONE=0,STUCK=1,MISSING=2,PERIOD=3};
struct fault {u32 code,index,gap;};
struct config {u32 cmd,divider,mask,value,trigger,monitor,pmin,pmax,missing,mode,channel;};
static u8 samples[64];
static struct fault faults[8];
static u32 record_id;
static const char digits[]="0123456789ABCDEF";
static void putc_uart(char c){while(REG(0x40000004u)&1u){} REG(0x40000000u)=(u8)c;}
static void puts_uart(const char *s){while(*s)putc_uart(*s++);}
static void hex8(u32 x){putc_uart(digits[(x>>4)&15u]);putc_uart(digits[x&15u]);}
static void hex32(u32 x){hex8(x>>24);hex8(x>>16);hex8(x>>8);hex8(x);}
static void field(const char *name,u32 x){puts_uart(name);hex32(x);puts_uart("\r\n");}
static const char *fault_name(u32 c){return c==STUCK?"STUCK":c==MISSING?"MISSING_PULSE":c==PERIOD?"PERIOD":"NONE";}
static void header(void){puts_uart("GWX DET8 v0.2\r\n");field("ID=",++record_id);field("CLOCK_HZ=",CLOCK_HZ);}
static void error_record(const char *reason){header();puts_uart("CAPTURE=CONFIG_ERROR\r\nERROR=");puts_uart(reason);puts_uart("\r\nEND\r\n");}
static void detect(const struct config *c){
 for(u32 ch=0;ch<8;ch++){
  faults[ch].code=NONE;faults[ch].index=NO_INDEX;faults[ch].gap=0;
  if(!(c->monitor&(1u<<ch)))continue;
  u32 previous=(samples[0]>>ch)&1u,transitions=0,rises=0,last=NO_INDEX;
  for(u32 i=1;i<64;i++){
   u32 level=(samples[i]>>ch)&1u;if(level!=previous)transitions++;
   if(level&&!previous){
    if(last!=NO_INDEX&&faults[ch].code==NONE){
     u32 gap=i-last;
     if(gap>=c->missing){faults[ch].code=MISSING;faults[ch].index=last+((c->pmin+c->pmax)>>1);faults[ch].gap=gap;}
     else if(gap<c->pmin||gap>c->pmax){faults[ch].code=PERIOD;faults[ch].index=i;faults[ch].gap=gap;}
    }
    last=i;rises++;
   }
   previous=level;
  }
  if(transitions<2){faults[ch].code=STUCK;faults[ch].index=0;faults[ch].gap=0;}
  else if(rises<2&&faults[ch].code==NONE){faults[ch].code=MISSING;faults[ch].index=0;faults[ch].gap=0;}
 }
}
static void capture(const struct config *c){
 CAP(8)=c->divider;CAP(12)=c->mask;CAP(16)=c->value;CAP(20)=c->trigger;
 REG(0x40000608u)=c->divider;REG(0x40000100u)=1;
 REG(0x40000600u)=c->cmd==1?0u:1u|(c->mode<<1)|(c->channel<<4);
 CAP(0)=1;u32 started=REG(0x40000200u);
 while(!(CAP(4)&4u)){
  if(REG(0x40000200u)-started>=CLOCK_HZ){
   CAP(0)=2;REG(0x40000100u)=8;header();puts_uart("CAPTURE=TIMEOUT\r\nEND\r\n");return;
  }
 }
 u32 sum=0;for(u32 i=0;i<64;i++){samples[i]=(u8)REG(0x20000000u+(i<<2));sum+=samples[i];}
 u32 hw=CAP(28),count=CAP(24);REG(0x40000320u)=1;
 u32 cyc=REG(0x40000310u),ret=REG(0x40000300u),br=REG(0x40000314u);
 u32 ds=REG(0x40000318u),fs=REG(0x4000031cu),fw=REG(0x40000328u),fl=REG(0x4000032cu);
 detect(c);
 u32 dcyc=REG(0x40000310u)-cyc,dret=REG(0x40000300u)-ret,dbr=REG(0x40000314u)-br;
 u32 dds=REG(0x40000318u)-ds,dfs=REG(0x4000031cu)-fs,dfw=REG(0x40000328u)-fw,dfl=REG(0x4000032cu)-fl;
 REG(0x40000320u)=0;header();puts_uart(c->cmd==1?"SOURCE=EXTERNAL\r\n":"SOURCE=INTERNAL\r\n");
 field("SCENARIO=",c->mode);field("INJECT_CHANNEL=",c->channel);field("DIVIDER=",c->divider);
 field("TRIGGER_MASK=",c->mask);field("TRIGGER_VALUE=",c->value);field("TRIGGER_MODE=",c->trigger);
 puts_uart("DATA=");for(u32 i=0;i<64;i++)hex8(samples[i]);puts_uart("\r\n");
 field("COUNT=",count);field("SUM=",sum);field("HW_SUM=",hw);
 if(count!=64||sum!=hw){REG(0x40000100u)=8;puts_uart("CAPTURE=FAIL\r\nEND\r\n");return;}
 puts_uart("CAPTURE=PASS\r\nMONITOR_MASK=");hex8(c->monitor);puts_uart("\r\n");
 field("PERIOD_MIN=",c->pmin);field("PERIOD_MAX=",c->pmax);field("MISSING_GAP=",c->missing);
 u32 n=0;for(u32 ch=0;ch<8;ch++)if(faults[ch].code)n++;field("FAULT_COUNT=",n);
 for(u32 ch=0;ch<8;ch++){
  puts_uart("CH");hex8(ch);putc_uart('=');puts_uart(fault_name(faults[ch].code));
  putc_uart(',');hex32(faults[ch].index);putc_uart(',');hex32(faults[ch].gap);puts_uart("\r\n");
 }
 field("ANALYSIS_CYCLES=",dcyc);field("ANALYSIS_RETIRED=",dret);field("ANALYSIS_BRANCHES=",dbr);
 field("ANALYSIS_DATA_STALLS=",dds);field("ANALYSIS_FETCH_STALLS=",dfs);field("ANALYSIS_FORWARD_EVENTS=",dfw);field("ANALYSIS_FLUSH_EVENTS=",dfl);
 field("CPU_OPTIONS=",REG(0x40000330u));u32 traces=REG(0x40000324u);field("TRACE_COUNT=",traces);
 for(u32 i=0;i<traces;i++){
  puts_uart("TRACE=");for(u32 j=0;j<4;j++){if(j)putc_uart(',');hex32(REG(0x20001000u+(i<<4)+(j<<2)));}puts_uart("\r\n");
 }
 puts_uart("END\r\n");REG(0x40000100u)=n?4u:2u;
}
static void defaults(struct config *c){
 c->cmd=2;c->divider=270;c->mask=255;c->value=16;c->trigger=0;c->monitor=255;
 c->pmin=6;c->pmax=10;c->missing=14;c->mode=0;c->channel=0;
}
static void suite(void){
 struct config c;defaults(&c);capture(&c);
 for(u32 mode=1;mode<=4;mode++)for(u32 ch=0;ch<8;ch++){c.mode=mode;c.channel=ch;capture(&c);}
}
static u32 read_byte(u8 *out,u32 timeout){
 u32 start=REG(0x40000200u);
 while(!(REG(0x4000000cu)&1u))if(timeout&&REG(0x40000200u)-start>=CLOCK_HZ)return 0;
 *out=(u8)REG(0x40000008u);return 1;
}
static void ready(void){puts_uart("GWX READY v0.2\r\n");}
int main(void){
 if(BOOT_SUITE){suite();}
 if(EXIT_AFTER_SUITE){return 0;}
 ready();
 for(;;){
  u8 pkt[16],x=0;read_byte(&pkt[0],0);if(pkt[0]!=0xa5)continue;
  if(!read_byte(&pkt[1],1)||pkt[1]!=0x5a)continue;
  u32 ok=1;for(u32 i=2;i<16;i++)if(!read_byte(&pkt[i],1)){ok=0;break;}
  if(ok)for(u32 i=0;i<16;i++)x^=pkt[i];
  if(!ok||x||pkt[2]!=1){error_record("BAD_PACKET");ready();continue;}
  struct config c;
  c.cmd=pkt[3];c.divider=(u32)pkt[4]|((u32)pkt[5]<<8);c.mask=pkt[6];c.value=pkt[7];
  c.trigger=pkt[8];c.monitor=pkt[9];c.pmin=pkt[10];c.pmax=pkt[11];c.missing=pkt[12];c.mode=pkt[13];c.channel=pkt[14];
  if(c.cmd<1||c.cmd>4||c.divider==0||c.trigger>2||!c.monitor||c.pmin<2||c.pmax<c.pmin||c.missing<=c.pmax||c.missing>63||c.mode>4||c.channel>7){error_record("RANGE");ready();continue;}
  if(c.cmd==1&&!(REG(0x40000604u)&2u)){error_record("SOURCE_UNAVAILABLE");ready();continue;}
  if(c.cmd==4){
   puts_uart("GWX COREMARK BEGIN\r\n");field("MODE=",c.mode);field("CLOCK_HZ=",CLOCK_HZ);field("CPU_OPTIONS=",REG(0x40000330u));
   seed1_volatile=c.mode?0x3415:0;seed2_volatile=seed1_volatile;seed3_volatile=0x66;seed4_volatile=COREMARK_ITERATIONS;
   int result=gwx_coremark_run();unsigned long long ticks=get_time();
   field("TICKS_LOW=",(u32)ticks);field("TICKS_HIGH=",(u32)(ticks>>32));field("COREMARK_RETURN=",(u32)result);
   puts_uart("GWX COREMARK END\r\n");
  }else if(c.cmd==3)suite();else capture(&c);ready();
 }
}
