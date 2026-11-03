OUTPUT_ARCH(riscv)
ENTRY(_start)
MEMORY {
 ROM (rx) : ORIGIN = 0x00000000, LENGTH = 64K
 RAM (rw) : ORIGIN = 0x10000000, LENGTH = 64K
}
SECTIONS {
 .text : { KEEP(*(.text.start)) *(.text .text.*) } > ROM
 .rodata : { *(.rodata .rodata.* .srodata .srodata.*) . = ALIGN(4); } > ROM
 .data : {
   . = ALIGN(4); _data_start = .;
   *(.data .data.* .sdata .sdata.*)
   . = ALIGN(4); _data_end = .;
 } > RAM AT> ROM
 _data_load = LOADADDR(.data);
 __global_pointer$ = _data_start + 0x800;
 .bss (NOLOAD) : {
   . = ALIGN(4); _bss_start = .;
   *(.bss .bss.* .sbss .sbss.*) *(COMMON)
   . = ALIGN(4); _bss_end = .;
 } > RAM
 _stack_top = ORIGIN(RAM) + LENGTH(RAM);
 ASSERT(_bss_end < _stack_top - 16384, "RAM overflow / less than 16KB stack")
 /DISCARD/ : { *(.comment) *(.eh_frame*) }
}
