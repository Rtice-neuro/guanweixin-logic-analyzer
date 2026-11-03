/* Project-owned port; EEMBC algorithm files are compiled unchanged. */
#include "coremark.h"
#define REG(a) (*(volatile ee_u32 *)(a))
volatile ee_s32 seed1_volatile=0,seed2_volatile=0,seed3_volatile=0x66;
volatile ee_s32 seed4_volatile=ITERATIONS,seed5_volatile=0;
ee_u32 default_num_contexts=1;
static CORE_TICKS t_start,t_stop;
static CORE_TICKS clock_ticks(void){ee_u32 lo=REG(0x40000200u),hi=REG(0x40000204u);return ((CORE_TICKS)hi<<32)|lo;}
void start_time(void){t_start=clock_ticks();}
void stop_time(void){t_stop=clock_ticks();}
CORE_TICKS get_time(void){return t_stop-t_start;}
secs_ret time_in_secs(CORE_TICKS ticks){return (secs_ret)(ticks/CLOCK_HZ);}
void portable_init(core_portable *p,int *argc,char *argv[]){
 (void)argc;(void)argv;
 if(sizeof(ee_ptr_int)!=sizeof(void*)||sizeof(ee_u32)!=4)ee_printf("ERROR! incompatible RV32 data types\n");
 p->portable_id=1;ee_printf("GUANWEIXIN five-stage RV32I / cached synchronous memory\n");
}
void portable_fini(core_portable *p){p->portable_id=0;while(REG(0x40000004u)){} }
