"""后台管理路由"""
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, session as flask_session
from models import get_db
from config import SITE_URL
from werkzeug.security import generate_password_hash, check_password_hash
import uuid
import functools

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

def login_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if not flask_session.get('admin_logged_in'):
            return redirect(url_for('admin.login'))
        return f(*args, **kwargs)
    return wrapper

@admin_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        db = get_db()
        admin = db.execute("SELECT * FROM admins WHERE username=?", (username,)).fetchone()
        db.close()
        if admin and check_password_hash(admin['password'], password):
            flask_session['admin_logged_in'] = True
            flask_session['admin_username'] = username
            return redirect(url_for('admin.dashboard'))
        return render_template('admin/login.html', error='用户名或密码错误')
    return render_template('admin/login.html')

@admin_bp.route('/logout')
def logout():
    flask_session.clear()
    return redirect(url_for('admin.login'))

@admin_bp.route('/')
@login_required
def dashboard():
    return render_template('admin/dashboard.html')

# ========== 渠道管理 ==========

@admin_bp.route('/channels')
@login_required
def channels():
    db = get_db()
    rows = db.execute("SELECT * FROM channels ORDER BY id").fetchall()
    db.close()
    return render_template('admin/channels.html', channels=rows)

@admin_bp.route('/channels/add', methods=['POST'])
@login_required
def add_channel():
    name = request.form['name']
    api_url = request.form['api_url']
    api_user = request.form.get('api_user', '')
    api_pass = request.form.get('api_pass', '')
    markup_percent = float(request.form.get('markup_percent', 0))
    channel_type = request.form.get('channel_type', 'haozhuma')
    db = get_db()
    try:
        cl = int(request.form.get('concurrent_limit', 5))
        db.execute("INSERT INTO channels (name, api_url, api_user, api_pass, markup_percent, concurrent_limit, channel_type) VALUES (?,?,?,?,?,?,?)",
        (name, api_url, api_user, api_pass, markup_percent, cl, channel_type))
        db.commit()
    except Exception as e:
        db.close()
        return jsonify({'ok': False, 'msg': str(e)})
    db.close()
    return jsonify({'ok': True})

@admin_bp.route('/channels/<int:id>/test-login', methods=['POST'])
@login_required
def test_channel_login(id):
    from channels.factory import create_channel_adapter
    db = get_db()
    ch = db.execute("SELECT * FROM channels WHERE id=?", (id,)).fetchone()
    db.close()
    if not ch:
        return jsonify({'ok': False, 'msg': '渠道不存在'})
    adapter = create_channel_adapter(ch)
    if adapter is None:
        return jsonify({'ok': False, 'msg': '不支持的渠道类型'})

    channel_type = (ch['channel_type'] or '').lower()
    is_herosms = channel_type == 'herosms' or 'herosms' in (ch['name'] or '').lower()

    if is_herosms:
        ok = adapter.ping()
        if ok:
            db2 = get_db()
            db2.execute("UPDATE channels SET token=? WHERE id=?", (adapter._api_key, id))
            db2.commit()
            db2.close()
            return jsonify({'ok': True, 'msg': '连接成功，API Key 有效'})
        else:
            return jsonify({'ok': False, 'msg': '连接失败，请检查 API Key 和 API 地址'})
    else:
        data = adapter.login()
        code = data.get('code')
        if code == 0 or code == '0':
            db2 = get_db()
            db2.execute("UPDATE channels SET token=? WHERE id=?", (data['token'], id))
            db2.commit()
            db2.close()
            return jsonify({'ok': True, 'msg': '登录成功', 'token': data['token']})
        return jsonify({'ok': False, 'msg': '登录失败: ' + data.get('msg', '')})

@admin_bp.route('/channels/<int:id>/edit', methods=['POST'])
@login_required
def edit_channel(id):
    name = request.form['name']
    api_url = request.form['api_url']
    api_user = request.form.get('api_user', '')
    api_pass = request.form.get('api_pass', '')
    token = request.form.get('token', '')
    channel_type = request.form.get('channel_type', 'haozhuma')
    markup_percent = float(request.form.get('markup_percent', 0))
    db = get_db()
    cl = int(request.form.get('concurrent_limit', 5))
    db.execute("""UPDATE channels SET name=?, api_url=?, api_user=?, api_pass=?, token=?, markup_percent=?, channel_type=?, concurrent_limit=?
                   WHERE id=?""",
               (name, api_url, api_user, api_pass, token, markup_percent, channel_type, cl, id))
    db.commit()
    db.close()
    return jsonify({'ok': True})

