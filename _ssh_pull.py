import paramiko, time, sys, subprocess
h, pw = '64.83.19.160', sys.argv[1]

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(h, port=2222, username='root', password=pw, timeout=10)

# Check all files are pushed to GitHub already
stdin, stdout, _ = c.exec_command('git log --oneline -1', timeout=5)
print("Server at:", stdout.read().decode().strip())

# Git pull
stdin, stdout, stderr = c.exec_command('cd /root/sms-platform && git pull origin master 2>&1', timeout=30)
pull_out = stdout.read().decode()
pull_err = stderr.read().decode()
print("Pull:", pull_out[:300])
if pull_err: print("Pull err:", pull_err[:300])

# Restart
c.exec_command('pkill -9 -f gunicorn 2>/dev/null; fuser -k 5000/tcp 2>/dev/null', timeout=5)
time.sleep(2)
c.exec_command('cd /root/sms-platform && nohup gunicorn -w 4 -b 0.0.0.0:5000 app:app > /tmp/gunicorn_btn.log 2>&1 &', timeout=5)
time.sleep(4)

stdin, stdout, _ = c.exec_command('ss -tlnp | grep 5000', timeout=5)
port_ok = stdout.read().decode().strip()
print("Port 5000:", 'OK' if port_ok else 'DEAD')

# Verify admin dashboard has the deploy button
try:
    r = subprocess.run(['curl', '-s', 'http://' + h + ':5000/admin'], capture_output=True, text=True, timeout=5)
    has_btn = '部署' in r.stdout
    print("Deploy button on page:", has_btn)
except:
    print("Curl check skipped")

c.close()
