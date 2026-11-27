from pathlib import Path
import re

def replace_once(path, old, new, label):
    p = Path(path)
    s = p.read_text()
    count = s.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, found {count}")
    p.write_text(s.replace(old, new, 1))

def add_before_final_endif(path, text, marker):
    p = Path(path)
    s = p.read_text()
    if marker not in s:
        i = s.rfind("#endif")
        if i < 0:
            raise SystemExit(f"{path}: final #endif not found")
        s = s[:i] + text + "\n" + s[i:]
        p.write_text(s)

# SUSFS 1.5.5 is the available non-GKI 4.19 implementation. Disable only
# Nova options whose implementation first appeared in newer SUSFS releases.
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

# SukiSU Nova dispatch passes void __user **; SUSFS 1.5.5 accepts typed
# pointers. Use the proven typed bridge pattern instead of dereferencing
# user pointers at the call site.
bridge = Path("KernelSU/kernel/include/linux/susfs_ksu_compat.h")
bridge.write_text(r'''#ifndef KSU_SUSFS_COMPAT_H
#define KSU_SUSFS_COMPAT_H
#include <linux/string.h>
#include <linux/susfs.h>

static inline void ksu_susfs_add_sus_path(void __user **p)
{
#ifdef CONFIG_KSU_SUSFS_SUS_PATH
    susfs_add_sus_path((struct st_susfs_sus_path __user *)*p);
#endif
}
static inline void ksu_susfs_add_sus_kstat(void __user **p)
{
#ifdef CONFIG_KSU_SUSFS_SUS_KSTAT
    susfs_add_sus_kstat((struct st_susfs_sus_kstat __user *)*p);
#endif
}
static inline void ksu_susfs_update_sus_kstat(void __user **p)
{
#ifdef CONFIG_KSU_SUSFS_SUS_KSTAT
    susfs_update_sus_kstat((struct st_susfs_sus_kstat __user *)*p);
#endif
}
static inline void ksu_susfs_set_uname(void __user **p)
{
#ifdef CONFIG_KSU_SUSFS_SPOOF_UNAME
    susfs_set_uname((struct st_susfs_uname __user *)*p);
#endif
}
static inline void ksu_susfs_set_cmdline(void __user **p)
{
#ifdef CONFIG_KSU_SUSFS_SPOOF_CMDLINE_OR_BOOTCONFIG
    susfs_set_cmdline_or_bootconfig((char __user *)*p);
#endif
}
static inline void ksu_susfs_add_open_redirect(void __user **p)
{
#ifdef CONFIG_KSU_SUSFS_OPEN_REDIRECT
    susfs_add_open_redirect((struct st_susfs_open_redirect __user *)*p);
#endif
}
static inline bool susfs_starts_with(const char *str, const char *prefix)
{
    size_t n;
    if (!str || !prefix)
        return false;
    n = strlen(prefix);
    return strncmp(str, prefix, n) == 0;
}
static inline bool susfs_ends_with(const char *str, const char *suffix)
{
    size_t n, m;
    if (!str || !suffix)
        return false;
    n = strlen(str);
    m = strlen(suffix);
    return n >= m && memcmp(str + n - m, suffix, m) == 0;
}

#define susfs_add_sus_path(p)                       ksu_susfs_add_sus_path(p)
#define susfs_add_sus_path_loop(p)                  do { } while (0)
#define susfs_set_hide_sus_mnts_for_non_su_procs(p) do { } while (0)
#define susfs_add_sus_kstat(p)                      ksu_susfs_add_sus_kstat(p)
#define susfs_update_sus_kstat(p)                   ksu_susfs_update_sus_kstat(p)
#define susfs_set_uname(p)                          ksu_susfs_set_uname(p)
#define susfs_enable_log(p)                         susfs_set_log(true)
#define susfs_set_cmdline_or_bootconfig(p)          ksu_susfs_set_cmdline(p)
#define susfs_add_open_redirect(p)                  ksu_susfs_add_open_redirect(p)
#define susfs_add_sus_map(p)                        do { } while (0)
#define susfs_set_avc_log_spoofing(p)               do { } while (0)
#define susfs_get_enabled_features(p)               do { } while (0)
#define susfs_show_variant(p)                       do { } while (0)
#define susfs_show_version(p)                       do { } while (0)
#define susfs_start_sdcard_monitor_fn()              do { } while (0)
#endif
''')

# Ensure the common unity-build header sees the bridge after the legacy
# SUSFS declarations have been loaded.
common = Path("KernelSU/kernel/kernel_includes.h")
cs = common.read_text()
if '#include <linux/susfs_ksu_compat.h>' not in cs:
    anchor = '#include <linux/susfs.h>'
    if cs.count(anchor) != 1:
        raise SystemExit("kernel_includes.h: SUSFS include anchor mismatch")
    cs = cs.replace(anchor, anchor + '\n#include <linux/susfs_ksu_compat.h>', 1)
    common.write_text(cs)

# Keep dispatch calls in Nova's void ** form; compatibility macros above
# perform the typed conversion.
dispatch = Path("KernelSU/kernel/supercall/dispatch.c")
ds = dispatch.read_text()
for fn in ("susfs_add_sus_path", "susfs_add_sus_kstat",
           "susfs_update_sus_kstat", "susfs_set_uname",
           "susfs_set_cmdline_or_bootconfig", "susfs_add_open_redirect"):
    ds = ds.replace(f"{fn}(*arg);", f"{fn}(arg);")
