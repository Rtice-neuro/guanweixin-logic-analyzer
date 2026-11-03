OUTPUT_ARCH(riscv)
ENTRY(_start)
MEMORY { ROM (rx) : ORIGIN = 0, LENGTH = 8K
RAM (rw) : ORIGIN = 0x10000000, LENGTH = 960 }
SECTIONS { .text : { *(.text.start) *(.text .text.*) } > ROM
.rodata : { *(.rodata .rodata.*) } > ROM
.data : { *(.data .data.*) } > RAM AT>ROM
.bss (NOLOAD) : { *(.bss .bss.*) *(COMMON) } > RAM
_stack_top = 0x100003c0; }
