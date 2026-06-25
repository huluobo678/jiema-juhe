"""阿里云邮件发送"""
import os, json, urllib.request, urllib.parse, hashlib, hmac, base64, uuid, datetime

ALIYUN_ACCESS_KEY = os.environ.get('ALIYUN_ACCESS_KEY', '')
ALIYUN_ACCESS_SECRET = os.environ.get('ALIYUN_ACCESS_SECRET', '')
ALIYUN_ACCOUNT_NAME = os.environ.get('ALIYUN_ACCOUNT_NAME', '')
ALIYUN_FROM_ALIAS = os.environ.get('ALIYUN_FROM_ALIAS', '接码平台')

# 阿里云 DirectMail API 版本
API_VERSION = '2015-11-23'
API_HOST = 'dm.aliyuncs.com'
API_METHOD = 'SingleSendMail'

def _sign(params, secret):
    """阿里云签名算法"""
    keys = sorted(params.keys())
    query = '&'.join(f'{urllib.parse.quote(k, safe="")}={urllib.parse.quote(str(params[k]), safe="")}' for k in keys)
    string_to_sign = f'POST&/&{urllib.parse.quote(query, safe="")}'
    h = hmac.new(secret.encode(), string_to_sign.encode(), hashlib.sha1).digest()
    return base64.b64encode(h).decode()

def send_email(to_address, subject, html_body):
    """发送邮件，返回 (ok, msg)"""
    if not ALIYUN_ACCESS_KEY or not ALIYUN_ACCESS_SECRET:
        # 开发模式：打印到日志
        print(f"[DEV EMAIL] To: {to_address}, Subject: {subject}, Body: {html_body[:100]}...")
        return (True, 'dev模式，邮件已记录日志')

    params = {
        'Action': API_METHOD,
        'Format': 'JSON',
        'Version': API_VERSION,
        'AccessKeyId': ALIYUN_ACCESS_KEY,
        'Timestamp': datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
        'SignatureMethod': 'HMAC-SHA1',
        'SignatureVersion': '1.0',
        'SignatureNonce': uuid.uuid4().hex,
        'AccountName': ALIYUN_ACCOUNT_NAME,
        'FromAlias': ALIYUN_FROM_ALIAS,
        'AddressType': '1',
        'ReplyToAddress': 'false',
        'ToAddress': to_address,
        'Subject': subject,
        'HtmlBody': html_body,
    }
    params['Signature'] = _sign(params, ALIYUN_ACCESS_SECRET + '&')

    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(f'https://{API_HOST}/', data=data, method='POST')
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        body = resp.read().decode()
        result = json.loads(body)
        if result.get('EnvId'):
            return (True, '发送成功')
        return (False, f'发送失败: {result}')
    except Exception as e:
        return (False, f'发送异常: {e}')

def send_verify_code(to_address, code):
    """发送邮箱验证码"""
    subject = '【接码平台】邮箱验证'
    body = f"""<div style="max-width:480px;margin:0 auto;padding:24px;font-family:sans-serif;">
    <h2 style="color:#4f46e5;">验证您的邮箱</h2>
    <p>您的验证码：</p>
    <div style="font-size:2rem;font-weight:800;color:#4f46e5;letter-spacing:8px;text-align:center;padding:20px;background:#f0f0ff;border-radius:8px;margin:16px 0">{code}</div>
    <p style="color:#666;font-size:0.85rem">有效期 10 分钟，请勿泄露。</p>
</div>"""
    return send_email(to_address, subject, body)