/* ARM64 Linux Image entry, position independent, MMU/caches left as ABL supplied. */
.section .text.head, "ax"
.global _head
_head:
    b _start
    .long 0
    .quad 0
    .quad _end
    .quad 0xa
    .quad 0, 0, 0
    .ascii "ARM\x64"
    .long 0
.text
_start:
    msr daifset, #15
    mov x19, x0
    msr spsel, #1
    adr x1, _stack_top
    mov sp, x1
    adr x1, vectors
    mrs x2, CurrentEL
    cmp x2, #8
    b.eq 1f
    cmp x2, #4
    b.ne 5f
    msr vbar_el1, x1
    mrs x3, sctlr_el1
    b 2f
1:  msr vbar_el2, x1
    mrs x3, sctlr_el2
2:  isb
    tst x3, #1
    b.ne 5f
    tst x3, #4
    b.ne 5f
    adr x1, _bss_start
    adr x2, _bss_end
3:  cmp x1, x2
    b.hs 4f
    str xzr, [x1], #8
    b 3b
4:  mov x0, x19
    bl shim_main
5:  wfe
    b 5b

/* PSCI CPU_ON entry: context x0 is the physical DTB pointer. The Gold
 * core has its own stack; the original Silver core parks after CPU_ON. */
.global gold_entry
gold_entry:
    msr daifset, #15
    msr spsel, #1
    adr x1, _gold_stack_top
    mov sp, x1
    adr x1, vectors
    msr vbar_el1, x1
    isb
    bl shim_main
    b 5b

.macro vector
    .balign 128
    b exception
.endm
.balign 2048
vectors:
.rept 16
    vector
.endr
exception:
    msr daifset, #15
    adr x9, exception_active
    ldr w10, [x9]
    cbnz w10, 5b
    mov w10, #1
    str w10, [x9]
    adr x9, _emergency_stack_top
    mov sp, x9
    mrs x0, CurrentEL
    cmp x0, #8
    b.eq 6f
    mrs x0, esr_el1
    mrs x1, elr_el1
    mrs x2, far_el1
    b 7f
6:  mrs x0, esr_el2
    mrs x1, elr_el2
    mrs x2, far_el2
7:  bl shim_exception
    b 5b

.bss
.balign 8
exception_active:
    .quad 0
