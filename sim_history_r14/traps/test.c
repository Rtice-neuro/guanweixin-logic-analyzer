#include <stdint.h>
#define R(a) (*(volatile uint32_t *)(a))
#define GET(n) ({uint32_t v;__asm__ volatile("csrr %0," #n:"=r"(v));v;})
#define SET(n,v) __asm__ volatile("csrw " #n ",%0"::"r"((uint32_t)(v)):"memory")
static volatile uint32_t exp_cause,exp_pc,exp_val,sync_seen,irq_seen,seq[8],allow_irq;
extern void gwx_trap_entry(void),trap_vectors(void);
extern void fault_illegal(void),fault_ecall(void),fault_break(void),fault_ialign(void),fault_ro(void),fault_unknown(void),fault_lalign(void),fault_salign(void),fault_laccess(void),fault_saccess(void),do_laccess(void),do_saccess(void),fault_ifetch(void);
static void fail(uint32_t code){R(0x100003f8)=code;R(0x100003fc)=0x50415353u;for(;;){}}
#define CHECK(c,n) do{if(!(c))fail(n);}while(0)
void gwx_trap_handler(void){
 uint32_t c=GET(mcause),pc=GET(mepc),v=GET(mtval),s=GET(mstatus);
 CHECK((s&8)==0 && (s&0x1800)==0x1800,101);
 if(c>>31){
  CHECK(allow_irq && irq_seen<8 && (s&0x80),102);seq[irq_seen++]=c&31;
  uint32_t bit=(c==0x8000000bu)?4:(c==0x80000003u)?1:(c==0x80000007u)?2:0;
  CHECK(bit!=0 && v==0,103);R(0x100003e0)&=~bit;return;
 }
 CHECK(c==exp_cause,110+c);CHECK(pc==exp_pc,140+c);CHECK(v==exp_val,160+c);
 sync_seen++;SET(mepc,pc+4);
}
static void expected(uint32_t c,void(*pc)(void),uint32_t v){exp_cause=c;exp_pc=(uintptr_t)pc;exp_val=v;}
extern void register_canary(void),canary_ecall(void);
void gwx_check_registers(uint32_t *frame){for(unsigned i=1;i<32;i++)if(i!=2)CHECK(frame[i]==0x51000000u+i,210+i);}
static void ticks_wait(void){for(volatile uint32_t i=0;i<120;i++);}
int main(void){
 SET(mtvec,(uintptr_t)gwx_trap_entry);SET(mie,0);SET(mstatus,0);
 SET(mscratch,0x13572468u);CHECK(GET(mscratch)==0x13572468u,1);
 uint32_t q;__asm__ volatile("csrrs %0,mscratch,%1":"=r"(q):"r"(0x80u));CHECK(q==0x13572468u && GET(mscratch)==0x135724e8u,2);
 __asm__ volatile("csrrc %0,mscratch,%1":"=r"(q):"r"(0x60u));CHECK(q==0x135724e8u && GET(mscratch)==0x13572488u,3);
 __asm__ volatile("csrrwi %0,mscratch,7":"=r"(q));CHECK(GET(mscratch)==7,4);
 __asm__ volatile("csrrsi %0,mscratch,24":"=r"(q));CHECK(GET(mscratch)==31,5);
 __asm__ volatile("csrrci %0,mscratch,3":"=r"(q));CHECK(GET(mscratch)==28,6);
 __asm__ volatile("csrrs zero,cycle,zero");CHECK((GET(misa)&0x100)!=0 && (GET(misa)&0x1000)==0,7);
 SET(mepc,7);CHECK(GET(mepc)==4,8);SET(mtvec,(uintptr_t)gwx_trap_entry|3);CHECK((GET(mtvec)&3)==0,9);
 SET(mcycleh,0x123);SET(mcycle,0xfffffff0u);ticks_wait();CHECK(GET(mcycleh)==0x124,10);
 SET(minstreth,0x77);SET(minstret,0x1234);CHECK(GET(minstret)>=0x1234 && GET(minstret)<0x1300 && GET(minstreth)==0x77,11);
 expected(2,fault_illegal,0xffffffffu);fault_illegal();
 expected(11,fault_ecall,0);fault_ecall();
 expected(3,fault_break,(uintptr_t)fault_break);fault_break();
 expected(0,fault_ialign,(uintptr_t)fault_ialign+2);fault_ialign();
 expected(4,fault_lalign,1);fault_lalign();expected(6,fault_salign,2);fault_salign();
 expected(5,fault_laccess,0x20000000u);do_laccess();expected(7,fault_saccess,0x20000000u);do_saccess();
 expected(2,fault_ro,0xc0001073u);fault_ro();expected(2,fault_unknown,0x7c002573u);fault_unknown();
 expected(1,fault_ifetch,(uintptr_t)fault_ifetch);fault_ifetch();
 CHECK(sync_seen==11,12);
 R(0x100003e0)=7;ticks_wait();CHECK(irq_seen==0,13);
 SET(mstatus,8);ticks_wait();CHECK(irq_seen==0,14);
 allow_irq=1;SET(mie,0x888);
 while(irq_seen<3);CHECK(seq[0]==11 && seq[1]==3 && seq[2]==7,15);CHECK((GET(mstatus)&0x88)==0x88,16);
 SET(mie,0);SET(mtvec,(uintptr_t)trap_vectors|1);CHECK((GET(mtvec)&3)==1,17);
 R(0x100003e0)=7;SET(mie,0x888);while(irq_seen<6);CHECK(seq[3]==11 && seq[4]==3 && seq[5]==7,18);
 SET(mie,0);allow_irq=0;expected(11,fault_ecall,0);fault_ecall();CHECK(sync_seen==12,19);expected(11,canary_ecall,0);register_canary();CHECK(sync_seen==13,21);
 CHECK(R(0x100003e0)==0,20);R(0x100003f4)=sync_seen;R(0x100003f0)=irq_seen;
 R(0x100003f8)=0;R(0x100003fc)=0x50415353u;for(;;){}
}
