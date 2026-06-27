from flask import Flask, render_template, session as flask_session, request
from models import init_db
from config import SECRET_KEY
from views.user import user_bp
from views.admin import admin_bp
from channels import init_channels, get_registry
from lib.health import init_health_checker
from lib.scheduler import scheduler as llm_scheduler
import subprocess, os

app = Flask(__name__)
app.secret_key = SECRET_KEY

app.register_blueprint(user_bp)
app.register_blueprint(admin_bp)

# ---- Remote deploy endpoints (HTTP-triggered git pull + restart) ----

@app.route('/__deploy__')
def deploy_hook():
    """Trigger git pull on server via HTTP. Password = first 16 chars of SECRET_KEY.
    Or if admin session exists, skip password."""
    # 管理员 session 免密
    if flask_session.get('admin_username'):
        pass  # skip password check
    else:
        pw = request.args.get('pw', '')
        if pw != SECRET_KEY[:16]:
            return 'unauthorized', 403
    try:
        r = subprocess.run(
            ['git', 'fetch', 'origin', 'master'],
            capture_output=True, text=True, timeout=30,
            cwd=os.path.dirname(os.path.abspath(__file__)))
        if r.returncode != 0:
            return f'<pre>fetch失败: {r.stdout}{r.stderr}</pre>'
        r2 = subprocess.run(
            ['git', 'reset', '--hard', 'origin/master'],
            capture_output=True, text=True, timeout=30,
            cwd=os.path.dirname(os.path.abspath(__file__)))
        return f'<pre>{r.stdout}{r2.stdout}{r2.stderr}</pre>'
    except Exception as e:
        return f'<pre>ERROR: {e}</pre>'

@app.route('/__patch__', methods=['POST'])
def patch_files():
    """在线修补文件 - 管理员可直接上传修改内容并重启"""
    if not flask_session.get('admin_username'):
        return 'unauthorized', 403
    
    import json
    data = request.get_json(silent=True) or {}
    files = data.get('files', {})  # {relative_path: content}
    
    if not files:
        return '<pre>请提供 files 字典（path: content）</pre>'
    
    results = []
    for path, content in files.items():
        # 安全：只允许修复特定目录下的文件
        safe = path.replace('..', '').lstrip('/\\')
        full = os.path.join(os.path.dirname(os.path.abspath(__file__)), safe)
        if not full.startswith(os.path.dirname(os.path.abspath(__file__))):
            results.append(f'{path}: 路径不允许')
            continue
        try:
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, 'w', encoding='utf-8') as f:
                f.write(content)
            results.append(f'{path}: 写入成功')
        except Exception as e:
            results.append(f'{path}: 写入失败 - {e}')
    
    out = '<pre>' + '\n'.join(results) + '</pre>'
    out += '<p>信号重启中...</p>'
    try:
        subprocess.Popen(['pkill', '-f', 'gunicorn.*app:app'],
                         cwd=os.path.dirname(os.path.abspath(__file__)))
    except:
        pass
    return out


@app.route('/__restart__')
def restart_app():
    """重启应用（发 pkill 给 gunicorn）"""
    if flask_session.get('admin_username'):
        subprocess.Popen(['pkill', '-f', 'gunicorn.*app:app'],
                         cwd=os.path.dirname(os.path.abspath(__file__)))
        return '<pre>Restarting...</pre>'
    pw = request.args.get('pw', '')
    if pw != SECRET_KEY[:16]:
        return 'unauthorized', 403
    subprocess.Popen(['pkill', '-f', 'gunicorn.*app:app'],
                     cwd=os.path.dirname(os.path.abspath(__file__)))
    return 'restarting'

# ----------------------------------------------------------------

@app.context_processor
def inject_globals():
    ctx = {
        'session_username': flask_session.get('admin_username', ''),
        'balance': 0
    }
    token = request.cookies.get('account_token')
    if token:
        from models import get_db
        db = get_db()
        acc = db.execute("SELECT balance FROM accounts WHERE token=?", (token,)).fetchone()
        if acc:
            ctx['balance'] = acc['balance']
        db.close()
    return ctx

# ---- 启动时初始化 (gunicorn 兼容: 走 import 而非 __main__) ----
# 先把 db 表建好
init_db()
# 再注册渠道
from models import get_db
_db = get_db()
init_channels(_db)
_db.close()
# 启动健康检查器
init_health_checker(get_registry())
print("OI - 数据库初始化完成, 渠道注册 & 健康检查器已启动")
for ch in get_registry().get_all():
    print(f"I 渠道 {ch.name}: {'活' if ch.alive else '死'}, 并发 {ch.concurrency}/{ch.max_concurrency}")

@app.route('/__dbg__')
def debug_info():
    """服务器诊断 - 查看最新会话和日志摘要"""
    from models import get_db
    import subprocess
    db = get_db()
    rows = db.execute("SELECT id, phone, activation_id, status, channel_id, project_id, code, cost, created_at, received_at FROM sms_sessions ORDER BY id DESC LIMIT 5").fetchall()
    out = '<h2>最近会话</h2><pre>'
    for r in rows:
        out += str({k: r[k] for k in r.keys() if k != 'sms_content'}) + '\n'
    out += '</pre>'
    out += '<h2>渠道状态</h2><pre>'
    chs = db.execute("SELECT id, name, channel_type FROM channels").fetchall()
    for c in chs:
        out += str(dict(c)) + '\n'
    db.close()
    out += '</pre><h2>日志尾部</h2><pre>'
    try:
        r = subprocess.run(['tail','-30','/tmp/gunicorn.log'],capture_output=True,text=True,timeout=5)
        out += r.stdout[-2000:]
    except: out += '(gunicorn log not available)'
    out += '</pre>'
    return out


if __name__ == '__main__':
    print("Front: http://127.0.0.1:5000")
    print("Admin: http://127.0.0.1:5000/admin")
    app.run(host='0.0.0.0', port=5000, debug=False)