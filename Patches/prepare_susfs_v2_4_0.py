#!/usr/bin/env python3
"""Move SUSFS 2.4.0's legacy vfs_kern_mount allocator hook to Legion's fs_context API."""
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
data = path.read_text()
pattern = re.compile(
    r"@@ -953,7 \\+1109,22 @@ vfs_kern_mount\\(struct file_system_type \\*type, int flags, const char \\*name, void\\n"
    r".*?(?=@@ -1008,7 \\+1179,40 @@ static struct mount \\*clone_mnt)",
    re.S,
)
replacement = """@@ -1064,7 +1064,14 @@ struct vfsmount *vfs_create_mount(struct fs_context *fc)
 \	if (!fc->root)
 \	\treturn ERR_PTR(-EINVAL);
 \	sb = fc->root->d_sb;
 
-\tmnt = alloc_vfsmnt(fc->source ?: "none");
+#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT
+\t/* Preserve SUSFS KSU mount IDs on Legion's fs_context mount path. */
+\tif (static_branch_unlikely(&susfs_is_sdcard_android_data_not_decrypted) &&
+\t    susfs_is_current_ksu_domain())
+\t\tmnt = susfs_alloc_non_unshare_ksu_vfsmnt(fc->source ?: "none");
+\telse
+#endif
+\t\tmnt = alloc_vfsmnt(fc->source ?: "none");
 \	if (!mnt)
 \	\treturn ERR_PTR(-ENOMEM);
"""
data, count = pattern.subn(replacement, data, count=1)
if count != 1:
    raise SystemExit(f"Expected exactly one legacy vfs_kern_mount hunk, found {count}")
if "vfs_kern_mount(struct file_system_type" in data[data.find("diff --git a/fs/namespace.c"):data.find("diff --git a/fs/namespace.c")+20000]:
    raise SystemExit("Legacy vfs_kern_mount SUSFS hunk was not removed")
if "susfs_alloc_non_unshare_ksu_vfsmnt(fc->source ?: \"none\")" not in data:
    raise SystemExit("fs_context SUSFS allocator hook missing")
path.write_text(data)
print("Adapted SUSFS 2.4.0 mount hook to vfs_create_mount(fs_context).")
