from pathlib import Path
import re

path = Path("fs/namespace.c")
source = path.read_text()

def replace_once(old, new, label):
    global source
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    source = source.replace(old, new, 1)

# legacy SUSFS mount-ID no longer uses the extra zygote-copy flag.
replace_once(
    "#define CL_ZYGOTE_COPY_MNT_NS BIT(24) /* used by copy_mnt_ns() */\n",
    "",
    "remove obsolete zygote namespace flag",
)

# Add the legacy SUSFS mount-ID namespace walk variables to clone_mnt().
replace_once(
    "static struct mount *clone_mnt(struct mount *old, struct dentry *root,\n"
    "\t\t\t\t\tint flag)\n"
    "{\n"
    "#ifdef CONFIG_KDP_NS\n"
    "\tint ns_flags;\n"
    "\tstruct super_block *sb = old->mnt->mnt_sb;\n"
    "#else\n"
    "\tstruct super_block *sb = old->mnt.mnt_sb;\n"
    "#endif\n"
    "\tstruct mount *mnt;\n"
    "\tint err;\n",
    "static struct mount *clone_mnt(struct mount *old, struct dentry *root,\n"
    "\t\t\t\t\tint flag)\n"
    "{\n"
    "#ifdef CONFIG_KDP_NS\n"
    "\tint ns_flags;\n"
    "\tstruct super_block *sb = old->mnt->mnt_sb;\n"
    "#else\n"
    "\tstruct super_block *sb = old->mnt.mnt_sb;\n"
    "#endif\n"
    "\tstruct mount *mnt;\n"
    "\tint err;\n"
    "#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT\n"
    "\tstruct mount *m;\n"
    "\tstruct mnt_namespace *mnt_ns;\n"
    "\tint mnt_id;\n"
    "#endif\n",
    "add clone_mnt legacy SUSFS mount-ID variables",
)

# Port clone_mnt by anchoring the edit inside the actual function.
# Legion's base patch can leave the original one-argument allocator call
# in place because its surrounding source differs from upstream SUSFS.
clone_start = source.index("static struct mount *clone_mnt(")
clone_end = source.index("\nstatic void cleanup_mnt(", clone_start)
clone_func = source[clone_start:clone_end]
old_alloc = "\tmnt = alloc_vfsmnt(old->mnt_devname);\n"
if clone_func.count(old_alloc) == 1:
    new_alloc = (
        "#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT\n"
        "\t/* Route mount clones through SUSFS-aware mount-ID allocation. */\n"
        "\tif (unlikely(is_current_ksu_domain)) {\n"
        "\t\tif (!(flag & CL_COPY_MNT_NS)) {\n"
        "\t\t\tmnt = alloc_vfsmnt(old->mnt_devname, true, 0);\n"
        "\t\t} else {\n"
        "\t\t\tmnt = alloc_vfsmnt(old->mnt_devname, true, old->mnt_id);\n"
        "\t\t\tif (mnt)\n"
        "\t\t\t\tmnt->mnt.susfs_mnt_id_backup = DEFAULT_SUS_MNT_ID_FOR_KSU_PROC_UNSHARE;\n"
        "\t\t}\n"
        "\t} else if (likely(is_current_zygote_domain) && (old->mnt_id >= DEFAULT_SUS_MNT_ID)) {\n"
        "\t\tmnt = alloc_vfsmnt(old->mnt_devname, true, 0);\n"
        "\t} else if ((flag & CL_COPY_MNT_NS) && (old->mnt_id >= DEFAULT_SUS_MNT_ID)) {\n"
        "\t\tmnt = alloc_vfsmnt(old->mnt_devname, true, 0);\n"
        "\t} else {\n"
        "\t\tmnt = alloc_vfsmnt(old->mnt_devname, false, 0);\n"
        "\t}\n"
        "#else\n"
        "\tmnt = alloc_vfsmnt(old->mnt_devname);\n"
        "#endif\n"
    )
    clone_func = clone_func.replace(old_alloc, new_alloc, 1)
    source = source[:clone_start] + clone_func + source[clone_end:]
