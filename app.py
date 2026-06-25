from flask import Flask, render_template, session as flask_session, request
from models import init_db
from config import SECRET_KEY
from views.user import user_bp
from views.admin import admin_bp
import subprocess, os

app = Flask(__name__)
app.secret_key = SECRET_KEY

app.register_blueprint(user_bp)
app.register_blueprint(admin_bp)

# ---- Remote deploy endpoints (HTTP-triggered git pull + restart) ----

@app.route('/__deploy__')
def deploy_hook():
    """Trigger git pull on server via HTTP. Password = first 16 chars of SECRET_KEY."""
    pw = request.args.get('pw', '')
    if pw != SECRET_KEY[:16]:
        return 'unauthorized', 403
    try:
        r = subprocess.run(['git', 'pull', 'origin', 'master'],
                           capture_output=True, text=True, timeout=60,
                           cwd=os.path.dirname(os.path.abspath(__file__)))
        return f'<pre>{r.stdout}{r.stderr}</pre>'
    except Exception as e:
        return f'<pre>ERROR: {e}</pre>'

@app.route('/__restart__')
def restart_app():
    """Restart the app process (requires nohup/supervisor to respawn)."""
    pw = request.args.get('pw', '')
    if pw != SECRET_KEY[:16]:
        return 'unauthorized', 403
    os._exit(0)

# ----------------------------------------------------------------

@app.context_processor
def inject_globals():
    return {
        'session_username': flask_session.get('admin_username', '')
    }

if __name__ == '__main__':
    init_db()
    print("OK - 数据库初始化完成")
    print("Front: http://127.0.0.1:5000")
    print("Admin: http://127.0.0.1:5000/admin")
    print("Default admin: admin / admin123")
    app.run(host='0.0.0.0', port=5000, debug=False)