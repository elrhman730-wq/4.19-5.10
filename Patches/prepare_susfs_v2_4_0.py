#!/usr/bin/env python3
"""Adapt the upstream SUSFS 2.4.0 Linux 4.19 patch to Legion's fs_context mount API."""
from pathlib import Path
import re
import sys

patch_path = Path(sys.argv[1])
data = patch_path.read_text()
pattern = re.compile(
    r"@@ -953,7 \+1109,22 @@ vfs_kern_mount\(struct file_system_type \*type, int flags, const char \*name, void.*?\n"
    r"(?=@@ -1008,7 \+1179,40 @@ static struct mount \*clone_mnt)",
    re.S,
)
replacement = """@@ -1050,7 +1057,14 @@ struct vfsmount *vfs_create_mount(struct fs_context *fc)
\tif (!fc->root)
\t\treturn ERR_PTR(-EINVAL);
\tsb = fc->root->d_sb;

-\tmnt = alloc_vfsmnt(fc->source ?: "none");
+#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT
+\t/* Legion uses the fs_context mount API instead of the older vfs_kern_mount flow. */
+\tif (static_branch_unlikely(&susfs_is_sdcard_android_data_not_decrypted) &&
+\t    susfs_is_current_ksu_domain())
+\t\tmnt = susfs_alloc_non_unshare_ksu_vfsmnt(fc->source ?: "none");
+\telse
+#endif
+\t\tmnt = alloc_vfsmnt(fc->source ?: "none");
 \tif (!mnt)
 \t\treturn ERR_PTR(-ENOMEM);
"""
data, count = pattern.subn(replacement, data, count=1)
if count != 1:
    raise SystemExit(f"Expected exactly one legacy vfs_kern_mount hunk, replaced {count}")
if "susfs_alloc_non_unshare_ksu_vfsmnt(fc->source ?: \"none\")" not in data:
    raise SystemExit("Legion fs_context SUSFS mount allocator hook missing")
patch_path.write_text(data)
print("Adapted SUSFS v2.4.0 mount allocator hook for Legion fs_context API.")