elif "alloc_vfsmnt(old->mnt_devname, false, 0);" not in clone_func:
    raise SystemExit(
        "clone_mnt allocator port: expected original one-argument call or an already-ported legacy SUSFS mount-ID call"
    )
if "struct mount *m;" not in clone_func:
    raise SystemExit("clone_mnt legacy SUSFS mount-ID namespace-walk declarations are missing")
if "struct mnt_namespace *mnt_ns;" not in clone_func:
    raise SystemExit("clone_mnt legacy SUSFS mount-ID namespace-walk declarations are missing")
if "int mnt_id;" not in clone_func:
    raise SystemExit("clone_mnt legacy SUSFS mount-ID namespace-walk declarations are missing")

# Keep the legacy one-argument allocator API for the rest of 4.19.
# SUSFS-specific callers use a dedicated helper with explicit ID policy.
source = source.replace(
    "static struct mount *alloc_vfsmnt(const char *name, bool should_spoof, int custom_mnt_id)",
    "static struct mount *alloc_vfsmnt_susfs(const char *name, bool should_spoof, int custom_mnt_id)",
)
source = source.replace(
    "static struct mount *alloc_vfsmnt(const char *name)\n#endif",
    "static struct mount *alloc_vfsmnt_susfs(const char *name)\n#endif",
)
# Convert only the explicit three-argument SUSFS allocation calls.
source = re.sub(
    r"\balloc_vfsmnt\(([^\n;]*?),\s*(true|false),\s*([^()\n;]*)\)",
    r"alloc_vfsmnt_susfs(\1, \2, \3)",
    source,
)
allocator_end = source.index("\n/*\n * Most r/o checks on a fs", source.index("static struct mount *alloc_vfsmnt_susfs("))
allocator_wrapper = (
    "\n#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT\n"
    "static struct mount *alloc_vfsmnt(const char *name)\n"
    "{\n"
    "\treturn alloc_vfsmnt_susfs(name, false, 0);\n"
    "}\n"
    "#else\n"
    "#define alloc_vfsmnt alloc_vfsmnt_susfs\n"
    "#endif\n"
)
source = source[:allocator_end] + allocator_wrapper + source[allocator_end:]

# The base patch's old fake-ID implementation was accidentally attached
# to vfs_create_mount(). Keep its SUSFS-aware allocator selection, but
# remove clone-only namespace-walk locals/logic from that function.
vfs_start = source.index("struct vfsmount *vfs_create_mount(")
vfs_end = source.index("\nEXPORT_SYMBOL(vfs_create_mount);", vfs_start)
vfs_func = source[vfs_start:vfs_end]
vfs_func = vfs_func.replace(
    "\tstruct mount *m;\n\tstruct mnt_namespace *mnt_ns;\n\tint mnt_id;\n", ""
)
vfs_func = re.sub(
    r"(?ms)^\s*// Calculate the next available fake mount ID in the current namespace\..*?^#endif\n",
    "",
    vfs_func,
)
# The legacy 4.19 allocator API is kept for ordinary mounts; only
# KernelSU-domain mounts request a SUSFS fake mount ID.
vfs_alloc = "\tmnt = alloc_vfsmnt(fc->source ?: \"none\");\n"
vfs_alloc_new = (
    "#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT\n"
    "\tif (unlikely(susfs_is_current_ksu_domain()))\n"
    "\t\tmnt = alloc_vfsmnt_susfs(fc->source ?: \"none\", true, 0);\n"
    "\telse\n"
    "\t\tmnt = alloc_vfsmnt(fc->source ?: \"none\");\n"
    "#else\n"
    "\tmnt = alloc_vfsmnt(fc->source ?: \"none\");\n"
    "#endif\n"
)
if vfs_func.count(vfs_alloc) != 1:
    raise SystemExit(f"vfs_create_mount allocator anchor: expected one match, found {vfs_func.count(vfs_alloc)}")