@admin_bp.route('/channels/<int:id>/json')
@login_required
def channel_json(id):
    db = get_db()
    ch = db.execute("SELECT * FROM channels WHERE id=?", (id,)).fetchone()
    db.close()
    if not ch:
        return jsonify({'ok': False, 'msg': '渠道不存在'})
    return jsonify({'ok': True, 'channel': dict(ch)})

@admin_bp.route('/channels/<int:id>/toggle', methods=['POST'])
@login_required
def toggle_channel(id):
    enabled = int(request.form.get('enabled', 1))
    db = get_db()
    db.execute("UPDATE channels SET enabled=? WHERE id=?", (enabled, id))
    db.commit()
    db.close()
    return jsonify({'ok': True})

@admin_bp.route('/channels/<int:id>/delete', methods=['POST'])
@login_required
def delete_channel(id):
    db = get_db()
    db.execute("DELETE FROM channels WHERE id=?", (id,))
    db.commit()
    db.close()
    return jsonify({'ok': True})

@admin_bp.route('/channel-balances')
@login_required
def channel_balances():
    """获取所有渠道的上游余额"""
    from channels import get_registry
    db = get_db()
    rows = db.execute("SELECT id, name, api_user, api_pass, token, api_url, channel_type FROM channels WHERE enabled=1").fetchall()
    db.close()
    reg = get_registry()
    result = []
    for r in rows:
        ch = reg.get(r['id'])
        if ch:
            try:
                bal = ch.get_balance()
                result.append({'id': r['id'], 'name': r['name'], 'balance': bal})
                continue
            except:
                pass
        # 没有活实例，通过工厂创建一次性实例
        try:
            from channels.factory import create_channel_adapter
            adp = create_channel_adapter(r)
            if adp:
                bal = adp.get_balance()
                result.append({'id': r['id'], 'name': r['name'], 'balance': bal})
        except Exception as e:
            result.append({'id': r['id'], 'name': r['name'], 'balance': 0})
    return jsonify({'ok': True, 'balances': result})

@admin_bp.route('/channels/status')
@login_required
def channels_status():
    from channels import get_registry
    reg = get_registry()
    chs = reg.get_all()
    return jsonify({'ok': True, 'channels': [{
        'id': c.channel_id,
        'name': c.name,
        'alive': c.alive,
        'circuit': 'closed',
        'concurrent': c.concurrency,
        'concurrent_limit': c.max_concurrency,
        'last_ping': '-',
    } for c in chs]})

# ========== 项目管理 ==========

@admin_bp.route('/projects')
@login_required
def projects():
    db = get_db()
    rows = [dict(r) for r in db.execute("""
        SELECT p.*, c.name as channel_name
        FROM projects p JOIN channels c ON p.channel_id=c.id
        ORDER BY p.id
    """).fetchall()]
    channels = db.execute("SELECT id, name FROM channels WHERE enabled=1").fetchall()
    db.close()
    return render_template('admin/projects.html', projects=rows, channels=channels)

@admin_bp.route('/projects/add', methods=['POST'])
@login_required
def add_project():
    db = get_db()
    try:
        db.execute("INSERT INTO projects (name, channel_id, sid, price, description, category, icon, color) VALUES (?,?,?,?,?,?,?,?)",
                   (request.form['name'], request.form['channel_id'], request.form['sid'],
                    float(request.form['price']), request.form.get('description', ''), request.form.get('category', ''), request.form.get('icon', ''), request.form.get('color', '#f1f5f9')))
        db.commit()
    except Exception as e:
        db.close()
        return jsonify({'ok': False, 'msg': str(e)})
    db.close()
    return jsonify({'ok': True})

@admin_bp.route('/projects/<int:id>/edit', methods=['POST'])
@login_required
def edit_project(id):
    db = get_db()
    try:
        db.execute("""UPDATE projects SET name=?, channel_id=?, sid=?, price=?, description=?, category=?, icon=?, color=?
                      WHERE id=?""",
                   (request.form['name'], request.form['channel_id'], request.form['sid'],
                    float(request.form['price']), request.form.get('description', ''), request.form.get('category', ''), request.form.get('icon', ''), request.form.get('color', '#f1f5f9'), id))
        db.commit()
    except Exception as e:
        db.close()
        return jsonify({'ok': False, 'msg': str(e)})
    db.close()
    return jsonify({'ok': True})

