#!/usr/bin/env python3
"""Prepare the pinned KernelSU-Next v3.4.0 SUSFS bridge for SUSFS v2.4.0."""
from pathlib import Path
import sys

root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
kconfig = root / "Kconfig"
source = kconfig.read_text()

required = [
    "config KSU_SUSFS",
    "config KSU_SUSFS_SUS_PATH",
    "config KSU_SUSFS_SUS_MOUNT",
    "config KSU_SUSFS_SUS_KSTAT",
    "config KSU_SUSFS_SPOOF_UNAME",
    "config KSU_SUSFS_ENABLE_LOG",
    "config KSU_SUSFS_HIDE_KSU_SUSFS_SYMBOLS",
    "config KSU_SUSFS_SPOOF_CMDLINE_OR_BOOTCONFIG",
    "config KSU_SUSFS_OPEN_REDIRECT",
    "config KSU_SUSFS_SUS_MAP",
]
import re
missing = [
    item for item in required
    if len(re.findall(r"(?m)^" + re.escape(item) + r"$", source)) != 1
]
if missing:
    raise SystemExit(f"KernelSU-Next SUSFS Kconfig anchors missing or duplicated: {missing}")

priority = "config KSU_SUSFS_PRIORITY_UID_FILTER"
if priority not in source:
    start = source.index("config KSU_SUSFS_SUS_MAP")
    end = source.index("\nendmenu", start)
    addition = """
config KSU_SUSFS_PRIORITY_UID_FILTER
    bool "Enable SUSFS priority UID filter"
    depends on KSU_SUSFS
    default y
"""
    source = source[:end] + addition + source[end:]
    kconfig.write_text(source)

source = kconfig.read_text()
if source.count(priority) != 1:
    raise SystemExit("KSU_SUSFS_PRIORITY_UID_FILTER must be declared exactly once")

checks = {
    "Kbuild": root / "Kbuild",
    "core/init.c": root / "core/init.c",
    "supercall/supercall.c": root / "supercall/supercall.c",
}
for name, path in checks.items():
    if not path.is_file():
        raise SystemExit(f"Missing KernelSU-Next source file: {name}")

kbuild = checks["Kbuild"].read_text()
init = checks["core/init.c"].read_text()
supercall = checks["supercall/supercall.c"].read_text()

for token in ("hook/syscall_table_hook.o", "infra/symbol_resolver.o", "KSU_SYSCALL_TABLE_HOOK"):
    if token not in kbuild:
        raise SystemExit(f"KernelSU-Next syscall-table hook support missing: {token}")
if "susfs_init();" not in init or "#include <linux/susfs.h>" not in init:
    raise SystemExit("KernelSU-Next init path does not initialize built-in SUSFS")
for token in ("SUSFS_MAGIC", "CMD_SUSFS_SHOW_VERSION", "CMD_SUSFS_SHOW_ENABLED_FEATURES"):
    if token not in supercall:
        raise SystemExit(f"KernelSU-Next SUSFS supercall bridge missing: {token}")

print("KernelSU-Next v3.4.0 SUSFS bridge verified; added v2.4.0 priority-UID Kconfig option.")
