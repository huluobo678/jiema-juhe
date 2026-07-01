from flask import Flask, session as flask_session, request, abort
from models import init_db, get_db
from config import SECRET_KEY
from views.user import user_bp
from views.admin import admin_bp
from channels import init_channels, get_registry
from lib.health import init_health_checker
import subprocess
import os
import time

os.environ.setdefault('TZ', 'Asia/Shanghai')
if hasattr(time, 'tzset'):
    time.tzset()

app = Flask(__name__)
app.secret_key = SECRET_KEY

app.register_blueprint(user_bp)
app.register_blueprint(admin_bp)


def _maintenance_allowed():
    token = os.environ.get('MAINTENANCE_TOKEN', '')
    return bool(token) and request.args.get('token') == token


@app.route('/__deploy__')
def deploy_hook():
    if not _maintenance_allowed():
        abort(404)
    try:
        app_dir = os.path.dirname(os.path.abspath(__file__))
        fetch = subprocess.run(
            ['git', 'fetch', 'origin', 'master'],
            capture_output=True, text=True, timeout=30, cwd=app_dir)
        if fetch.returncode != 0:
            return f'<pre>fetch failed: {fetch.stdout}{fetch.stderr}</pre>', 500
        reset = subprocess.run(
            ['git', 'reset', '--hard', 'origin/master'],
            capture_output=True, text=True, timeout=30, cwd=app_dir)
        status = 200 if reset.returncode == 0 else 500
        return f'<pre>{fetch.stdout}{reset.stdout}{reset.stderr}</pre>', status
    except Exception as exc:
        return f'<pre>ERROR: {exc}</pre>', 500


@app.route('/__patch__', methods=['POST'])
def patch_files():
    if not _maintenance_allowed():
        abort(404)
    if not flask_session.get('admin_logged_in'):
        return 'unauthorized', 403

    data = request.get_json(silent=True) or {}
    files = data.get('files', {})
    if not files:
        return '<pre>missing files dict</pre>', 400

    app_dir = os.path.dirname(os.path.abspath(__file__))
    results = []
    for path, content in files.items():
        safe = path.replace('..', '').lstrip('/\\')
        full = os.path.abspath(os.path.join(app_dir, safe))
        if not full.startswith(app_dir + os.sep):
            results.append(f'{path}: path not allowed')
            continue
        try:
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, 'w', encoding='utf-8') as handle:
                handle.write(content)
            results.append(f'{path}: written')
        except Exception as exc:
            results.append(f'{path}: write failed - {exc}')

    try:
        subprocess.Popen(['pkill', '-f', 'gunicorn.*app:app'], cwd=app_dir)
    except Exception:
        pass
    return '<pre>' + '\n'.join(results) + '</pre>'


@app.route('/__restart__')
def restart_app():
    if not _maintenance_allowed():
        abort(404)
    app_dir = os.path.dirname(os.path.abspath(__file__))
    subprocess.Popen(['pkill', '-f', 'gunicorn.*app:app'], cwd=app_dir)
    return 'restarting'


@app.context_processor
def inject_globals():
    ctx = {
        'session_username': flask_session.get('admin_username', ''),
        'balance': 0,
        'is_vip': False,
    }
    token = request.cookies.get('account_token')
    if token:
        db = get_db()
        acc = db.execute('SELECT balance, is_vip FROM accounts WHERE token=?', (token,)).fetchone()
        if acc:
            ctx['balance'] = acc['balance']
            ctx['is_vip'] = bool(acc['is_vip'] if 'is_vip' in acc.keys() else 0)
        db.close()
    return ctx


init_db()
_db = get_db()
init_channels(_db)
_db.close()
init_health_checker(get_registry())
print('database initialized, channels registered, health checker started')
for ch in get_registry().get_all():
    print(f'channel {ch.name}: {"alive" if ch.alive else "dead"}, concurrency {ch.concurrency}/{ch.max_concurrency}')


@app.route('/__dbg__')
def debug_info():
    if not flask_session.get('admin_logged_in'):
        abort(404)
    db = get_db()
    rows = db.execute('''
        SELECT id, phone, activation_id, status, channel_id, project_id, code, cost, created_at, received_at
        FROM sms_sessions ORDER BY id DESC LIMIT 5
    ''').fetchall()
    out = '<h2>Recent sessions</h2><pre>'
    for row in rows:
        out += str({key: row[key] for key in row.keys() if key != 'sms_content'}) + '\n'
    out += '</pre><h2>Channels</h2><pre>'
    channels = db.execute('SELECT id, name, channel_type FROM channels').fetchall()
    for channel in channels:
        out += str(dict(channel)) + '\n'
    db.close()
    out += '</pre><h2>Log tail</h2><pre>'
    try:
        result = subprocess.run(['tail', '-30', '/tmp/gunicorn.log'], capture_output=True, text=True, timeout=5)
        out += result.stdout[-2000:]
    except Exception:
        out += '(gunicorn log not available)'
    out += '</pre>'
    return out


if __name__ == '__main__':
    print('Front: http://127.0.0.1:5000')
    print('Admin: http://127.0.0.1:5000/admin')
    app.run(host='0.0.0.0', port=5000, debug=False)