dispatch.write_text(ds)

# SUSFS 1.5.5 stores the non-root-app marker in task_struct. Nova's newer
# LSM path expects these helpers and a deferred sus-path work item.
compat = Path("fs/susfs_compat.c")
compat.write_text(r'''// SPDX-License-Identifier: GPL-2.0
#include <linux/kernel.h>
#include <linux/sched.h>
#include <linux/susfs.h>
#include <linux/susfs_def.h>
#include <linux/workqueue.h>

struct work_struct susfs_extra_works;

static void susfs_compat_extra_work(struct work_struct *work)
{
#ifdef CONFIG_KSU_SUSFS_SUS_PATH
    susfs_run_sus_path_loop();
#endif
}

void susfs_compat_init_work(void)
{
    INIT_WORK(&susfs_extra_works, susfs_compat_extra_work);
}

void susfs_set_current_proc_no_su(void)
{
    /* Legacy SUSFS has no separate no-su task bit. */
}

void susfs_set_current_proc_umounted(void)
{
    current->susfs_task_state |= TASK_STRUCT_NON_ROOT_USER_APP_PROC;
}

void susfs_set_current_proc_umounted_for_zygote_next(void)
{
    current->susfs_task_state |= TASK_STRUCT_NON_ROOT_USER_APP_PROC;
}
''')

# Initialize the work item from the real SUSFS initializer; do not leave an
# uninitialized work_struct for Nova's setresuid hook to schedule.
susfs_c = Path("fs/susfs.c")
sc = susfs_c.read_text()
if "susfs_compat_init_work();" not in sc:
    m = re.search(r"(\nvoid\s+(?:__init\s+)?susfs_init\s*\([^)]*\)\s*\{)", sc)
    if not m:
        raise SystemExit("fs/susfs.c: cannot locate susfs_init() for workqueue initialization")
    sc = sc[:m.end()] + "\n    extern void susfs_compat_init_work(void);\n    susfs_compat_init_work();" + sc[m.end():]
    susfs_c.write_text(sc)
# The legacy SUSFS source declares this helper static in some 4.19/4.9
# patchsets; the compatibility workqueue lives in a separate translation unit.
sc, exported = re.subn(
    r"(?m)^static void susfs_run_sus_path_loop\(void\)",
    "void susfs_run_sus_path_loop(void)",
    sc,
)
if exported > 1:
    raise SystemExit("SUSFS loop helper has multiple definitions")
if "void susfs_run_sus_path_loop(void)" not in sc:
    raise SystemExit("SUSFS 1.5.5 core lacks susfs_run_sus_path_loop; cannot wire Nova workqueue safely")
if exported:
    susfs_c.write_text(sc)
if "TASK_STRUCT_NON_ROOT_USER_APP_PROC" not in Path("include/linux/susfs_def.h").read_text():
    raise SystemExit("Legacy SUSFS task-state marker is missing; refusing unsafe umount shim")

# The SELinux AVD registration API belongs to later SUSFS releases. The
# legacy 1.5.5 path retains its original policy generation logic.
sepolicy = Path("KernelSU/kernel/selinux/sepolicy.c")
sp = sepolicy.read_text()
sp2, n = re.subn(
    r"(?m)^\s*susfs_add_sus_avd_allowed_by_type\(src->value,\s*tgt->value,\s*cls->value,\s*node->datum\.u\.data\);\s*\n",
    "",
    sp,
)
if n != 1:
    raise SystemExit(f"sepolicy.c: expected one SUSFS 2.x AVD registration call, found {n}")
sepolicy.write_text(sp2)

# Add the compatibility object exactly once.
mk = Path("fs/Makefile")
ms = mk.read_text()
if "susfs_compat.o" not in ms:
    anchor = "obj-$(CONFIG_KSU_SUSFS) += susfs.o"
    if ms.count(anchor) != 1:
        raise SystemExit("fs/Makefile: SUSFS object anchor mismatch")
    mk.write_text(ms.replace(anchor, anchor + "\nobj-$(CONFIG_KSU_SUSFS) += susfs_compat.o", 1))

# Validate every previously unresolved API has a concrete implementation,
# wrapper, or explicit legacy-feature gate.
checks = {
    "compat workqueue": "struct work_struct susfs_extra_works" in compat.read_text(),
    "umount task marker": "current->susfs_task_state |= TASK_STRUCT_NON_ROOT_USER_APP_PROC" in compat.read_text(),
    "typed dispatch bridge": "ksu_susfs_add_sus_path" in bridge.read_text(),
    "legacy AVD gate": "susfs_add_sus_avd_allowed_by_type(" not in sepolicy.read_text(),
    "workqueue initialization": "susfs_compat_init_work();" in susfs_c.read_text(),
    "compat object": "susfs_compat.o" in mk.read_text(),
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit("SUSFS Nova compatibility validation failed: " + ", ".join(failed))
print("SukiSU Nova legacy SUSFS bridge and Linux 4.19 compatibility checks passed.")
