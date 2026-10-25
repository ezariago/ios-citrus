# Minimal Citrus XNU stage: required changes

Source inspection against Topaz e4772911e116ab4ab6c4ac1f38e6106fefe8b483.
These are implementation requirements, not claims of tested hardware support.

1. Keep the default 16K build initially: MACHINE_CONFIG=SWEET,
   KERNEL_CONFIG=DEVELOPMENT, MACOS_VERSION=13.5, TOPAZ_4K unset/0. TOPAZ_4K=1
   also enables the later AMP paths. Start with cpus=1 on Gold MPIDR 0x100.
2. The shim must establish actual Gold 16K translation support and transfer
   control to that core. The standalone diagnostic currently stays on ABL's
   entry core and only reports its feature registers; it is not an XNU loader.
3. Build a Citrus ADT with one Gold CPU. Retain legacy kernel compatibility
   matches until a dedicated Citrus platform expert exists. Omit sweet-ufs,
   arm-io/disp0 and WLAN for the first driver-free kernel attempt.
4. Correct or disable all inherited Sweet early framebuffer mappings/stores in
   start.s, arm_vm_init.c and sweet_early.c: their 16K branches still reference
   0x9c000000. On Citrus that address is RAM, not the splash reservation.
5. Do not reuse Topaz highmem/midmem values. The bank 0x80000000..0xc0000000
   is a candidate only; account for fixed and dynamic reservations, the image,
   DTB and ramdisk before selecting a kernel-managed span.
6. Explicitly gate SweetBattery: it matches IOResources independently and
   defaults to real hardware. Its start path calls sweet_cpufreq_max first.
   At minimum sweetbattery=0 sweetcpufreq=0 sweetchg=0; preferably remove its
   personality from a diagnostic build. sweethw=0 alone is insufficient;
   later patches moved some touch/keys startup outside that gate.
7. Full XNU build remains pending a compatible Xcode/iig and KDK setup.
   Upstream expects Xcode 15.4 + KDK 13.5; the installed Xcode is 27.1.
   No prebuilt Topaz XNU kernel was found locally.

## Boot route test, 2026-10-25

Built Citrus diagnostic image: out/citrus-diagnostic/citrus-diagnostic-boot.img.
fastboot transferred the complete image successfully, then ABL returned:

```
Booting FAILED (remote: 'unknown command')
```

The diagnostic has not executed on the physical phone. The phone was rebooted
normally afterward and Android ADB reappeared. No partition was flashed.
Testing this bootloader requires a different route, such as a temporary boot
partition replacement followed by restoration from the verified backup.
