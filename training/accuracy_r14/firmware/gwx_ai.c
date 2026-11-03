/* Complete, allocation-free diagnostic Transformer runtime.
 * Q4 matrix weights, Q8 dynamic activations, FP16 stored KV, FP32 math.
 * Full pretrained geometry retained. No host callback except optional dot64 IP.
 */
#include "gwx_ai.h"
#include "rope_data.h"
#include "tokenizer_data.h"

typedef union {uint32_t u;float f;} bits32;
struct matrix {const uint8_t *q;const float *scale;int rows,cols;};
static struct matrix matrices[36];
static const float *attnorm,*ffnorm,*lastnorm;
static struct {
 uint16_t keys[5][64][32],values[5][64][32];
 float x[64],a[64],q[64],k[32],v[32],b[64],c[64];
 float h[192],gate[192],attention[8][64],logits[512];
 int8_t quantized[192];float scales[3];
 uint32_t groups;int valid;
} state;
static gwx_dot64_fn dot_hook;
static uint32_t quant_epoch;
uint32_t gwx_ai_quant_epoch(void){return quant_epoch;}

static float absf(float x){return x<0?-x:x;}
static float inverse_sqrt(float x){
 bits32 b;b.f=x;b.u=0x5f3759dfu-(b.u>>1);float y=b.f;
 for(int i=0;i<4;i++)y=y*(1.5f-0.5f*x*y*y);
 return y;
}
static float exp_approx(float x){
 if(x<-80.0f)return 0.0f;if(x>80.0f)x=80.0f;
 float t=x*1.44269504089f;int n=(int)(t+(t>=0?.5f:-.5f));
 float r=(x-n*0.693359375f)-n*(-0.0002121944400547f);
 float p=1.0f+r*(1.0f+r*(.5f+r*(.166666666667f+r*(.041666666667f+r*(.008333333333f+r*.001388888889f)))));
 bits32 b;b.u=(uint32_t)(n+127)<<23;return p*b.f;
}
static uint16_t half_store(float f){
 bits32 b;b.f=f;uint32_t sign=(b.u>>16)&0x8000u,m=b.u&0x7fffffu;int e=(int)((b.u>>23)&255)-127+15;
 if(e>=31){state.valid=0;return (uint16_t)(sign|0x7c00u);}
 if(e<=0){
  if(e< -10)return (uint16_t)sign;
  m|=0x800000u;int shift=14-e;uint32_t q=m>>shift,tail=m&((1u<<shift)-1u),half=1u<<(shift-1);
  if(tail>half||(tail==half&&(q&1)))q++;
  return (uint16_t)(sign|q);
 }
 uint32_t q=m>>13,tail=m&8191u;
 if(tail>4096u||(tail==4096u&&(q&1)))q++;
 if(q==1024u){q=0;e++;if(e>=31)state.valid=0;}
 return (uint16_t)(sign|((uint32_t)e<<10)|q);
}
static float half_load(uint16_t h){
 bits32 b;uint32_t sign=(uint32_t)(h&0x8000u)<<16,m=h&1023u;int e=(h>>10)&31;
 if(!e){if(!m){b.u=sign;return b.f;}e=-14;while(!(m&1024u)){m<<=1;e--;}m&=1023u;b.u=sign|((uint32_t)(e+127)<<23)|(m<<13);}
 else b.u=sign|((uint32_t)(e-15+127)<<23)|(m<<13);
 return b.f;
}
static int nibble(const uint8_t *p,int index){unsigned n=(p[index>>1]>>((index&1)*4))&15u;return n>=8?(int)n-16:(int)n;}
int32_t gwx_ai_dot_reference(const int8_t *x,const uint8_t *p){int32_t sum=0;for(int i=0;i<64;i++)sum+=(int32_t)x[i]*nibble(p,i);return sum;}
static void quantize(const float *x,int n){
 quant_epoch++;
 for(int g=0;g<n/64;g++){
  float max=0;for(int i=0;i<64;i++){float a=absf(x[g*64+i]);if(a>max)max=a;}
  float scale=max>0?max/127.0f:1.0f;state.scales[g]=scale;
  for(int i=0;i<64;i++){float a=x[g*64+i]/scale;int q=(int)(a+(a>=0?.5f:-.5f));if(q>127)q=127;if(q< -127)q=-127;state.quantized[g*64+i]=(int8_t)q;}
 }
}
static void matmul(float *out,int which){
 const struct matrix *m=&matrices[which];int groups=m->cols/64;
 // Interchange independent rows: each row retains its original group order.
 // The hardware activation vector can now be reused for every row in a group.
 for(int row=0;row<m->rows;row++)out[row]=0;
 for(int g=0;g<groups;g++)for(int row=0;row<m->rows;row++){
  const uint8_t *w=m->q+(row*groups+g)*32;const int8_t *x=state.quantized+g*64;
  int32_t sum=dot_hook?dot_hook(x,w):gwx_ai_dot_reference(x,w);state.groups++;
  out[row]+=(float)sum*m->scale[row*groups+g]*state.scales[g];
 }
}
static void norm(float *out,const float *x,const float *w){float sum=0;for(int i=0;i<64;i++)sum+=x[i]*x[i];float scale=inverse_sqrt(sum/64.0f+1e-5f);for(int i=0;i<64;i++)out[i]=w[i]*(scale*x[i]);}
static void rotate(float *x,int n,int pos){for(int i=0;i<n;i+=2){float a=x[i],b=x[i+1];int j=i&7;float c=gwx_rope[pos][j],s=gwx_rope[pos][j+1];x[i]=a*c-b*s;x[i+1]=a*s+b*c;}}
static int forward(int token,int pos,int produce_logits){
 if(token<0||token>=512||pos<0||pos>=64)return -1;
 const struct matrix *emb=&matrices[0];for(int i=0;i<64;i++)state.x[i]=(float)nibble(emb->q,token*64+i)*emb->scale[token];
 for(int l=0;l<5;l++){
  norm(state.a,state.x,attnorm+l*64);quantize(state.a,64);
  matmul(state.q,1+l);matmul(state.k,6+l);matmul(state.v,11+l);rotate(state.q,64,pos);rotate(state.k,32,pos);
  for(int i=0;i<32;i++){state.keys[l][pos][i]=half_store(state.k[i]);state.values[l][pos][i]=half_store(state.v[i]);}
  for(int head=0;head<8;head++){
   int base=(head/2)*8;float max=-1e30f;
   for(int t=0;t<=pos;t++){float sum=0;for(int i=0;i<8;i++)sum+=state.q[head*8+i]*half_load(state.keys[l][t][base+i]);sum*=0.353553390593f;state.attention[head][t]=sum;if(sum>max)max=sum;}
   float total=0;for(int t=0;t<=pos;t++){state.attention[head][t]=exp_approx(state.attention[head][t]-max);total+=state.attention[head][t];}
   for(int i=0;i<8;i++)state.b[head*8+i]=0;
   for(int t=0;t<=pos;t++){float a=state.attention[head][t]/total;for(int i=0;i<8;i++)state.b[head*8+i]+=a*half_load(state.values[l][t][base+i]);}
  }
  quantize(state.b,64);matmul(state.c,16+l);for(int i=0;i<64;i++)state.x[i]+=state.c[i];
  norm(state.a,state.x,ffnorm+l*64);quantize(state.a,64);matmul(state.h,21+l);matmul(state.gate,31+l);
  for(int i=0;i<192;i++){float x=state.h[i];state.h[i]=(x*(1.0f/(1.0f+exp_approx(-x))))*state.gate[i];}
  quantize(state.h,192);matmul(state.c,26+l);for(int i=0;i<64;i++)state.x[i]+=state.c[i];
 }
 if(produce_logits){norm(state.a,state.x,lastnorm);quantize(state.a,64);matmul(state.logits,0);}
 return state.valid?0:-2;
}
int gwx_ai_init(const void *model,uint32_t bytes){
 if(bytes!=GWX_AI_MODEL_BYTES||((uintptr_t)model&3u))return -1;
 const uint32_t *h=(const uint32_t *)model;
 if(h[0]!=0x34515747u||h[1]!=64||h[2]!=192||h[3]!=5||h[4]!=8||h[5]!=4||h[6]!=512||h[7]!=64)return -2;
 const uint8_t *p=(const uint8_t *)model+256;attnorm=(const float *)p;ffnorm=attnorm+320;lastnorm=ffnorm+320;p+=704*4;
 for(int i=0;i<36;i++){
  int rows=i==0?512:i<=5?64:i<=15?32:i<=20?64:i<=25?192:i<=30?64:192;
  int cols=(i>=26&&i<=30)?192:64;
  matrices[i].q=p;matrices[i].rows=rows;matrices[i].cols=cols;p+=rows*cols/2;
  matrices[i].scale=(const float *)p;p+=rows*cols/64*4;
 }
 if((uint32_t)(p-(const uint8_t *)model)!=bytes)return -3;
 return 0;
}
int gwx_ai_run(const uint16_t *tokens,int count,gwx_dot64_fn accelerator,struct gwx_ai_result *result){
 if(!tokens||!result||count<=0||count>=64)return -1;
 dot_hook=accelerator;state.valid=1;state.groups=0;
 for(int pos=0;pos<count;pos++)if(forward(tokens[pos],pos,pos==count-1))return -2;
 int best=0;for(int i=1;i<512;i++)if(state.logits[i]>state.logits[best])best=i;
 float total=0;for(int i=0;i<512;i++)total+=exp_approx(state.logits[i]-state.logits[best]);
 result->token=best;result->score=1.0f/total;result->label=-1;
 for(int i=0;i<6;i++)if(best==gwx_code_ids[i])result->label=i;
 if(forward(best,count,1))return -3;
 best=0;for(int i=1;i<512;i++)if(state.logits[i]>state.logits[best])best=i;
 result->eos=best;result->groups=state.groups;
 return 0;
}
uint32_t gwx_ai_working_bytes(void){return sizeof(state)+sizeof(matrices);}

