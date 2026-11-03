#include <stdint.h>
#define REG(a) (*(volatile uint32_t *)(a))
#define CSR_GET(n) ({uint32_t v;__asm__ volatile("csrr %0," #n:"=r"(v));v;})
#define CSR_SET(n,v) __asm__ volatile("csrw " #n ",%0"::"r"((uint32_t)(v)):"memory")
extern void gwx_trap_entry(void);
volatile uint32_t gwx_irq_counts[3],gwx_sync_count,gwx_trap_last_cause,gwx_trap_last_pc,gwx_trap_last_value,gwx_irq_selftest_pass;
static volatile uint32_t selftest_active;
void gwx_trap_handler(void){
 uint32_t cause=CSR_GET(mcause),pc=CSR_GET(mepc),value=CSR_GET(mtval);
 gwx_trap_last_cause=cause;gwx_trap_last_pc=pc;gwx_trap_last_value=value;
 if(cause==0x80000007u){REG(0x40000800u)=0xffffffffu;REG(0x40000804u)=0xffffffffu;gwx_irq_counts[0]++;return;}
 if(cause==0x80000003u){REG(0x40000808u)=0;gwx_irq_counts[1]++;return;}
 if(cause==0x8000000bu){
  REG(0x4000080cu)=0;gwx_irq_counts[2]++;
  /* UART data remains for the normal command parser; disable its level IRQ
     until application code consumes it and explicitly re-enables MEIE. */
  if(REG(0x4000000cu)&1u){uint32_t mask=CSR_GET(mie);CSR_SET(mie,mask&~0x800u);}return;
 }
 if(selftest_active && cause==11){gwx_sync_count++;CSR_SET(mepc,pc+4);return;}
 /* An unexpected fault is recorded, never silently skipped. */
 CSR_SET(mie,0);REG(0x40000100u)=0xe0000000u|(cause&255u);
 for(;;)__asm__ volatile("wfi");
}
static int wait_irq(volatile uint32_t *counter){
 uint32_t start=REG(0x40000200u);while(!*counter)if(REG(0x40000200u)-start>270000u)return -1;return 0;
}
int gwx_machine_selftest(void){
 uint32_t saved_status=CSR_GET(mstatus),saved_mie=CSR_GET(mie);
 CSR_SET(mie,0);CSR_SET(mstatus,saved_status&~8u);selftest_active=1;
 __asm__ volatile("ecall":::"memory");selftest_active=0;
 if(gwx_sync_count!=1)return -1;
 CSR_SET(mie,8);CSR_SET(mstatus,saved_status|8u);REG(0x40000808u)=1;
 if(wait_irq(&gwx_irq_counts[1]))return -2;
 CSR_SET(mie,0x80);uint32_t now=REG(0x40000200u);
 REG(0x40000804u)=0xffffffffu;REG(0x40000800u)=now+2000;REG(0x40000804u)=REG(0x40000208u);
 if(wait_irq(&gwx_irq_counts[0]))return -3;
 CSR_SET(mie,0x800);REG(0x4000080cu)=1;
 if(wait_irq(&gwx_irq_counts[2]))return -4;
 CSR_SET(mie,saved_mie);CSR_SET(mstatus,saved_status);
 gwx_irq_selftest_pass=1;return 0;
}
void gwx_machine_init(void){
 CSR_SET(mtvec,(uintptr_t)&gwx_trap_entry);CSR_SET(mie,0);
 int status=gwx_machine_selftest();
 const char *p=status?"GWX IRQ SELFTEST FAIL\r\n":"GWX IRQ SELFTEST PASS\r\n";
 while(*p){while(REG(0x40000004u)&1u){}REG(0x40000000u)=(uint8_t)*p++;}
 if(status)for(;;)__asm__ volatile("wfi");
}
