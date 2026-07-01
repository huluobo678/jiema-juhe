"""前台用户路由"""
import uuid, random, time
from flask import Blueprint, render_template, request, jsonify, abort
from werkzeug.security import generate_password_hash, check_password_hash
from models import get_db, calculate_final_price
from config import SITE_URL
from lib.scheduler import scheduler as smart_scheduler
from channels import get_registry as get_channel_registry
import re
from lib.phone_format import format_phone
from lib.time_utils import beijing_now, beijing_now_str, beijing_after

user_bp = Blueprint('user', __name__)

def project_service(project):
    country = project['country'] if 'country' in project.keys() else ''
    location = project['location'] if 'location' in project.keys() else ''
    price_limit = project['upstream_price_limit_usd'] if 'upstream_price_limit_usd' in project.keys() else 0
    if country or location or price_limit:
        return {'sid': project['sid'], 'country': country, 'location': location, 'max_price': price_limit}
    return project['sid']

def row_value(row, key, default=''):
    if row and key in row.keys():
        return row[key]
    return default

def current_account(db):
    token = request.cookies.get('account_token')
    if not token:
        return None
    return db.execute("SELECT * FROM accounts WHERE token=?", (token,)).fetchone()

def session_channel_meta(db, session_row):
    channel = db.execute("SELECT name, channel_type FROM channels WHERE id=?", (session_row['channel_id'],)).fetchone()
    channel_name = row_value(channel, 'name')
    channel_type = row_value(channel, 'channel_type', 'haozhuma')
    return channel_name, channel_type

def log_transaction(db, account_token, tx_type, amount, balance_after, description='', project_id=None, card_id=None, session_id=None):
    db.execute("""INSERT INTO transactions (account_token, type, amount, balance_after, description, project_id, card_id, session_id, created_at)
                  VALUES (?,?,?,?,?,?,?,?,?)""",
               (account_token, tx_type, amount, balance_after, description, project_id, card_id, session_id, beijing_now_str()))

def validate_login_password(password):
    if not password or len(password) < 6:
        return False, '密码至少需要 6 位'
    if len(password) > 72:
        return False, '密码不能超过 72 位'
    return True, ''

@user_bp.route('/')
def index():
    """首页 - 项目选择"""
    # 跟踪邀请链接
    ref = request.args.get('ref', '').strip()
    if ref:
        from flask import redirect
        resp = redirect('/', 302)
        resp.set_cookie('invited_by', ref, max_age=30*24*3600)
        return resp
    
    db = get_db()
    acc = current_account(db)
    is_vip = bool(row_value(acc, 'is_vip', 0))
    projects = db.execute("""
        SELECT p.id, p.name, p.price, p.vip_price, p.base_price, p.base_price_type, c.markup_percent, c.vip_markup_percent, c.name as channel_name
        FROM projects p JOIN channels c ON p.channel_id=c.id
        WHERE c.enabled=1
    """).fetchall()
    projects_clean = []
    for p in projects:
        normal_price = calculate_final_price(p['price'], p['base_price'], p['markup_percent'], p['base_price_type'])
        final_price = calculate_final_price(p['price'], p['base_price'], p['markup_percent'], p['base_price_type'], is_vip=is_vip, vip_price=row_value(p, 'vip_price', 0), vip_markup_percent=row_value(p, 'vip_markup_percent', p['markup_percent']))
        projects_clean.append({'id': p['id'], 'name': p['name'], 'price': final_price, 'normal_price': normal_price, 'is_vip_price': is_vip and final_price < normal_price})
    db.close()
    return render_template('user/index.html', projects=projects_clean, is_vip=is_vip)

