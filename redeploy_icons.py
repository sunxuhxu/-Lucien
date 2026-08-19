"""redeploy_icons.py — 上传完整包并解压补全缺失文件"""
import os
import sys
import time
import paramiko

SERVER = "47.100.249.33"
ARCHIVE = os.path.join(os.environ.get("TEMP", "."), "deploy_xumo_full.tar.gz")
TARGET_DIR = "/opt/lucien"
SERVICE = "lucien"
REMOTE_ARCHIVE = "/tmp/deploy_lucien_release.tar.gz"

def progress(transferred, total):
    pct = transferred * 100 // total
    mb = transferred / (1024 * 1024)
    total_mb = total / (1024 * 1024)
    sys.stdout.write(f"\r  [{mb:.1f}/{total_mb:.1f} MB] {pct}%")
    sys.stdout.flush()

def run(ssh, cmd, timeout=300):
    print(f"\n>>> {cmd}")
    _, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace").strip()
    err = stderr.read().decode("utf-8", errors="replace").strip()
    rc = stdout.channel.recv_exit_status()
    if out:
        print(out)
    if err:
        print(f"[stderr] {err}")
    return out, err, rc

def main():
    size_mb = os.path.getsize(ARCHIVE) / 1024 / 1024
    print(f"连接服务器并上传完整包 ({size_mb:.1f} MB)...")

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(SERVER, username="root", password="xumo.2026", timeout=15)

    sftp = ssh.open_sftp()
    sftp.put(ARCHIVE, REMOTE_ARCHIVE, callback=progress)
    print("\n上传完成")
    sftp.close()

    # 发布前备份会被覆盖的核心代码，便于故障时快速回滚。
    run(
        ssh,
        f"mkdir -p {TARGET_DIR}/releases && "
        f"tar czf {TARGET_DIR}/releases/pre-deploy-$(date +%Y%m%d_%H%M%S).tar.gz "
        f"-C {TARGET_DIR} app.py creative_apps.py deep_apps.py extensions.json "
        "life_apps.py nova_apps.py pocket_apps.py story_apps.py video_apps.py "
        "wonder_apps.py static/index.html static/extension_editor.html",
        timeout=300,
    )

    # 解压覆盖（保留 .env 等运行时文件，tar 包里没有 .env 所以不会被覆盖）
    _, _, extract_rc = run(ssh, f"tar xzf {REMOTE_ARCHIVE} -C {TARGET_DIR} --overwrite", timeout=300)
    if extract_rc != 0:
        raise RuntimeError("发布包解压失败")
    run(ssh, f"rm -f {REMOTE_ARCHIVE}")

    # 验证文件数量
    run(ssh, f"find {TARGET_DIR}/static -type f | wc -l")
    run(ssh, f"find {TARGET_DIR}/static/img/icons -type f | wc -l")

    # 重启服务（确保静态文件被识别）
    # 旧 xumo.service 与正式 lucien.service 争用 8000 端口；确保旧服务停止。
    run(ssh, "systemctl stop xumo")
    run(ssh, f"systemctl restart {SERVICE}")
    time.sleep(5)
    run(ssh, f"systemctl is-active {SERVICE}")

    # 测试图标访问
    _, _, health_rc = run(
        ssh,
        "for i in $(seq 1 20); do "
        "code=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/health); "
        "if [ \"$code\" = 200 ]; then echo 200; exit 0; fi; sleep 2; done; "
        "echo health-check-failed; exit 1",
        timeout=60,
    )
    if health_rc != 0:
        raise RuntimeError("lucien 服务健康检查失败")
    run(ssh, f"test -f {TARGET_DIR}/static/coze-restore.js && test -f {TARGET_DIR}/static/premium-ui.css && echo assets-ok")

    ssh.close()
    print("\n完成")

if __name__ == "__main__":
    main()
