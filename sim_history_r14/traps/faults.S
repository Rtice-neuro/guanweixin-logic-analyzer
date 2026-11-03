.section .text,"ax",@progbits
.p2align 2
.global fault_illegal
fault_illegal:
.word 0xffffffff
ret
.p2align 2
.global fault_ecall
fault_ecall:
.word 0x00000073
ret
.p2align 2
.global fault_break
fault_break:
.word 0x00100073
ret
.p2align 2
.global fault_ialign
fault_ialign:
.word 0x0020006f
ret
.p2align 2
.global fault_ro
fault_ro:
.word 0xc0001073
ret
.p2align 2
.global fault_unknown
fault_unknown:
.word 0x7c002573
ret
.global fault_lalign
fault_lalign:
lw t0,1(zero)
ret
.global fault_salign
fault_salign:
sw t0,2(zero)
ret
.global do_laccess,fault_laccess
do_laccess:
li t0,0x20000000
fault_laccess:
lw t1,0(t0)
ret
.global do_saccess,fault_saccess
do_saccess:
li t0,0x20000000
fault_saccess:
sw t1,0(t0)
ret
.p2align 4
.global fault_ifetch
fault_ifetch:
nop
ret
.p2align 6
.global trap_vectors
trap_vectors:
.rept 16
j gwx_trap_entry
.endr

.p2align 2
.global register_canary,canary_ecall
register_canary:
addi sp,sp,-256
sw x1,132(sp)
sw x3,140(sp)
sw x4,144(sp)
sw x5,148(sp)
sw x6,152(sp)
sw x7,156(sp)
sw x8,160(sp)
sw x9,164(sp)
sw x10,168(sp)
sw x11,172(sp)
sw x12,176(sp)
sw x13,180(sp)
sw x14,184(sp)
sw x15,188(sp)
sw x16,192(sp)
sw x17,196(sp)
sw x18,200(sp)
sw x19,204(sp)
sw x20,208(sp)
sw x21,212(sp)
sw x22,216(sp)
sw x23,220(sp)
sw x24,224(sp)
sw x25,228(sp)
sw x26,232(sp)
sw x27,236(sp)
sw x28,240(sp)
sw x29,244(sp)
sw x30,248(sp)
sw x31,252(sp)
li x1,0x51000001
li x3,0x51000003
li x4,0x51000004
li x5,0x51000005
li x6,0x51000006
li x7,0x51000007
li x8,0x51000008
li x9,0x51000009
li x10,0x5100000a
li x11,0x5100000b
li x12,0x5100000c
li x13,0x5100000d
li x14,0x5100000e
li x15,0x5100000f
li x16,0x51000010
li x17,0x51000011
li x18,0x51000012
li x19,0x51000013
li x20,0x51000014
li x21,0x51000015
li x22,0x51000016
li x23,0x51000017
li x24,0x51000018
li x25,0x51000019
li x26,0x5100001a
li x27,0x5100001b
li x28,0x5100001c
li x29,0x5100001d
li x30,0x5100001e
li x31,0x5100001f
canary_ecall:
ecall
sw x1,4(sp)
sw x3,12(sp)
sw x4,16(sp)
sw x5,20(sp)
sw x6,24(sp)
sw x7,28(sp)
sw x8,32(sp)
sw x9,36(sp)
sw x10,40(sp)
sw x11,44(sp)
sw x12,48(sp)
sw x13,52(sp)
sw x14,56(sp)
sw x15,60(sp)
sw x16,64(sp)
sw x17,68(sp)
sw x18,72(sp)
sw x19,76(sp)
sw x20,80(sp)
sw x21,84(sp)
sw x22,88(sp)
sw x23,92(sp)
sw x24,96(sp)
sw x25,100(sp)
sw x26,104(sp)
sw x27,108(sp)
sw x28,112(sp)
sw x29,116(sp)
sw x30,120(sp)
sw x31,124(sp)
mv a0,sp
call gwx_check_registers
lw x1,132(sp)
lw x3,140(sp)
lw x4,144(sp)
lw x5,148(sp)
lw x6,152(sp)
lw x7,156(sp)
lw x8,160(sp)
lw x9,164(sp)
lw x10,168(sp)
lw x11,172(sp)
lw x12,176(sp)
lw x13,180(sp)
lw x14,184(sp)
lw x15,188(sp)
lw x16,192(sp)
lw x17,196(sp)
lw x18,200(sp)
lw x19,204(sp)
lw x20,208(sp)
lw x21,212(sp)
lw x22,216(sp)
lw x23,220(sp)
lw x24,224(sp)
lw x25,228(sp)
lw x26,232(sp)
lw x27,236(sp)
lw x28,240(sp)
lw x29,244(sp)
lw x30,248(sp)
lw x31,252(sp)
addi sp,sp,256
ret