@user_bp.route('/redeem', methods=['POST'])
def redeem():
    """兑换卡密"""
    code = request.form.get('code', '').strip()
    if not code:
        return jsonify({'ok': False, 'msg': '请输入卡密'})

    db = get_db()
    card = db.execute("SELECT * FROM cards WHERE code=? AND used=0", (code,)).fetchone()
    if not card:
        db.close()
        return jsonify({'ok': False, 'msg': '卡密无效或已使用'})

    cur = db.execute("UPDATE cards SET used=1, used_at=? WHERE id=? AND used=0", (beijing_now_str(), card['id']))
    if cur.rowcount != 1:
        db.rollback()
        db.close()
        return jsonify({'ok': False, 'msg': '卡密无效或已使用'})

    account_token = request.cookies.get('account_token')
    
    # 检查邀请关系：从cookie获取邀请人
    invited_by = request.cookies.get('invited_by', '').strip()
    final_referred_by = None
    if invited_by:
        referrer = db.execute("SELECT * FROM accounts WHERE token=? AND email_verified=1", (invited_by,)).fetchone()
        if referrer and row_value(referrer, 'email_verified'):
            final_referred_by = invited_by

    if account_token:
        acc = db.execute("SELECT * FROM accounts WHERE token=?", (account_token,)).fetchone()
        if acc:
            db.execute("UPDATE accounts SET balance=balance+? WHERE token=?", (card['credit'], account_token))
            updated = db.execute("SELECT balance FROM accounts WHERE token=?", (account_token,)).fetchone()
            log_transaction(db, account_token, 'recharge', float(card['credit']), updated['balance'], f'卡密充值 {code}', card_id=card['id'])
        else:
            account_token = uuid.uuid4().hex
            db.execute("INSERT INTO accounts (token, balance, referred_by) VALUES (?,?,?)",
                       (account_token, card['credit'], final_referred_by))
            log_transaction(db, account_token, 'recharge', float(card['credit']), float(card['credit']), f'卡密充值 {code}', card_id=card['id'])
    else:
        account_token = uuid.uuid4().hex
        db.execute("INSERT INTO accounts (token, balance, referred_by) VALUES (?,?,?)",
                   (account_token, card['credit'], final_referred_by))
        log_transaction(db, account_token, 'recharge', float(card['credit']), float(card['credit']), f'卡密充值 {code}', card_id=card['id'])

    db.commit()
    db.close()

    resp = jsonify({'ok': True, 'msg': f'充值成功！余额 +{card["credit"]}元', 'account_token': account_token})
    resp.set_cookie('account_token', account_token, max_age=30*24*3600)
    return resp

@user_bp.route('/balance')
def balance():
    account_token = request.cookies.get('account_token')
    if not account_token:
        return jsonify({'ok': False, 'balance': 0})
    db = get_db()
    acc = db.execute("SELECT balance, is_vip FROM accounts WHERE token=?", (account_token,)).fetchone()
    db.close()
    balance_value = float(acc['balance'] if acc else 0)
    return jsonify({'ok': True, 'balance': balance_value, 'balance_text': f'{balance_value:.2f}', 'is_vip': bool(row_value(acc, 'is_vip', 0))})

@user_bp.route('/announcements')
@user_bp.route('/user/announcements')
def announcements():
    db = get_db()
    rows = db.execute("SELECT * FROM announcements WHERE active=1 ORDER BY priority DESC, id DESC").fetchall()
    db.close()
    if request.args.get('json') == '1':
        return jsonify({'ok': True, 'list': [dict(r) for r in rows]})
    return render_template('user/announcements.html', announcements=rows)

