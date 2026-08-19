"""redeploy_icons.py — 上传完整包并解压补全缺失文件"""
import os
import sys
import time
import paramiko

SERVER = "47.100.249.33"
ARCHIVE = os.path.join(os.environ.get("TEMP", "."), "deploy_xumo_full.tar.gz")

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
    sftp.put(ARCHIVE, "/tmp/deploy_xumo_full.tar.gz", callback=progress)
    print("\n上传完成")
    sftp.close()

    # 解压覆盖（保留 .env 等运行时文件，tar 包里没有 .env 所以不会被覆盖）
    run(ssh, "tar xzf /tmp/deploy_xumo_full.tar.gz -C /opt/xumo --overwrite", timeout=300)
    run(ssh, "rm -f /tmp/deploy_xumo_full.tar.gz")

    # 验证文件数量
    run(ssh, "find /opt/xumo/static -type f | wc -l")
    run(ssh, "find /opt/xumo/static/img/icons -type f | wc -l")

    # 重启服务（确保静态文件被识别）
    run(ssh, "systemctl restart xumo")
    time.sleep(5)
    run(ssh, "systemctl is-active xumo")

    # 测试图标访问
    run(ssh, "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/static/img/icons/t/logo.png -H 'Authorization: Bearer xumo2026'")
    # 直接通过应用测试（带 cookie/口令）
    run(ssh, "curl -s -o /dev/null -w '%{http_code}' 'http://127.0.0.1:8000/static/img/icons/t/heart.png'")

    ssh.close()
    print("\n完成")

if __name__ == "__main__":
    main()
