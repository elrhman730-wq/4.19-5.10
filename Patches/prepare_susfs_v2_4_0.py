#!/usr/bin/env python3
"""Adapt the SUSFS 2.4.0 legacy mount hook to Legion's fs_context mount path."""
from pathlib import Path
import sys

patch_path = Path(sys.argv[1])
data = patch_path.read_text()

# The upstream 4.19 patch hooks vfs_kern_mount(), but Legion's branch routes
# kernel mounts through fc_mount() -> vfs_create_mount(). Replace only that
# obsolete hunk; retain every other SUSFS 2.4.0 hunk unchanged.
start = "@@ -953,7 +1109,22 @@ vfs_kern_mount"
end = "@@ -1008,7 +1179,40 @@ static struct mount *clone_mnt"
if data.count(start) != 1:
    raise SystemExit(f"Expected one legacy vfs_kern_mount hunk, found {data.count(start)}")
if data.count(end) != 1:
    raise SystemExit(f"Expected one following clone_mnt hunk, found {data.count(end)}")

begin = data.index(start)
finish = data.index(end, begin)
replacement = """@@ -1064,7 +1064,14 @@ struct vfsmount *vfs_create_mount(struct fs_context *fc)
 	if (!fc->root)
 		return ERR_PTR(-EINVAL);
 	sb = fc->root->d_sb;
 
-	mnt = alloc_vfsmnt(fc->source ?: "none");
+#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT
+	/* Preserve SUSFS KSU mount IDs on Legion's fs_context mount path. */
+	if (static_branch_unlikely(&susfs_is_sdcard_android_data_not_decrypted) &&
+	    susfs_is_current_ksu_domain())
+		mnt = susfs_alloc_non_unshare_ksu_vfsmnt(fc->source ?: "none");
+	else
+#endif
+		mnt = alloc_vfsmnt(fc->source ?: "none");
 	if (!mnt)
 		return ERR_PTR(-ENOMEM);
"""
data = data[:begin] + replacement + data[finish:]

if "susfs_alloc_non_unshare_ksu_vfsmnt(fc->source ?: \"none\")" not in data:
    raise SystemExit("fs_context SUSFS allocator hook missing")
if start in data:
    raise SystemExit("Obsolete vfs_kern_mount hook remains")
if end not in data:
    raise SystemExit("clone_mnt SUSFS hunk was unexpectedly changed")

# Do not ship the upstream copy_mnt_ns insertion hunk at all. Its
# declared line counts become fragile when only the additions are stripped.
# The build workflow inserts CL_COPY_MNT_NS at a verified function-local
# anchor in fs/namespace.c after all remaining SUSFS hunks are applied.
import re
pattern = re.compile(
    r"(?m)^@@ -2945,6 \+3155,9 @@ struct mnt_namespace \*copy_mnt_ns.*?\n(?=^@@ -3527,3 \+3740,43 @@)",
    re.S,
)
data, removed = pattern.subn("", data)
if removed != 1:
    raise SystemExit(f"Expected to remove exactly one copy_mnt_ns hunk, removed {removed}")
if "copy_flags |= CL_COPY_MNT_NS;" in data:
    raise SystemExit("Unsafe copy_mnt_ns insertion remains in generated patch")

patch_path.write_text(data)
print("Adapted SUSFS 2.4.0 vfs_kern_mount hook to Legion vfs_create_mount(fs_context).")