@user_bp.route('/projects')
def project_list():
    db = get_db()
    acc = current_account(db)
    is_vip = bool(row_value(acc, 'is_vip', 0))
    rows = db.execute("""
        SELECT p.id, p.name, p.price, p.vip_price, p.base_price, p.base_price_type, p.category, p.country, p.location, p.icon, p.color, c.markup_percent, c.vip_markup_percent, c.name as channel_name
        FROM projects p JOIN channels c ON p.channel_id=c.id
        WHERE c.enabled=1
    """).fetchall()
    projects = []
    for p in rows:
        normal_price = calculate_final_price(p['price'], p['base_price'], p['markup_percent'], p['base_price_type'])
        final_price = calculate_final_price(p['price'], p['base_price'], p['markup_percent'], p['base_price_type'], is_vip=is_vip, vip_price=row_value(p, 'vip_price', 0), vip_markup_percent=row_value(p, 'vip_markup_percent', p['markup_percent']))
        projects.append({'id': p['id'], 'name': p['name'], 'price': final_price, 'normal_price': normal_price, 'is_vip_price': is_vip and final_price < normal_price, 'category': p['category'], 'country': p['country'], 'location': p['location'], 'channel_name': p['channel_name'], 'base_price_type': p['base_price_type'], 'icon': p['icon'], 'color': p['color']})
    db.close()
    return render_template('user/projects.html', projects=projects, is_vip=is_vip)

@user_bp.route('/sms/<view_token>')
def sms_view(view_token):
    db = get_db()
    session = db.execute("""
        SELECT s.*, p.name as project_name, p.price
        FROM sms_sessions s
        JOIN projects p ON s.project_id=p.id
        WHERE s.view_token=?
    """, (view_token,)).fetchone()
    db.close()
    if not session:
        abort(404)
    return render_template('user/sms_view.html', session=session)

# ========== 渠道状态监控 ==========

@user_bp.route('/channels/status')
def channel_status():
    channels = get_channel_registry().get_all()
    from lib.health import health_checker
    status = health_checker.status() if health_checker else []
    return jsonify({'ok': True, 'channels': status})

# ========== 统计数据 API ==========

@user_bp.route('/today-count')
def today_count():
    """今日成功收码次数"""
    token = request.cookies.get('account_token')
    db = get_db()
    r = db.execute("""SELECT COUNT(*) as cnt FROM sms_sessions
                     WHERE account_token=? AND status='received'
                     AND date(received_at)=?""", (token, beijing_now().strftime('%Y-%m-%d'))).fetchone()
    db.close()
    return jsonify({'ok': True, 'count': r[0] if r and r[0] else 0})


@user_bp.route('/recent-sms')
def recent_sms():
    """最近收码记录"""
    token = request.cookies.get('account_token')
    if not token:
        return jsonify({'ok': True, 'list': []})
    db = get_db()
    rows = db.execute("""SELECT s.phone, s.code, s.received_at, s.status, p.name as project
                        FROM sms_sessions s
                        JOIN projects p ON s.project_id=p.id
                        WHERE s.account_token=?
                        ORDER BY s.id DESC LIMIT 10""", (token,)).fetchall()
    db.close()
    items = []
    for r in rows:
        items.append({
            'phone': r['phone'],
            'code': r['code'] if r['status'] == 'received' else '',
            'time': r['received_at'] if r['received_at'] else '',
            'project': r['project'],
            'project_name': r['project'],
            'status': r['status'],
        })
    return jsonify({'ok': True, 'list': items})


# ========== 核心业务：获取号码 ==========

