"""repack.py — 用 Python tarfile 重新打包（容错跳过无法读取的文件）"""
import os
import sys
import tarfile

ROOT = r"G:\xumo"
OUT = os.path.join(os.environ.get("TEMP", "."), "deploy_xumo_full.tar.gz")

# 排除的顶级目录
EXCLUDE_DIRS = {
    "__pycache__", ".cache", ".deps", ".libs", ".numba_cache", ".snapshots",
    ".uploads", ".workbuddy", ".devin", ".git", "logs", "uploads",
    "chat_archives", "guest_data", "models", "node_modules", "users_data",
    "generated-images", "scripts", "ngrok", "katago",
    ".numba_cache",
}
# 排除的顶级文件/目录（精确匹配）
# 注意：.env 必须排除，否则会用本地配置覆盖服务器配置（端口/口令/API Key）
EXCLUDE_TOP = {
    "deploy_xumo.tar.gz", "deploy_xumo_full.tar.gz",
    "guest_cookie.txt", "certs",
    ".env", ".env.local", ".secret",
}
# 排除的文件扩展名
EXCLUDE_EXT = {
    ".log", ".wav", ".tmp", ".bak", ".pyc",
}
# 排除的目录（任意层级）
EXCLUDE_ANYWHERE = {
    "__pycache__", ".cache", ".snapshots", "img2img", "img_quota", "tts_log", "call_rec",
}

skipped = []
count = 0

def filter_fn(info):
    return info

def main():
    global count
    if os.path.exists(OUT):
        os.remove(OUT)

    with tarfile.open(OUT, "w:gz", compresslevel=6) as tar:
        for dirpath, dirnames, filenames in os.walk(ROOT):
            # 过滤子目录
            rel_dir = os.path.relpath(dirpath, ROOT)
            if rel_dir == ".":
                dirnames[:] = [d for d in dirnames
                               if d not in EXCLUDE_DIRS and d not in EXCLUDE_TOP]
            else:
                dirnames[:] = [d for d in dirnames if d not in EXCLUDE_ANYWHERE]

            for fn in filenames:
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, ROOT).replace("\\", "/")
                ext = os.path.splitext(fn)[1].lower()
                if rel_dir == "." and fn in EXCLUDE_TOP:
                    continue
                if ext in EXCLUDE_EXT:
                    continue
                if fn.startswith("_diag") or fn.startswith(".diag"):
                    continue
                try:
                    tar.add(full, arcname="./" + rel, recursive=False)
                    count += 1
                except (OSError, PermissionError, FileNotFoundError) as e:
                    skipped.append((rel, str(e)))
                # 目录本身也要加入（保留空目录结构）
            # 添加目录条目（保证目录结构存在）
            if rel_dir != ".":
                try:
                    tar.add(dirpath, arcname="./" + rel_dir.replace("\\", "/"), recursive=False)
                except (OSError, PermissionError):
                    pass

    size_mb = os.path.getsize(OUT) / 1024 / 1024
    print(f"打包完成: {OUT}")
    print(f"文件数: {count}, 大小: {size_mb:.1f} MB")
    if skipped:
        print(f"跳过 {len(skipped)} 个无法读取的文件:")
        for rel, err in skipped[:20]:
            print(f"  - {rel}: {err}")

if __name__ == "__main__":
    main()
