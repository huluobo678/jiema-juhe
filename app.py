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

@app.route('/__restart__')
def restart_app():
    """Restart the app process (requires nohup/supervisor to respawn)."""
    # 管理员 session 免密
    if flask_session.get('admin_username'):
        os._exit(0)
    pw = request.args.get('pw', '')
    if pw != SECRET_KEY[:16]:
        return 'unauthorized', 403
    os._exit(0)

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

if __name__ == '__main__':
    print("Front: http://127.0.0.1:5000")
    print("Admin: http://127.0.0.1:5000/admin")
    app.run(host='0.0.0.0', port=5000, debug=False)