@user_bp.route('/start-order', methods=['POST'])
def start_order():
    """使用智能调度器选渠道并获取号码"""
    project_id = request.json.get('project_id')
    account_token = request.cookies.get('account_token')

    if not account_token:
        return jsonify({'ok': False, 'msg': '请先兑换卡密'})

    db = get_db()
    acc = db.execute("SELECT * FROM accounts WHERE token=?", (account_token,)).fetchone()
    project = db.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()

    if not acc or not project:
        db.close()
        return jsonify({'ok': False, 'msg': '项目不存在，请联系管理员'})
    if not row_value(project, 'sid'):
        db.close()
        return jsonify({'ok': False, 'msg': '项目未配置上游服务代码，请联系管理员'})

    base_price = project['base_price'] if 'base_price' in project.keys() else 0
    ch_row = db.execute("SELECT * FROM channels WHERE id=?", (project['channel_id'],)).fetchone()
    markup = ch_row['markup_percent'] if ch_row and 'markup_percent' in ch_row.keys() else 0
    vip_markup = row_value(ch_row, 'vip_markup_percent', markup)
    price_type = project['base_price_type'] if 'base_price_type' in project.keys() else 'auto'
    is_vip = bool(row_value(acc, 'is_vip', 0))
    total_price = calculate_final_price(project['price'], base_price, markup, price_type, is_vip=is_vip, vip_price=row_value(project, 'vip_price', 0), vip_markup_percent=vip_markup)

    if float(acc['balance']) < total_price:
        db.close()
        return jsonify({'ok': False, 'msg': f'余额不足，需要{total_price}元，当前{acc["balance"]}元'})

    # ====== 智能调度器选渠道 ======
    ch = smart_scheduler.pick_channel(project, is_vip=is_vip)
    if ch is None:
        db.close()
        return jsonify({'ok': False, 'msg': '所有渠道繁忙或不可用，请稍后再试'})

    # 获取号码
    if not ch.acquire():
        db.close()
        return jsonify({'ok': False, 'msg': '渠道繁忙，请稍后再试'})

    try:
        phone_data = ch.get_phone(project_service(project))
    except Exception as e:
        ch.release()
        db.close()
        return jsonify({'ok': False, 'msg': f'获取号码失败: {e}'})

    code_val = phone_data.get('code')
    if code_val != 0 and code_val != '0':
        ch.release()
        msg = phone_data.get('msg', '获取号码失败')
        if '余额' in msg or '余额不足' in msg:
            msg = '请充值'
        db.close()
        return jsonify({'ok': False, 'msg': msg})

    channel_id = ch.channel_id
    phone = phone_data['phone']
    activation_id = phone_data.get('activation_id', '')
    view_token = uuid.uuid4().hex

    smart_scheduler.set_sticky(view_token, channel_id)

    expire_at = beijing_after(200)
    db.execute("""INSERT INTO sms_sessions (account_token, project_id, channel_id, phone, activation_id, view_token, expire_at, status, cost)
                  VALUES (?,?,?,?,?,?,?, 'waiting', ?)""",
              (account_token, project_id, channel_id, phone, activation_id, view_token, expire_at, total_price))
    db.commit()
    db.close()
    ch.release()

    return jsonify({'ok': True, 'view_url': f'{SITE_URL}/sms/{view_token}', 'phone': phone, 'formatted_phone': format_phone(phone, ch.name), 'view_token': view_token})


