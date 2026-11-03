#include "gwx_ai.h"
#include "model_identity.h"
#ifndef CLOCK_HZ
#define CLOCK_HZ 27000000u
#endif
#define REG(a) (*(volatile uint32_t *)(a))
#define AI(a) REG(0x40000700u+(a))
static int initialized;static int accelerator_failed;
static void out(char c){while(REG(0x40000004u)&1u){}REG(0x40000000u)=(unsigned char)c;}
static void text(const char *s){while(*s)out(*s++);}
static void hex(uint32_t x){const char h[]="0123456789ABCDEF";for(int i=7;i>=0;i--)out(h[(x>>(i*4))&15]);}
static void field(const char *s,uint32_t x){text(s);hex(x);text("\r\n");}
static uint64_t ticks(void){uint32_t low=REG(0x40000200u);return ((uint64_t)REG(0x40000204u)<<32)|low;}
static uint32_t crc32(const uint8_t *p,uint32_t n){uint32_t c=~0u;for(uint32_t i=0;i<n;i++){c^=p[i];for(int j=0;j<8;j++)c=(c>>1)^((0u-(c&1u))&0xedb88320u);}return ~c;}
static uint32_t cached_epoch;static const int8_t *cached_x;static int cached_valid;
static int32_t accelerated_dot(const int8_t *x,const uint8_t *w){
 if(accelerator_failed)return 0;
 typedef uint32_t alias_u32 __attribute__((may_alias));
 if(((uintptr_t)x|(uintptr_t)w)&3u){accelerator_failed=1;return 0;}
 const alias_u32 *xwords=(const alias_u32 *)(const void *)x,*weights=(const alias_u32 *)(const void *)w;
 uint32_t began=REG(0x40000200u);
 while(!(AI(0x10)&1u))if(REG(0x40000200u)-began>CLOCK_HZ){accelerator_failed=1;return 0;}
 uint32_t epoch=gwx_ai_quant_epoch();
 if(!cached_valid||cached_epoch!=epoch||cached_x!=x){
  for(unsigned i=0;i<16;i++)AI(0x40+i*4)=xwords[i];
  cached_epoch=epoch;cached_x=x;cached_valid=1;
 }
 for(unsigned i=0;i<8;i++)AI(0x80+i*4)=weights[i];
 AI(0xa0)=1;
 uint32_t start=REG(0x40000200u);
 while(!(AI(0x10)&2u))if(REG(0x40000200u)-start>CLOCK_HZ){accelerator_failed=1;cached_valid=0;return 0;}
 uint32_t status=AI(0x10);int32_t result=(int32_t)AI(0x14);AI(0x18)=1;
 if(status&4u){accelerator_failed=1;cached_valid=0;}
 return result;
}
void gwx_ai_capture(const uint8_t *samples,uint32_t channel,uint32_t period,uint32_t accelerated,uint32_t record_id){
 text("GWX AI BEGIN\r\nEXEC=FPGA_RV32I\r\n");field("RECORD=",record_id);field("CHANNEL=",channel);
 field("CLOCK_HZ=",CLOCK_HZ);field("MODEL_CRC=",GWX_MODEL_CRC32);field("ACCEL=",accelerated);
 field("EXPECTED_PERIOD=",period);
 if(!initialized){
  if(crc32((const uint8_t *)0x30000000u,GWX_AI_MODEL_BYTES)!=GWX_MODEL_CRC32||gwx_ai_init((const void *)0x30000000u,GWX_AI_MODEL_BYTES)){
   text("STATUS=MODEL_ERROR\r\nGWX AI END\r\n");return;
  }
  initialized=1;
 }
 if(AI(0x1c)!=0x47575134u){text("STATUS=ACCEL_ID_ERROR\r\nGWX AI END\r\n");return;}
 char prompt[160];uint16_t tokens[128];struct gwx_ai_result r={0};
 if(gwx_ai_summary(samples,channel,period,prompt)<0){text("STATUS=OUT_OF_DOMAIN\r\nGWX AI END\r\n");return;}
 int n=gwx_ai_tokens(prompt,tokens,128);
 if(n<=0||n>=64){text("STATUS=CONTEXT_ERROR\r\nGWX AI END\r\n");return;}
 field("RUNTIME_VERSION=",2);field("PROMPT_TOKENS=",(uint32_t)n);field("WORKING_BYTES=",gwx_ai_working_bytes());
 accelerator_failed=0;cached_valid=0;uint64_t start=ticks();int status=gwx_ai_run(tokens,n,accelerated?accelerated_dot:0,&r);uint64_t elapsed=ticks()-start;
 field("INFERENCE_TICKS_LOW=",(uint32_t)elapsed);field("INFERENCE_TICKS_HIGH=",(uint32_t)(elapsed>>32));
 if(status||accelerator_failed){text("STATUS=INFERENCE_ERROR\r\nGWX AI END\r\n");return;}
 field("TOKEN=",(uint32_t)r.token);field("EOS=",(uint32_t)r.eos);field("LABEL=",(uint32_t)r.label);
 field("SCORE_PERMILLE=",(uint32_t)(r.score*1000.0f));field("DOT_GROUPS=",r.groups);
 text(r.label>=0&&r.eos==2?"STATUS=PASS\r\n":"STATUS=INVALID_OUTPUT\r\n");text("GWX AI END\r\n");
}
