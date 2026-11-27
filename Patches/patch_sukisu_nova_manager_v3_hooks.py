#!/usr/bin/env python3
"""Apply the SukiSU Nova builtin-branch manager hooks for this Linux 4.19 tree.

The pinned SukiSU Nova builtin commit uses struct filename-based exec hooks and
routes Manager/SUSFS supercalls through ksu_handle_sys_reboot().
"""
from pathlib import Path
import sys

root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()

def patch_once(path: str, needle: str, replacement: str, marker: str) -> None:
    file = root / path
    source = file.read_text()
    if marker in source:
        if source.count(marker) != 1:
            raise SystemExit(f"{path}: expected exactly one existing {marker!r}")
        return
    count = source.count(needle)
    if count != 1:
        raise SystemExit(f"{path}: anchor expected once, found {count}: {needle!r}")
    file.write_text(source.replace(needle, replacement, 1))

exec_anchor = (
    "static int do_execveat_common(int fd, struct filename *filename,\n"
    "\t\t\t      struct user_arg_ptr argv,\n"
    "\t\t\t      struct user_arg_ptr envp,\n"
    "\t\t\t      int flags)\n"
    "{\n"
)
exec_hook = (
    "#ifdef CONFIG_KSU\n"
    "\textern int ksu_handle_execveat(int *, struct filename **, void *, void *, int *);\n"
    "\tksu_handle_execveat(&fd, &filename, &argv, &envp, &flags);\n"
    "#endif\n"
)
patch_once(
    "fs/exec.c",
    exec_anchor,
    exec_anchor + exec_hook,
    "ksu_handle_execveat(&fd, &filename, &argv, &envp, &flags);",
)

reboot_anchor = (
    "SYSCALL_DEFINE4(reboot, int, magic1, int, magic2, unsigned int, cmd,\n"
    "\t\tvoid __user *, arg)\n"
    "{\n"
)
reboot_replacement = (
    "#ifdef CONFIG_KSU\n"
    "extern int ksu_handle_sys_reboot(int magic1, int magic2, unsigned int cmd, void __user **arg);\n"
    "#endif\n\n"
    + reboot_anchor
    + "#ifdef CONFIG_KSU\n"
    "\tksu_handle_sys_reboot(magic1, magic2, cmd, &arg);\n"
    "#endif\n"
)
patch_once(
    "kernel/reboot.c",
    reboot_anchor,
    reboot_replacement,
    "ksu_handle_sys_reboot(magic1, magic2, cmd, &arg);",
)

exec_source = (root / "fs/exec.c").read_text()
reboot_source = (root / "kernel/reboot.c").read_text()
if exec_source.count("ksu_handle_execveat(&fd, &filename, &argv, &envp, &flags);") != 1:
    raise SystemExit("SukiSU Nova execveat hook verification failed")
if reboot_source.count("ksu_handle_sys_reboot(magic1, magic2, cmd, &arg);") != 1:
    raise SystemExit("SukiSU Nova reboot/Manager supercall hook verification failed")
if "CONFIG_KSU" not in exec_source or "CONFIG_KSU" not in reboot_source:
    raise SystemExit("SukiSU Nova hook guards are missing")
print("SukiSU Nova builtin manual hooks applied and verified: execveat + reboot supercalls.")
