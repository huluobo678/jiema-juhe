#!/usr/bin/env python3
"""部署接码平台到服务器"""
import os
import paramiko
import time

# 从环境变量读取，不要写死在代码里
HOST = os.environ.get('DEPLOY_HOST', '')
PORT = int(os.environ.get('DEPLOY_PORT', '2222'))
USER = os.environ.get('DEPLOY_USER', 'root')
PASS = os.environ.get('DEPLOY_PASS', '')
LOCAL_DIR = os.path.dirname(os.path.abspath(__file__))
REMOTE_DIR = os.environ.get('DEPLOY_REMOTE_DIR', '/root/sms-platform')
EXCLUDE = {'__pycache__', '*.db', '.git', '.env'}

if not HOST or not PASS:
    print("❌ 请设置环境变量 DEPLOY_HOST 和 DEPLOY_PASS")
    print("   推荐: 创建 .env 文件或用 export/set 命令")
    exit(1)

def should_exclude(name):
    for e in EXCLUDE:
        if e.startswith('*'):
            if name.endswith(e[1:]):
                return True
        elif name == e:
            return True
    return False

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
print("Connecting...")
ssh.connect(HOST, PORT, USER, PASS, look_for_keys=False, allow_agent=False)
print("Connected!")

# 1. Check environment and kill old app
print("Checking environment...")
ssh.exec_command("mkdir -p /root/sms-platform")
ssh.exec_command("kill $(lsof -t -i:5000 2>/dev/null) 2>/dev/null; sleep 1")

# 2. Upload files via SFTP
sftp = ssh.open_sftp()
print("Uploading files...")
uploaded = 0
for root, dirs, files in os.walk(LOCAL_DIR):
    dirs[:] = [d for d in dirs if not should_exclude(d)]
    for f in files:
        if should_exclude(f):
            continue
        local_path = os.path.join(root, f)
        rel_path = os.path.relpath(local_path, LOCAL_DIR)
        remote_path = os.path.join(REMOTE_DIR, rel_path).replace('\\', '/')
        remote_dir = os.path.dirname(remote_path)
        ssh.exec_command(f"mkdir -p {remote_dir}")
        sftp.put(local_path, remote_path)
        uploaded += 1
        if uploaded % 10 == 0:
            print(f"  Uploaded {uploaded} files...")

sftp.close()
print(f"Uploaded {uploaded} files total")

# 3. Install Python dependencies
print("Installing Python packages...")
stdin, stdout, stderr = ssh.exec_command("pip3 install flask requests", timeout=60)
err = stderr.read().decode()
if err:
    print("  pip stderr:", err[:500])
print("  pip done")

# 4. Start app via nohup
print("Starting app (port 5000)...")
cmd = f"cd {REMOTE_DIR} && nohup python3 app.py > app.log 2>&1 &"
ssh.exec_command(cmd)
time.sleep(3)

# 5. Check if it's running
stdin, stdout, stderr = ssh.exec_command("lsof -i:5000 2>/dev/null | head -5")
print("Port 5000 check:", stdout.read().decode().strip()[:200])

stdin, stdout, stderr = ssh.exec_command("curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:5000/")
code = stdout.read().decode().strip()
print(f"HTTP status: {code}")

ssh.close()

if code == '200':
    print("\n✅ 部署成功！")
    print(f"前台: http://{HOST}:5000")
    print(f"后台: http://{HOST}:5000/admin")
else:
    ssh2 = paramiko.SSHClient()
    ssh2.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh2.connect(HOST, PORT, USER, PASS, look_for_keys=False, allow_agent=False)
    stdin, stdout, stderr = ssh2.exec_command(f"tail -30 {REMOTE_DIR}/app.log")
    log = stdout.read().decode()
    print(f"\n❌ 部署失败，日志如下:\n{log}")
    ssh2.close()
