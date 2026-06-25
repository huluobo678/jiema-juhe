import paramiko, time, sys
host, pw = '64.83.19.160', sys.argv[1]
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(host, port=2222, username='root', password=*** timeout=10)

client.exec_command('cd /root/sms-platform && git pull origin master 2>&1', timeout=30)
time.sleep(2)
client.exec_command('pkill -9 -f gunicorn 2>/dev/null; fuser -k 5000/tcp 2>/dev/null', timeout=5)
time.sleep(2)
client.exec_command('cd /root/sms-platform && nohup gunicorn -w 4 -b 0.0.0.0:5000 app:app > /tmp/gunicorn_btn.log 2>&1 &', timeout=5)
time.sleep(4)

stdin, stdout, _ = client.exec_command('ss -tlnp | grep 5000', timeout=5)
print('Port 5000:', 'OK' if stdout.read().decode().strip() else 'DEAD')
client.close()