vfs_func = vfs_func.replace(vfs_alloc, vfs_alloc_new, 1)
source = source[:vfs_start] + vfs_func + source[vfs_end:]

# Ensure the state predicates belong to clone_mnt(), not a fuzz-matched
# neighboring function in the legacy base patch.
clone_start = source.index("static struct mount *clone_mnt(")
clone_end = source.index("\nstatic void cleanup_mnt(", clone_start)
clone_func = source[clone_start:clone_end]
if "bool is_current_ksu_domain = susfs_is_current_ksu_domain();" not in clone_func:
    clone_func = clone_func.replace(
        "\tint err;\n",
        "\tint err;\n#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT\n"
        "\tbool is_current_ksu_domain = susfs_is_current_ksu_domain();\n"
        "\tbool is_current_zygote_domain = susfs_is_current_zygote_domain();\n"
        "#endif\n",
        1,
    )
source = source[:clone_start] + clone_func + source[clone_end:]

# The legacy base patch's fake-ID hunk was removed because fuzzed
# context could place it in vfs_create_mount instead of clone_mnt.
# Remove any residual legacy block, then install legacy SUSFS mount-ID at a unique
# anchor inside clone_mnt().
import re
legacy_fake = re.compile(
    r"(?ms)^#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT\n"
    r"\t// If caller process is zygote and not doing unshare,.*?^#endif\n"
)
source, legacy_count = legacy_fake.subn("", source)
if legacy_count > 1:
    raise SystemExit(f"legacy clone_mnt fake-ID block appeared {legacy_count} times")
clone_start = source.index("static struct mount *clone_mnt(")
clone_end = source.index("\nstatic void cleanup_mnt(", clone_start)
clone_func = source[clone_start:clone_end]
anchor = "\tmnt->mnt_parent = mnt;\n"
if clone_func.count(anchor) != 1:
    raise SystemExit(
        f"clone_mnt fake-ID insertion anchor: expected one match, found {clone_func.count(anchor)}"
    )
new_fake_id = (
    "#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT\n"
    "\t/* Allocate the next available fake mount ID in this namespace. */\n"
    "\tif (likely(is_current_zygote_domain) && !(flag & CL_COPY_MNT_NS)) {\n"
    "\t\tmnt_ns = current->nsproxy->mnt_ns;\n"
    "\t\tif (mnt_ns) {\n"
    "\t\t\tget_mnt_ns(mnt_ns);\n"
    "\t\t\trcu_read_lock();\n"
    "\t\t\tmnt_id = list_first_entry(&mnt_ns->list, struct mount, mnt_list)->mnt_id;\n"
    "\t\t\tlist_for_each_entry_rcu(m, &mnt_ns->list, mnt_list) {\n"
    "\t\t\t\tif (m->mnt_id < DEFAULT_SUS_MNT_ID)\n"
    "\t\t\t\t\tmnt_id++;\n"
    "\t\t\t}\n"
    "\t\t\tWRITE_ONCE(mnt->mnt.susfs_mnt_id_backup, READ_ONCE(mnt->mnt_id));\n"
    "\t\t\tWRITE_ONCE(mnt->mnt_id, READ_ONCE(mnt_id));\n"
    "\t\t\trcu_read_unlock();\n"
    "\t\t\tput_mnt_ns(mnt_ns);\n"
    "\t\t}\n"
    "\t}\n"
    "#endif\n"
)
clone_func = clone_func.replace(anchor, anchor + new_fake_id, 1)
source = source[:clone_start] + clone_func + source[clone_end:]