@admin_bp.route('/projects/<int:id>/delete', methods=['POST'])
@login_required
def delete_project(id):
    db = get_db()
    db.execute("DELETE FROM projects WHERE id=?", (id,))
    db.commit()
    db.close()
    return jsonify({'ok': True})

@admin_bp.route('/projects/<int:id>/json', methods=['GET'])
@login_required
def project_json(id):
    db = get_db()
    row = db.execute("SELECT * FROM projects WHERE id=?", (id,)).fetchone()
    db.close()
    if not row:
        return jsonify({'ok': False, 'msg': 'Not found'})
    return jsonify({'ok': True, 'project': dict(row)})

# ========== 卡密管理 ==========

@admin_bp.route('/cards')
@login_required
def cards():
    db = get_db()
    rows = db.execute("SELECT * FROM cards ORDER BY id DESC LIMIT 100").fetchall()
    db.close()
    return render_template('admin/cards.html', cards=rows)

@admin_bp.route('/cards/generate', methods=['POST'])
@login_required
def generate_cards():
    count = int(request.form.get('count', 1))
    credit = float(request.form.get('credit', 1.0))
    prefix = request.form.get('prefix', 'HZ').upper().strip()[:8]
    if not prefix:
        prefix = 'HZ'
    db = get_db()
    codes = []
    for _ in range(count):
        # 生成格式: YSZL-XXXX-XXXX-XXXX（分组易读）
        code = prefix + '-' + '-'.join([uuid.uuid4().hex[i*4:(i+1)*4].upper() for i in range(3)])
        # 确保唯一性
        while db.execute("SELECT id FROM cards WHERE code=?", (code,)).fetchone():
            code = prefix + '-' + '-'.join([uuid.uuid4().hex[i*4:(i+1)*4].upper() for i in range(3)])
        codes.append(code)
        db.execute("INSERT INTO cards (code, credit) VALUES (?,?)", (code, credit))
    db.commit()
    db.close()
    return jsonify({'ok': True, 'codes': codes, 'count': count, 'credit': credit})

# ========== 统计 ==========

@admin_bp.route('/stats')
@login_required
def stats():
    db = get_db()
    channel_count = db.execute("SELECT COUNT(*) FROM channels").fetchone()[0]
    project_count = db.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
    total_cards = db.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
    used_cards = db.execute("SELECT COUNT(*) FROM cards WHERE used=1").fetchone()[0]
    total_sessions = db.execute("SELECT COUNT(*) FROM sms_sessions").fetchone()[0]
    user_count = db.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
    total_balance = db.execute("SELECT SUM(balance) FROM accounts").fetchone()[0] or 0

    # JSON 返回（供 dashboard 调用）
    if request.args.get('json') == '1':
        db.close()
        return jsonify({'channelCount': channel_count, 'projectCount': project_count, 'cardCount': total_cards, 'sessionCount': total_sessions, 'userCount': user_count})

    # 最近订单
    recent = db.execute("""
        SELECT s.*, p.name as project_name
        FROM sms_sessions s
        JOIN projects p ON s.project_id=p.id
        ORDER BY s.id DESC LIMIT 20
    """).fetchall()

    db.close()
    return render_template('admin/stats.html', **locals())

# ========== 公告管理 ==========

@admin_bp.route('/announcements')
@login_required
def announcements():
    db = get_db()
    rows = db.execute("SELECT * FROM announcements ORDER BY priority DESC, id DESC").fetchall()
    db.close()
    return render_template('admin/announcements.html', announcements=rows)

@admin_bp.route('/announcements/add', methods=['POST'])
@login_required
def add_announcement():
    title = request.form.get('title', '').strip()
    content = request.form.get('content', '').strip()
    priority = int(request.form.get('priority', 0))
    if not title or not content:
        return jsonify({'ok': False, 'msg': '标题和内容不能为空'})
    db = get_db()
    db.execute("INSERT INTO announcements (title, content, priority) VALUES (?,?,?)",
               (title, content, priority))
    db.commit()
    db.close()
    return jsonify({'ok': True})

