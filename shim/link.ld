ENTRY(_head)
SECTIONS {
    . = 0;
    .text : { *(.text.head) *(.text*) }
    .rodata : { *(.rodata*) }
    .data : { *(.data*) }
    . = ALIGN(16);
    _bss_start = .;
    .bss : { *(.bss*) *(COMMON) }
    . = ALIGN(16);
    _bss_end = .;
    . += 0x4000;
    _stack_top = .;
    . += 0x4000;
    _gold_stack_top = .;
    . += 0x4000;
    _emergency_stack_top = .;
    . = ALIGN(4096);
    _end = .;
    /DISCARD/ : { *(.comment) *(.note*) *(.eh_frame*) }
}
