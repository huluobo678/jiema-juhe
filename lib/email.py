"""阿里云DirectMail SMTP 邮件发送"""
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from models import get_db
import os

def _get_config(key, default=''):
    env_map = {'smtp_host': 'SMTP_HOST', 'smtp_port': 'SMTP_PORT', 'smtp_user': 'SMTP_USER', 'smtp_pass': 'SMTP_PASS', 'smtp_from_name': 'SMTP_FROM_NAME'}
    env_key = env_map.get(key)
    if env_key:
        val = os.environ.get(env_key)
        if val:
            return val
    db = get_db()
    db.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))
    row = db.execute("SELECT value FROM site_config WHERE key=?", (key,)).fetchone()
    db.close()
    if row and row['value']:
        return row['value']
    return default

def send_email(to_address, subject, html_body):
    host = _get_config('smtp_host', 'smtpdm.aliyun.com')
    port = int(_get_config('smtp_port', '465'))
    user = _get_config('smtp_user', '')
    password = _get_config('smtp_pass', '')
    from_name = _get_config('smtp_from_name', '云枢智联')

    if not user or not password:
        return (False, '邮件服务未配置，请联系管理员')

    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = Header(subject, 'utf-8')
        msg['From'] = f"{from_name} <{user}>"
        msg['To'] = to_address
        msg.attach(MIMEText(html_body, 'html', 'utf-8'))

        server = smtplib.SMTP_SSL(host, port, timeout=15)
        server.login(user, password)
        server.sendmail(user, [to_address], msg.as_string())
        server.quit()
        return (True, '发送成功')
    except Exception as e:
        return (False, f'发送失败: {e}')

def send_verify_code(to_address, code):
    subject = '【云枢智联】邮箱验证'
    body = '<div style="max-width:480px;margin:0 auto;padding:24px;font-family:sans-serif;">'
    body += '<h2 style="color:#059669;">验证您的邮箱</h2>'
    body += '<p>您的验证码：</p>'
    body += '<div style="font-size:2rem;font-weight:800;color:#059669;letter-spacing:8px;text-align:center;padding:20px;background:#f0fdf4;border-radius:8px;margin:16px 0">' + code + '</div>'
    body += '<p style="color:#666;font-size:0.85rem">有效期 10 分钟，请勿泄露。</p></div>'
    return send_email(to_address, subject, body)
