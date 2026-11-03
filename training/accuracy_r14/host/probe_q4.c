#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include "../firmware/gwx_ai.h"
int main(int argc,char **argv){
 if(argc!=4)return 2;FILE *m=fopen(argv[1],"rb");if(!m)return 3;
 void *weights=malloc(GWX_AI_MODEL_BYTES);if(!weights)return 4;
 if(fread(weights,1,GWX_AI_MODEL_BYTES,m)!=GWX_AI_MODEL_BYTES||fgetc(m)!=EOF)return 5;fclose(m);
 if(gwx_ai_init(weights,GWX_AI_MODEL_BYTES))return 6;
 FILE *in=fopen(argv[2],"r"),*out=fopen(argv[3],"w");if(!in||!out)return 7;
 char id[80];int n,want;uint16_t tokens[128];
 fprintf(out,"id,expected_token,predicted_token,eos_token,label,score,groups,host_ms\n");
 while(fscanf(in,"%79s %d %d",id,&n,&want)==3){
  if(n<=0||n>=64)return 8;for(int i=0;i<n;i++){unsigned t;if(fscanf(in,"%u",&t)!=1||t>=512)return 9;tokens[i]=(uint16_t)t;}
  struct gwx_ai_result r;clock_t start=clock();if(gwx_ai_run(tokens,n,NULL,&r))return 10;
  double ms=1000.0*(clock()-start)/CLOCKS_PER_SEC;
  fprintf(out,"%s,%d,%d,%d,%d,%.9g,%u,%.6f\n",id,want,r.token,r.eos,r.label,r.score,r.groups,ms);
 }
 fclose(in);fclose(out);free(weights);printf("PASS HOST Q4 KV16 working_bytes=%u\n",gwx_ai_working_bytes());return 0;
}