@user_bp.route('/start-order-by-number', methods=['POST'])
def start_order_by_number():
    """指定号码取号"""
    data = request.json or {}
    project_id = data.get('project_id')
    phone_number = data.get('phone', '').strip()
    account_token = request.cookies.get('account_token')

    if not account_token:
        return jsonify({'ok': False, 'msg': '请先兑换卡密'})
    if not phone_number:
        return jsonify({'ok': False, 'msg': '请输入号码'})

    db = get_db()
    acc = db.execute("SELECT * FROM accounts WHERE token=?", (account_token,)).fetchone()
    project = db.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()

    if not acc or not project:
        db.close()
        return jsonify({'ok': False, 'msg': '项目不存在，请联系管理员'})
    if not row_value(project, 'sid'):
        db.close()
        return jsonify({'ok': False, 'msg': '项目未配置上游服务代码，请联系管理员'})

    base_price = project['base_price'] if 'base_price' in project.keys() else 0
    ch_row = db.execute("SELECT * FROM channels WHERE id=?", (project['channel_id'],)).fetchone()
    markup = ch_row['markup_percent'] if ch_row and 'markup_percent' in ch_row.keys() else 0
    vip_markup = row_value(ch_row, 'vip_markup_percent', markup)
    price_type = project['base_price_type'] if 'base_price_type' in project.keys() else 'auto'
    is_vip = bool(row_value(acc, 'is_vip', 0))
    total_price = calculate_final_price(project['price'], base_price, markup, price_type, is_vip=is_vip, vip_price=row_value(project, 'vip_price', 0), vip_markup_percent=vip_markup)

    if float(acc['balance']) < total_price:
        db.close()
        return jsonify({'ok': False, 'msg': f'余额不足，需要{total_price}元，当前{acc["balance"]}元'})

    # ====== 锁定到项目绑定的渠道 ======
    ch = get_channel_registry().get(project['channel_id'])
    if ch is None:
        from channels.factory import create_channel_adapter
        ch_row2 = db.execute("SELECT * FROM channels WHERE id=?", (project['channel_id'],)).fetchone()
        if ch_row2:
            ch = create_channel_adapter(ch_row2)
            get_channel_registry().register(ch)
    if ch is None:
        db.close()
        return jsonify({'ok': False, 'msg': '渠道不可用'})

    if not ch.acquire():
        db.close()
        return jsonify({'ok': False, 'msg': '渠道繁忙，请稍后再试'})

    try:
        phone_data = ch.get_phone_by_number(project_service(project), phone_number)
    except Exception as e:
        ch.release()
        db.close()
        return jsonify({'ok': False, 'msg': f'指定号码取号失败: {e}'})

    code_val = phone_data.get('code')
    if code_val != 0 and code_val != '0':
        ch.release()
        msg = phone_data.get('msg', '指定号码不可用')
        if '余额' in msg or '余额不足' in msg:
            msg = '请充值'
        db.close()
        return jsonify({'ok': False, 'msg': msg})

    channel_id = ch.channel_id
    phone = phone_data['phone']
    activation_id = phone_data.get('activation_id', '')
    view_token = uuid.uuid4().hex

    smart_scheduler.set_sticky(view_token, channel_id)

    expire_at = beijing_after(200)
    db.execute("""INSERT INTO sms_sessions (account_token, project_id, channel_id, phone, activation_id, view_token, expire_at, status, cost)
                  VALUES (?,?,?,?,?,?,?, 'waiting', ?)""",
              (account_token, project_id, channel_id, phone, activation_id, view_token, expire_at, total_price))
    db.commit()
    db.close()
    ch.release()

    return jsonify({'ok': True, 'view_url': f'{SITE_URL}/sms/{view_token}', 'phone': phone, 'formatted_phone': format_phone(phone, ch.name), 'view_token': view_token})

# ========== 轮询短信 ==========