# copy_tree() needs to account for clones before they are attached to mnt_ns->list.
replace_once(
    "struct mount *copy_tree(struct mount *mnt, struct dentry *dentry,\n"
    "\t\t\t\t\tint flag)\n"
    "{\n"
    "\tstruct mount *res, *p, *q, *r, *parent;\n",
    "struct mount *copy_tree(struct mount *mnt, struct dentry *dentry,\n"
    "\t\t\t\t\tint flag)\n"
    "{\n"
    "\tstruct mount *res, *p, *q, *r, *parent;\n"
    "#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT\n"
    "\tbool is_current_zygote_domain = susfs_is_current_zygote_domain();\n"
    "#endif\n",
    "add copy_tree zygote state",
)
replace_once(
    "\tlist_for_each_entry(r, &mnt->mnt_mounts, mnt_child) {\n"
    "\t\tstruct mount *s;\n",
    "\tlist_for_each_entry(r, &mnt->mnt_mounts, mnt_child) {\n"
    "\t\tstruct mount *s;\n"
    "#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT\n"
    "\t\tint attach_mnt_count = 0;\n"
    "#endif\n",
    "add copy_tree attach counter",
)
replace_once(
    "\t\t\tif (IS_ERR(q))\n"
    "\t\t\t\tgoto out;\n"
    "\t\t\tlock_mount_hash();\n",
    "\t\t\tif (IS_ERR(q))\n"
    "\t\t\t\tgoto out;\n"
    "#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT\n"
    "\t\t\tif (is_current_zygote_domain &&\n"
    "\t\t\t\t!(flag & CL_COPY_MNT_NS) &&\n"
    "\t\t\t\tq->mnt_id < DEFAULT_SUS_MNT_ID) {\n"
    "\t\t\t\tattach_mnt_count++;\n"
    "\t\t\t\tq->mnt_id += attach_mnt_count;\n"
    "\t\t\t}\n"
    "#endif\n"
    "\t\t\tlock_mount_hash();\n",
    "add copy_tree pre-attach ID correction",
)

# The old SUSFS patch used a zygote-only flag and a per-task fake-ID
# counter. legacy SUSFS mount-ID uses CL_COPY_MNT_NS only; install it in the real
# copy_mnt_ns() function, whose Legion body has CONFIG_KDP_NS branches.
import re
source = re.sub(
    r"(?ms)^#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT\n"
    r"\s*// Always let clone_mnt\(\).*?^#endif\n",
    "",
    source,
)
source = re.sub(
    r"(?ms)^#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT\n"
    r"\s*// Assign the 'last_entry_mnt_id'.*?^#endif\n",
    "",
    source,
)
copy_start = source.index("struct mnt_namespace *copy_mnt_ns(")
copy_end = source.index("\n/**\n * create_mnt_ns", copy_start)
copy_func = source[copy_start:copy_end]
copy_anchor = (
    "\tif (user_ns != ns->user_ns)\n"
    "\t\tcopy_flags |= CL_SHARED_TO_SLAVE | CL_UNPRIVILEGED;\n"
)
if copy_func.count(copy_anchor) != 1:
    raise SystemExit(
        f"copy_mnt_ns CL_COPY_MNT_NS anchor: expected one match, found {copy_func.count(copy_anchor)}"
    )
copy_func = copy_func.replace(
    copy_anchor,
    copy_anchor
    + "#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT\n"
    + "\tcopy_flags |= CL_COPY_MNT_NS;\n"
    + "#endif\n",
    1,
)
source = source[:copy_start] + copy_func + source[copy_end:]

if "CL_ZYGOTE_COPY_MNT_NS" in source:
    raise SystemExit("obsolete CL_ZYGOTE_COPY_MNT_NS reference remains")
if "current->susfs_last_fake_mnt_id" in source:
    raise SystemExit("obsolete per-task fake mount ID reference remains")
if source.count("Allocate the next available fake mount ID in this namespace.") != 1:
    raise SystemExit("legacy SUSFS mount-ID clone_mnt mount-ID algorithm was not installed exactly once")

path.write_text(source)
print("SUSFS legacy SUSFS mount-ID namespace logic ported with Legion CONFIG_KDP_NS layout checks.")
