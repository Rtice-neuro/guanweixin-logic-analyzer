.section .text.__mulsi3,"ax",@progbits
.p2align 2
.global __mulsi3
.type __mulsi3,@function
__mulsi3:
    mul a0,a0,a1
    ret
.size __mulsi3,.-__mulsi3
