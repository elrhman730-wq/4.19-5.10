#!/sbin/sh
# AnyKernel3 Ramdisk Mod Script
# osm0sis @ xda-developers
# Edit by @physwizz Generic

## AnyKernel setup
# begin properties
properties() { '
kernel.string=Legion Kernel for mt6768 - A13VE - KernelSU-Next v3.4.0 - SUSFS v2.4.0
do.devicecheck=0
do.modules=0
do.cleanup=1
do.cleanuponabort=0
device.name1=a13ve
device.name2=SM-A137F
supported.versions=
'; } # end properties

# A13VE boot partition
# AnyKernel3 core expects these variable names in UPPERCASE.
BLOCK=boot;
IS_SLOT_DEVICE=0;
RAMDISK_COMPRESSION=auto;

## AnyKernel methods (DO NOT CHANGE)
. tools/ak3-core.sh;

ui_print "- Unpacking boot image";
dump_boot;

ui_print "- Installing new boot image";
write_boot;

ui_print "- Done";
ui_print " ";
## end install
