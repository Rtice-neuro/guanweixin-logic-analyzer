#include "core_portme.h"
volatile unsigned int init_words[4]={0x12345678,0x89abcdef,0x55aa55aa,7};
volatile unsigned char init_bytes[4]={1,128,255,4};
volatile unsigned short init_half[2]={0x1234,0xabcd};
volatile unsigned char clear_bss[32768];
const unsigned int constants[4]={0x10203040,0x50607080,0xabcdef01,0x31415926};
__attribute__((noinline)) unsigned int read_const(unsigned int i) { return constants[i]; }
static unsigned long long read_timer(void) {
    unsigned int lo=*(volatile unsigned int *)0x40000200;
    unsigned int hi=*(volatile unsigned int *)0x40000204;
    return ((unsigned long long)hi<<32)|lo;
}
int main(void) {
    unsigned int errors=0;
    unsigned long long first=read_timer();
    for(unsigned int i=0;i<sizeof(clear_bss);i++) if(clear_bss[i]) errors++;
    if(init_words[0]!=0x12345678 || init_words[1]!=0x89abcdef || init_words[3]!=7) errors++;
    if(init_bytes[1]!=128 || init_bytes[2]!=255 || init_half[1]!=0xabcd) errors++;
    if(read_const(init_words[3]&3)!=0x31415926) errors++;
    init_bytes[1]=0x5a; init_half[1]=0xbeef;
    clear_bss[32767]=0xa5;
    if(init_bytes[0]!=1 || init_bytes[1]!=0x5a || init_bytes[2]!=255 || init_bytes[3]!=4) errors++;
    if(init_half[0]!=0x1234 || init_half[1]!=0xbeef || clear_bss[32767]!=0xa5) errors++;
    unsigned long long second=read_timer();
    if(second<=first) errors++;
#ifdef EXPECT_TIMER_HIGH
    if((first>>32)!=1 || (second>>32)!=1) errors++;
#endif
    ee_printf("BOOT DATA BSS RODATA BYTE HALF HIGH_RAM TIMER64 errors=%u\n",errors);
    while(*(volatile unsigned int *)0x40000004) { }
    return errors;
}