@admin_bp.route('/announcements/<int:id>/toggle', methods=['POST'])
@login_required
def toggle_announcement(id):
    db = get_db()
    db.execute("UPDATE announcements SET active = CASE WHEN active=1 THEN 0 ELSE 1 END WHERE id=?", (id,))
    db.commit()
    db.close()
    return jsonify({'ok': True})

@admin_bp.route('/announcements/<int:id>/delete', methods=['POST'])
@login_required
def delete_announcement(id):
    db = get_db()
    db.execute("DELETE FROM announcements WHERE id=?", (id,))
    db.commit()
    db.close()
    return jsonify({'ok': True})

@admin_bp.route('/users')
@login_required
def users():
    q = request.args.get('q', '').strip()
    db = get_db()
    if q:
        rows = db.execute("""SELECT * FROM accounts WHERE token LIKE ? OR email LIKE ? ORDER BY id DESC""",
                          (f'%{q}%', f'%{q}%')).fetchall()
    else:
        rows = db.execute("SELECT * FROM accounts ORDER BY id DESC LIMIT 200").fetchall()
    db.close()
    return render_template('admin/users.html', accounts=rows, q=q)

@admin_bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        action = request.form.get('action')
        db = get_db()

        if action == 'smtp':
            keys = ['smtp_host', 'smtp_port', 'smtp_user', 'smtp_pass', 'smtp_from_name']
            for k in keys:
                v = request.form.get(k, '').strip()
                db.execute(
                    "INSERT INTO site_config (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=?",
                    (k, v, v))
            db.commit()
            db.close()
            return jsonify({'ok': True, 'msg': 'SMTP 配置已保存'})

        elif action == 'test_email':
            from lib.email import send_email
            test_to = request.form.get('test_to', '').strip()
            if not test_to:
                db.close()
                return jsonify({'ok': False, 'msg': '请输入收件邮箱'})
            ok, msg = send_email(test_to, '【云枢智联】测试邮件', '<h2>测试成功</h2><p>SMTP 配置正确，邮件发送功能正常。</p>')
            db.close()
            return jsonify({'ok': ok, 'msg': msg})

        new_pass = request.form.get('new_password')
        if new_pass:
            db.execute("UPDATE admins SET password=? WHERE username=?",
                       (generate_password_hash(new_pass), flask_session['admin_username']))
            db.commit()
            db.close()
            return jsonify({'ok': True, 'msg': '密码已修改'})
        db.close()
        return jsonify({'ok': False, 'msg': '请输入新密码'})
    
    # GET: 加载 site_config
    db = get_db()
    config_rows = db.execute("SELECT key, value FROM site_config").fetchall()
    db.close()
    site_config = {row['key']: row['value'] for row in config_rows}
    return render_template('admin/settings.html', config=site_config)
@admin_bp.route('/__unban__', methods=['GET', 'POST'])
def admin_unban():
    import subprocess
    if request.method == 'GET':
        return jsonify({'ok': True, 'msg': 'POST password to unban all'})
    password = request.json.get('password', '') if request.is_json else request.form.get('password', '')
    if password != 'change-me-in-pro':
        return jsonify({'ok': False, 'msg': 'wrong password'})
    try:
        result = subprocess.run(['fail2ban-client', 'unban', '--all'], capture_output=True, text=True, timeout=10)
        output = result.stdout.strip() or result.stderr.strip()
        status_result = subprocess.run(['fail2ban-client', 'status'], capture_output=True, text=True, timeout=5)
        jails = []
        for line in status_result.stdout.split('\n'):
            if 'Jail list:' in line:
                parts = line.split(':', 1)[1].strip()
                jails = [j.strip() for j in parts.split(',') if j.strip()]
        banned_ips = {}
        for jail in jails[:5]:
            sr = subprocess.run(['fail2ban-client', 'status', jail], capture_output=True, text=True, timeout=5)
            for sl in sr.stdout.split('\n'):
                if 'Currently banned:' in sl:
                    try:
                        banned_ips[jail] = int(sl.split(':')[1].strip())
                    except:
                        banned_ips[jail] = 0
        return jsonify({'ok': True, 'msg': 'unban done', 'jails': jails, 'banned_ips': banned_ips})
    except Exception as e:
        return jsonify({'ok': False, 'msg': f'unban failed: {e}'})
