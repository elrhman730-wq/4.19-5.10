from pathlib import Path
import re

def add_before_final_endif(path, text, marker):
    p = Path(path)
    s = p.read_text()
    if marker not in s:
        i = s.rfind("#endif")
        if i < 0:
            raise SystemExit(f"{path}: final #endif not found")
        s = s[:i] + text + "\n" + s[i:]
        p.write_text(s)

defs = Path("include/linux/susfs_def.h")
add_before_final_endif(
    defs,
    """
/* SukiSU Nova protocol compatibility for the legacy 4.19 SUSFS core. */
#ifndef SUSFS_MAGIC
#define SUSFS_MAGIC 0xFAFAFAFA
#endif
#ifndef CMD_SUSFS_ADD_SUS_PATH_LOOP
#define CMD_SUSFS_ADD_SUS_PATH_LOOP 0x55553
#endif
#ifndef CMD_SUSFS_HIDE_SUS_MNTS_FOR_NON_SU_PROCS
#define CMD_SUSFS_HIDE_SUS_MNTS_FOR_NON_SU_PROCS 0x55561
#endif
#ifndef CMD_SUSFS_ENABLE_AVC_LOG_SPOOFING
#define CMD_SUSFS_ENABLE_AVC_LOG_SPOOFING 0x60010
#endif
""",
    "SukiSU Nova protocol compatibility",
)

# The 1.5.5 4.19 core does not implement these two v2-only features.
# Disable them at Kconfig level so Nova does not compile unavailable handlers.
import re
kconfig = Path("KernelSU/kernel/Kconfig")
ks = kconfig.read_text()
blocks = re.split(r"(?=^config )", ks, flags=re.M)
for option in ("KSU_SUSFS_SUS_MAP", "KSU_SUSFS_PRIORITY_UID_FILTER"):
    found = False
    for n, block in enumerate(blocks):
        if block.startswith("config " + option + "\n"):
            if "default y" in block:
                blocks[n] = block.replace("default y", "default n", 1)
            found = True
            break
    if not found:
        raise SystemExit(f"Nova Kconfig option missing: {option}")
kconfig.write_text("".join(blocks))

dispatch = Path("KernelSU/kernel/supercall/dispatch.c")
d = dispatch.read_text()
for fn in (
    "susfs_add_sus_path",
    "susfs_add_sus_kstat",
    "susfs_update_sus_kstat",
    "susfs_set_uname",
    "susfs_set_cmdline_or_bootconfig",
    "susfs_add_open_redirect",
):
    d = d.replace(f"{fn}(arg);", f"{fn}(*arg);")
dispatch.write_text(d)

compat = Path("fs/susfs_compat.c")
compat.write_text(r'''// SPDX-License-Identifier: GPL-2.0
#include <linux/errno.h>
#include <linux/susfs.h>
#include <linux/uaccess.h>

void susfs_add_sus_path_loop(void __user **arg) { (void)arg; }
void susfs_set_hide_sus_mnts_for_non_su_procs(void __user **arg) { (void)arg; }
void susfs_set_avc_log_spoofing(void __user **arg) { (void)arg; }
void susfs_get_enabled_features(void __user **arg) { (void)arg; }
void susfs_show_variant(void __user **arg) { (void)arg; }
void susfs_show_version(void __user **arg) { (void)arg; }

void susfs_enable_log(void __user **arg)
{
    bool enabled;
    if (!arg || !*arg)
        return;
    if (!copy_from_user(&enabled, *arg, sizeof(enabled)))
        susfs_set_log(enabled);
}

void susfs_set_current_proc_no_su(void) { }
''')

header = Path("include/linux/susfs.h")
add_before_final_endif(
    header,
    """
/* SukiSU Nova legacy-core compatibility entry points. */
void susfs_add_sus_path_loop(void __user **arg);
void susfs_set_hide_sus_mnts_for_non_su_procs(void __user **arg);
void susfs_set_avc_log_spoofing(void __user **arg);
void susfs_get_enabled_features(void __user **arg);
void susfs_show_variant(void __user **arg);
void susfs_show_version(void __user **arg);
void susfs_enable_log(void __user **arg);
void susfs_set_current_proc_no_su(void);
""",
    "SukiSU Nova legacy-core compatibility entry points",
)

mk = Path("fs/Makefile")
m = mk.read_text()
if "susfs_compat.o" not in m:
    anchor = "obj-$(CONFIG_KSU_SUSFS) += susfs.o"
    if m.count(anchor) != 1:
        raise SystemExit("fs/Makefile: SUSFS object anchor mismatch")
    m = m.replace(anchor, anchor + "\nobj-$(CONFIG_KSU_SUSFS) += susfs_compat.o", 1)
    mk.write_text(m)

if "SUSFS_MAGIC" not in defs.read_text() or "susfs_compat.o" not in mk.read_text():
    raise SystemExit("SUSFS Nova compatibility verification failed")
print("Legacy SUSFS core compatibility layer installed.")