@user_bp.route('/api/sms/<view_token>')
def api_sms(view_token):
    """轮询验证码"""
    account_token = request.cookies.get('account_token')
    db = get_db()
    s = db.execute("SELECT * FROM sms_sessions WHERE view_token=?", (view_token,)).fetchone()
    if not s:
        db.close()
        return jsonify({'ok': False, 'msg': '会话不存在'})

    if s['account_token'] != account_token:
        db.close()
        return jsonify({'ok': False, 'msg': '无权访问此会话'})

    if s['status'] == 'received':
        channel_name, channel_type = session_channel_meta(db, s)
        db.close()
        return jsonify({'ok': True, 'code': s['code'], 'sms': s['sms_content'], 'phone': s['phone'], 'formatted_phone': format_phone(s['phone'], channel_name), 'channel_type': channel_type})

    # 从注册中心获取渠道实例（避免重复实例化）
    ch = get_channel_registry().get(s['channel_id'])
    if ch is None:
        # 回退：通过工厂创建
        channel = db.execute("SELECT * FROM channels WHERE id=?", (s['channel_id'],)).fetchone()
        project = db.execute("SELECT * FROM projects WHERE id=?", (s['project_id'],)).fetchone()
        db.close()
        if not channel or not project:
            return jsonify({'ok': False, 'msg': '渠道信息丢失'})
        from channels.factory import create_channel_adapter
        ch = create_channel_adapter(channel)
    else:
        project = db.execute("SELECT * FROM projects WHERE id=?", (s['project_id'],)).fetchone()
        channel = db.execute("SELECT * FROM channels WHERE id=?", (s['channel_id'],)).fetchone()
        db.close()
        if not project:
            return jsonify({'ok': False, 'msg': '项目不存在或已删除'})

    # 传递 activation_id（HeroSMS 等渠道需要）
    aid = row_value(s, 'activation_id') or ''
    data = ch.get_message(project_service(project), s['phone'], activation_id=aid)
    ch.release()  # 释放并发槽位

    if data.get('code') == 0 or data.get('code') == '0':
        code = data.get('yzm', '')
        sms_content = data.get('sms', '')
        
        # 如果 yzm 是 0/空，尝试从 sms 文本提取验证码
        if not code and sms_content:
            import re
            m = re.search(r'(\d{4,8})', sms_content)
            if m:
                code = m.group(1)
        
        if not code:
            # 还没真正收到验证码（豪猪 code=0 只表示请求成功）
            db2 = get_db()
            db2.close()
            return jsonify({'ok': False, 'msg': '等待验证码中...', 'waiting': True})
        db2 = get_db()
        # 收码时扣款（使用下单时锁定的价格）
        final_price = s['cost'] or 0
        cur = db2.execute("UPDATE accounts SET balance=balance-? WHERE token=? AND balance>=?", (final_price, s['account_token'], final_price))
        if cur.rowcount != 1:
            db2.rollback()
            db2.close()
            return jsonify({'ok': False, 'msg': '余额不足，请充值'})
        cur = db2.execute("""UPDATE sms_sessions SET status='received', code=?, sms_content=?, received_at=?
                          WHERE id=? AND status!='received'""", (code, sms_content, beijing_now_str(), s['id']))
        if cur.rowcount != 1:
            db2.rollback()
            db2.close()
            return jsonify({'ok': True, 'code': code, 'sms': sms_content, 'phone': s['phone'], 'formatted_phone': format_phone(s['phone'], row_value(channel, 'name')), 'channel_type': row_value(channel, 'channel_type', 'haozhuma')})
        updated_balance = db2.execute("SELECT balance FROM accounts WHERE token=?", (s['account_token'],)).fetchone()
        log_transaction(db2, s['account_token'], 'consume', -float(final_price), updated_balance['balance'] if updated_balance else 0, f'接码消费 {row_value(project, "name", "项目")}', project_id=s['project_id'], session_id=s['id'])
        db2.commit()
        db2.close()
        return jsonify({'ok': True, 'code': code, 'sms': sms_content, 'phone': s['phone'], 'formatted_phone': format_phone(s['phone'], row_value(channel, 'name')), 'channel_type': row_value(channel, 'channel_type', 'haozhuma')})

    err_msg = data.get('msg') or ''
    if '余额' in err_msg or '余额不足' in err_msg:
        return jsonify({'ok': False, 'msg': '请充值'})

    return jsonify({'ok': False, 'msg': '等待验证码中...', 'waiting': True})

# ========== 释放号码 ==========

@user_bp.route('/release-phone', methods=['POST'])
def release_phone():
    """释放/拉黑号码"""
    view_token = request.json.get('view_token')
    if not view_token:
        return jsonify({'ok': False, 'msg': '项目不存在，请联系管理员'})
    account_token = request.cookies.get('account_token')

    db = get_db()
    s = db.execute("SELECT * FROM sms_sessions WHERE view_token=?", (view_token,)).fetchone()
    if not s:
        db.close()
        return jsonify({'ok': False, 'msg': '会话不存在'})

    if s['account_token'] != account_token:
        db.close()
        return jsonify({'ok': False, 'msg': '无权访问此会话'})

    project = db.execute("SELECT * FROM projects WHERE id=?", (s['project_id'],)).fetchone()
    db.close()

    if not project:
        return jsonify({'ok': False, 'msg': '项目不存在或已删除'})

    # 从注册中心获取渠道
    ch = get_channel_registry().get(s['channel_id'])
    if ch is None:
        db3 = get_db()
        channel = db3.execute("SELECT * FROM channels WHERE id=?", (s['channel_id'],)).fetchone()
        db3.close()
        if channel:
            from channels.factory import create_channel_adapter
            ch = create_channel_adapter(channel)

    if s['status'] == 'waiting' and ch:
        try:
            aid = row_value(s, 'activation_id') or ''
            ch.add_blacklist(project_service(project), s['phone'], activation_id=aid)
        except:
            pass

    db2 = get_db()
    db2.execute("UPDATE sms_sessions SET status='released' WHERE id=?", (s['id'],))
    db2.commit()
    db2.close()

    # 释放粘性会话
    smart_scheduler.release_sticky(view_token)

    return jsonify({'ok': True, 'msg': '号码已释放'})

