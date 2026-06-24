"""前台用户路由"""
import uuid
from flask import Blueprint, render_template, request, jsonify, abort
from models import get_db
from config import SITE_URL

user_bp = Blueprint('user', __name__)

@user_bp.route('/')
def index():
    """首页 - 兑换+项目一体"""
    db = get_db()
    projects = db.execute("""
        SELECT p.id, p.name, p.price, c.name as channel_name
        FROM projects p JOIN channels c ON p.channel_id=c.id
        WHERE c.enabled=1
    """).fetchall()
    db.close()
    return render_template('user/index.html', projects=projects)

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

    db.execute("UPDATE cards SET used=1, used_at=datetime('now','localtime') WHERE id=?", (card['id'],))

    account_token = request.cookies.get('account_token')
    if account_token:
        acc = db.execute("SELECT * FROM accounts WHERE token=?", (account_token,)).fetchone()
        if acc:
            db.execute("UPDATE accounts SET balance=balance+? WHERE token=?", (card['credit'], account_token))
        else:
            account_token = uuid.uuid4().hex
            db.execute("INSERT INTO accounts (token, balance) VALUES (?,?)", (account_token, card['credit']))
    else:
        account_token = uuid.uuid4().hex
        db.execute("INSERT INTO accounts (token, balance) VALUES (?,?)", (account_token, card['credit']))

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
    acc = db.execute("SELECT balance FROM accounts WHERE token=?", (account_token,)).fetchone()
    db.close()
    return jsonify({'ok': True, 'balance': acc['balance'] if acc else 0})

@user_bp.route('/projects')
def project_list():
    db = get_db()
    projects = db.execute("""
        SELECT p.id, p.name, p.price, c.name as channel_name
        FROM projects p JOIN channels c ON p.channel_id=c.id
        WHERE c.enabled=1
    """).fetchall()
    db.close()
    return render_template('user/projects.html', projects=projects)

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

@user_bp.route('/api/sms/<view_token>')
def api_sms(view_token):
    db = get_db()
    s = db.execute("SELECT * FROM sms_sessions WHERE view_token=?", (view_token,)).fetchone()
    if not s:
        db.close()
        return jsonify({'ok': False, 'msg': '会话不存在'})

    if s['status'] == 'received':
        db.close()
        return jsonify({'ok': True, 'code': s['code'], 'sms': s['sms_content'], 'phone': s['phone']})

    channel = db.execute("SELECT * FROM channels WHERE id=?", (s['channel_id'],)).fetchone()
    project = db.execute("SELECT * FROM projects WHERE id=?", (s['project_id'],)).fetchone()
    db.close()

    from channels.haozhuma import HaoZhuMa
    hzm = HaoZhuMa(channel['api_url'], channel['api_user'], channel['api_pass'], channel['token'])
    data = hzm.get_message(project['sid'], s['phone'])

    if data.get('code') == 0 or data.get('code') == '0':
        code = data.get('yzm', '')
        sms_content = data.get('sms', '')
        db2 = get_db()
        db2.execute("UPDATE accounts SET balance=balance-? WHERE token=?", (project['price'], s['account_token']))
        db2.execute("""UPDATE sms_sessions SET status='received', code=?, sms_content=?, received_at=datetime('now','localtime')
                       WHERE id=?""", (code, sms_content, s['id']))
        db2.commit()
        db2.close()
        return jsonify({'ok': True, 'code': code, 'sms': sms_content, 'phone': s['phone']})

    # 上游报错 -> 显示没有账号
    err_msg = data.get('msg') or ''
    if '余额' in err_msg or '余额不足' in err_msg:
        return jsonify({'ok': False, 'msg': '没有账号'})

    return jsonify({'ok': False, 'msg': '等待验证码中...', 'waiting': True})

@user_bp.route('/start-order', methods=['POST'])
def start_order():
    project_id = request.json.get('project_id')
    account_token = request.cookies.get('account_token')

    if not account_token:
        return jsonify({'ok': False, 'msg': '请先兑换卡密'})

    db = get_db()
    acc = db.execute("SELECT * FROM accounts WHERE token=?", (account_token,)).fetchone()
    project = db.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()

    if not acc or not project:
        db.close()
        return jsonify({'ok': False, 'msg': '参数错误'})

    if float(acc['balance']) < project['price']:
        db.close()
        return jsonify({'ok': False, 'msg': f'余额不足，需要{project["price"]}元，当前{acc["balance"]}元'})

    channel = db.execute("SELECT * FROM channels WHERE id=?", (project['channel_id'],)).fetchone()

    from channels.haozhuma import HaoZhuMa
    hzm = HaoZhuMa(channel['api_url'], channel['api_user'], channel['api_pass'], channel['token'])
    phone_data = hzm.get_phone(project['sid'])

    code_val = phone_data.get('code')
    if code_val != 0 and code_val != '0':
        msg = phone_data.get('msg', '获取号码失败')
        # 上游余额不足或没号 -> 统一显示 没有账号
        if '余额' in msg or '余额不足' in msg or '超限' in msg or '没有更多' in msg:
            msg = '没有账号'
        db.close()
        return jsonify({'ok': False, 'msg': msg})

    phone = phone_data['phone']
    view_token = uuid.uuid4().hex

    db.execute("""INSERT INTO sms_sessions (account_token, project_id, channel_id, phone, view_token, status)
                  VALUES (?,?,?,?,?, 'waiting')""",
              (account_token, project_id, channel['id'], phone, view_token))
    db.commit()
    db.close()

    return jsonify({'ok': True, 'view_url': f'{SITE_URL}/sms/{view_token}', 'phone': phone, 'view_token': view_token})

@user_bp.route('/release-phone', methods=['POST'])
def release_phone():
    """释放/拉黑号码"""
    view_token = request.json.get('view_token')
    if not view_token:
        return jsonify({'ok': False, 'msg': '参数错误'})

    db = get_db()
    s = db.execute("SELECT * FROM sms_sessions WHERE view_token=?", (view_token,)).fetchone()
    if not s:
        db.close()
        return jsonify({'ok': False, 'msg': '会话不存在'})

    channel = db.execute("SELECT * FROM channels WHERE id=?", (s['channel_id'],)).fetchone()
    project = db.execute("SELECT * FROM projects WHERE id=?", (s['project_id'],)).fetchone()

    if s['status'] == 'waiting':
        from channels.haozhuma import HaoZhuMa
        hzm = HaoZhuMa(channel['api_url'], channel['api_user'], channel['api_pass'], channel['token'])
        hzm.add_blacklist(project['sid'], s['phone'])

    db.execute("UPDATE sms_sessions SET status='released' WHERE id=?", (s['id'],))
    db.commit()
    db.close()
    return jsonify({'ok': True, 'msg': '号码已释放'})