/* RV32 bare-metal integer-only printf; no floating-point formats. */
#include <stdarg.h>
#include "core_portme.h"
static void putch(char c) { *(volatile unsigned int *)0x40000000=(unsigned char)c; }
int ee_printf(const char *fmt,...) {
    va_list ap; va_start(ap,fmt); int count=0;
    while(*fmt) {
        if(*fmt!='%') { putch(*fmt++); count++; continue; }
        fmt++; int width=0, zero=0;
        if(*fmt=='0') { zero=1; fmt++; }
        while(*fmt>='0' && *fmt<='9') width=width*10+(*fmt++-'0');
        if(*fmt=='l') fmt++; /* int/long are both 32 bits in ILP32. */
        char spec=*fmt++;
        if(spec=='s') {
            const char *s=va_arg(ap,const char *); if(!s) s="(null)";
            while(*s) { putch(*s++); count++; }
        } else if(spec=='c' || spec=='%') {
            putch(spec=='%'?'%':(char)va_arg(ap,int)); count++;
        } else if(spec=='d'||spec=='u'||spec=='x'||spec=='X') {
            unsigned int v=va_arg(ap,unsigned int); int neg=spec=='d' && (int)v<0;
            if(neg) v=0u-v;
            unsigned int base=(spec=='x'||spec=='X')?16:10;
            char buf[32]; int n=0;
            do { unsigned int digit=v%base; v/=base;
                 buf[n++]=digit<10?'0'+digit:(spec=='X'?'A':'a')+digit-10; } while(v);
            int pad=width-n-neg;
            if(neg && zero) { putch('-'); count++; }
            while(pad-->0) { putch(zero?'0':' '); count++; }
            if(neg && !zero) { putch('-'); count++; }
            while(n) { putch(buf[--n]); count++; }
        } else { putch('?'); count++; }
    }
    va_end(ap); return count;
}