# ========== 邮箱注册/绑定 ==========

@user_bp.route('/send-code', methods=['POST'])
def send_code():
    """发送邮箱验证码（仅限 @qq.com）"""
    email = request.json.get('email', '').strip().lower()
    if '@' not in email:
        return jsonify({'ok': False, 'msg': '邮箱格式不正确'})
    if not email.endswith('@qq.com'):
        return jsonify({'ok': False, 'msg': '仅支持 QQ 邮箱（@qq.com）'})

    code = ''.join(random.choices('0123456789', k=6))
    expire_at = __import__('time').time() + 600

    from lib.email import send_verify_code
    ok, msg = send_verify_code(email, code)
    if not ok:
        return jsonify({'ok': False, 'msg': msg})

    db = get_db()
    db.execute("DELETE FROM verify_codes WHERE email=?", (email,))
    db.execute("INSERT INTO verify_codes (email, code, expire_at) VALUES (?,?,?)", (email, code, expire_at))
    db.commit()
    db.close()
    return jsonify({'ok': True, 'msg': '验证码已发送'})

@user_bp.route('/register', methods=['GET', 'POST'])
def register():
    """注册/绑定QQ邮箱页面"""
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        if not email.endswith('@qq.com'):
            return jsonify({'ok': False, 'msg': '仅支持 QQ 邮箱（@qq.com）'})
        code = request.form.get('code', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        ok, msg = validate_login_password(password)
        if not ok:
            return jsonify({'ok': False, 'msg': msg})
        if confirm_password and password != confirm_password:
            return jsonify({'ok': False, 'msg': '两次输入的密码不一致'})
        account_token = request.cookies.get('account_token')

        db = get_db()
        now = __import__('time').time()
        row = db.execute(
            "SELECT id, code, expire_at, used FROM verify_codes WHERE email=? ORDER BY id DESC LIMIT 1",
            (email,)
        ).fetchone()
        if not row:
            db.close()
            return jsonify({'ok': False, 'msg': '请先获取验证码'})
        if row['used']:
            db.close()
            return jsonify({'ok': False, 'msg': '验证码已使用过'})
        if now > row['expire_at']:
            db.close()
            return jsonify({'ok': False, 'msg': '验证码已过期'})
        if row['code'] != code:
            db.close()
            return jsonify({'ok': False, 'msg': '验证码错误'})

        # 标记验证码已使用
        db.execute("UPDATE verify_codes SET used=1 WHERE id=?", (row['id'],))
        db.execute("DELETE FROM verify_codes WHERE email=? AND id!=?", (email, row['id']))

        password_hash = generate_password_hash(password)
        existing = db.execute("SELECT id, token FROM accounts WHERE email=? AND email_verified=1", (email,)).fetchone()
        if existing and existing['token'] != account_token:
            db.close()
            return jsonify({'ok': False, 'msg': '该邮箱已绑定，请直接登录'})

        if account_token:
            # 已有账户 → 绑定邮箱
            acc = db.execute("SELECT id FROM accounts WHERE token=?", (account_token,)).fetchone()
            if not acc:
                db.execute("INSERT INTO accounts (token, email, email_verified, password_hash) VALUES (?,?,1,?)", (account_token, email, password_hash))
            else:
                db.execute("UPDATE accounts SET email=?, email_verified=1, password_hash=? WHERE token=?", (email, password_hash, account_token))
        else:
            # 没有 account_token → 创建新账户
            account_token = uuid.uuid4().hex
            db.execute("INSERT INTO accounts (token, email, email_verified, password_hash) VALUES (?,?,1,?)", (account_token, email, password_hash))

        db.commit()
        db.close()

        resp = jsonify({'ok': True, 'msg': '邮箱绑定成功', 'account_token': account_token})
        resp.set_cookie('account_token', account_token, max_age=30*24*3600)
        return resp

    return render_template('user/register.html')

@user_bp.route('/login', methods=['GET', 'POST'])
@user_bp.route('/user/login', methods=['GET', 'POST'])
def user_login():
    """用户邮箱密码登录"""
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        if not email.endswith('@qq.com'):
            return jsonify({'ok': False, 'msg': '请输入 QQ 邮箱'})
        db = get_db()
        acc = db.execute("SELECT token, password_hash FROM accounts WHERE email=? AND email_verified=1", (email,)).fetchone()
        db.close()
        if not acc:
            return jsonify({'ok': False, 'msg': '该邮箱未绑定，请先绑定邮箱'})
        if not acc['password_hash']:
            return jsonify({'ok': False, 'msg': '该邮箱尚未设置登录密码，请重新绑定邮箱设置密码'})
        if not check_password_hash(acc['password_hash'], password):
            return jsonify({'ok': False, 'msg': '邮箱或密码错误'})
        resp = jsonify({'ok': True, 'msg': '登录成功', 'account_token': acc['token']})
        resp.set_cookie('account_token', acc['token'], max_age=30*24*3600)
        return resp
    return render_template('user/login.html')

@user_bp.route('/user/cards')
def user_cards():
    """卡密充值页面"""
    return render_template('user/cards.html')

@user_bp.route('/user/account')
def user_account():
    """账户信息页面"""
    account_token = request.cookies.get('account_token')
    email = None
    referred_by = None
    invite_link = None
    has_password = False
    is_vip = False
    if account_token:
        db = get_db()
        acc = db.execute("SELECT email, referred_by, password_hash, is_vip FROM accounts WHERE token=?", (account_token,)).fetchone()
        if acc:
            email = acc['email']
            referred_by = acc['referred_by']
            has_password = bool(row_value(acc, 'password_hash'))
            is_vip = bool(row_value(acc, 'is_vip', 0))
            if email:
                invite_link = SITE_URL.rstrip('/') + '/?ref=' + account_token
        db.close()
    return render_template('user/account.html', email=email, referred_by=referred_by, invite_link=invite_link, has_password=has_password, is_vip=is_vip)

@user_bp.route('/logout')
def logout():
    """用户退出 - 清除cookie"""
    resp = __import__('flask').redirect('/')
    resp.set_cookie('account_token', '', expires=0)
    return resp

@user_bp.route('/history')
def user_history():
    """用户使用记录"""
    account_token = request.cookies.get('account_token')
    sessions = []
    if account_token:
        db = get_db()
        sessions = db.execute("""
            SELECT s.*, p.name as project_name
            FROM sms_sessions s
            JOIN projects p ON s.project_id=p.id
            WHERE s.account_token=?
            ORDER BY s.id DESC LIMIT 50
        """, (account_token,)).fetchall()
        db.close()
    return render_template('user/history.html', sessions=sessions)

@user_bp.route('/transactions')
@user_bp.route('/user/transactions')
def user_transactions():
    """账户充值和消费明细"""
    account_token = request.cookies.get('account_token')
    rows = []
    if account_token:
        db = get_db()
        rows = db.execute("""
            SELECT t.*, p.name as project_name, c.code as card_code
            FROM transactions t
            LEFT JOIN projects p ON t.project_id=p.id
            LEFT JOIN cards c ON t.card_id=c.id
            WHERE t.account_token=?
            ORDER BY t.id DESC LIMIT 200
        """, (account_token,)).fetchall()
        db.close()
    return render_template('user/transactions.html', transactions=rows)