static int slen(const char *s){int n=0;while(s[n])n++;return n;}
static int equal(const char *a,const char *b){while(*a&&*b&&*a==*b){a++;b++;}return *a==*b;}
static int lookup(const char *s){for(int i=0;i<512;i++)if(equal(s,gwx_vocab[i]))return i;return -1;}
int gwx_ai_tokens(const char *text,uint16_t *out,int capacity){
 if(!text||!out||capacity<2)return -1;int n=0;out[n++]=1;
 if(*text){int id=lookup(" ");if(id<0)return -1;out[n++]=(uint16_t)id;}
 for(const unsigned char *p=(const unsigned char *)text;*p;p++){
  if(*p>=128||n>=capacity)return -1;char one[2]={(char)*p,0};int id=lookup(one);out[n++]=(uint16_t)(id<0?*p+3:id);
 }
 for(;;){int best=-1,id=-1;float score=-1e30f;
  for(int i=0;i<n-1;i++){
   const char *a=gwx_vocab[out[i]],*b=gwx_vocab[out[i+1]];int na=slen(a),nb=slen(b);if(na+nb>=128)continue;
   char s[128];int k=0;for(int j=0;j<na;j++)s[k++]=a[j];for(int j=0;j<nb;j++)s[k++]=b[j];s[k]=0;
   int x=lookup(s);if(x>=0&&gwx_scores[x]>score){best=i;id=x;score=gwx_scores[x];}
  }
  if(best<0)break;out[best]=(uint16_t)id;for(int i=best+1;i<n-1;i++)out[i]=out[i+1];n--;
 }
 return n;
}
static int decimal(char *out,unsigned x){char r[10];int n=0;do{r[n++]=(char)('0'+x%10);x/=10;}while(x);for(int i=0;i<n;i++)out[i]=r[n-1-i];return n;}
int gwx_ai_summary(const uint8_t samples[64],unsigned channel,unsigned period,char out[160]){
 if(!samples||!out||channel>7||period<4||period>16)return -1;
 unsigned high=0,edges=0;int previous=(samples[0]>>channel)&1,last=-1;unsigned gaps[32],ngaps=0;
 high=(unsigned)previous;
 for(int i=1;i<64;i++){int bit=(samples[i]>>channel)&1;high+=(unsigned)bit;if(bit!=previous)edges++;if(bit&&!previous){if(last>=0){unsigned g=(16u*(unsigned)(i-last)+period/2)/period;gaps[ngaps++]=g>63?63:g;}last=i;}previous=bit;}
 int n=0;out[n++]='h';n+=decimal(out+n,high);out[n++]=' ';out[n++]='e';n+=decimal(out+n,edges);out[n++]=' ';out[n++]='g';
 for(unsigned i=0;i<ngaps;i++){if(i)out[n++]=',';n+=decimal(out+n,gaps[i]);}
 const char suffix[]="\nanswer:";for(unsigned i=0;i<sizeof(suffix);i++)out[n++]=suffix[i];
 return n-1;
}
