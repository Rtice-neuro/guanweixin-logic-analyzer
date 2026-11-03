.section .text.start,"ax",@progbits
.globl _start
_start:
 li sp,0x100003c0
 li t0,0x10000000
 li t1,0x100003c0
1: sw zero,0(t0)
 addi t0,t0,4
 bltu t0,t1,1b
 call main
2: j 2b
