import sqlite3
import os
from datetime import datetime, timedelta
from config import DATABASE

def _migrate_upgrade(conn):
    """迁移旧表：添加新列"""
    try:
        conn.execute("ALTER TABLE channels ADD COLUMN channel_type TEXT DEFAULT 'haozhuma'")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE channels ADD COLUMN markup_percent REAL DEFAULT 0")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE channels ADD COLUMN concurrent_limit INTEGER DEFAULT 5")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE accounts ADD COLUMN concurrent_limit INTEGER DEFAULT 5")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE accounts ADD COLUMN email TEXT")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE accounts ADD COLUMN email_verified INTEGER DEFAULT 0")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE accounts ADD COLUMN referred_by TEXT")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE accounts ADD COLUMN password_hash TEXT DEFAULT ''")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE sms_sessions ADD COLUMN expire_at TEXT")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE sms_sessions ADD COLUMN activation_id TEXT DEFAULT ''")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE projects ADD COLUMN base_price REAL DEFAULT 0")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE projects ADD COLUMN country TEXT DEFAULT ''")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE projects ADD COLUMN location TEXT DEFAULT ''")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE projects ADD COLUMN upstream_price_limit_usd REAL DEFAULT 0")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE projects ADD COLUMN base_price_type TEXT DEFAULT 'auto'")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE projects ADD COLUMN category TEXT DEFAULT ''")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE projects ADD COLUMN icon TEXT DEFAULT ''")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE projects ADD COLUMN color TEXT DEFAULT '#f1f5f9'")
    except Exception:
        pass
    conn.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_token TEXT NOT NULL,
            type TEXT NOT NULL,
            amount REAL NOT NULL,
            balance_after REAL NOT NULL DEFAULT 0,
            description TEXT DEFAULT '',
            project_id INTEGER,
            card_id INTEGER,
            session_id INTEGER,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        )
    ''')
    conn.commit()

def calculate_final_price(project_price, project_base_price, channel_markup, price_type='auto'):
    """计算最终售价。fixed 使用项目固定价；auto 使用上游成本加渠道加价。"""
    if price_type == 'fixed' and project_price and float(project_price) > 0:
        return float(project_price)
    base = float(project_base_price or 1.0)
    return round(base * (1 + float(channel_markup or 0) / 100), 2)

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    conn = get_db()
    conn.executescript('''
        -- 接码渠道
        CREATE TABLE IF NOT EXISTS channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,          -- 渠道名称 eg. 豪猪
            api_url TEXT NOT NULL,
            api_user TEXT,
            api_pass TEXT,
            token TEXT,                          -- 缓存的token
            enabled INTEGER DEFAULT 1,
            markup_percent REAL DEFAULT 0,       -- 加价百分比
            concurrent_limit INTEGER DEFAULT 5, -- 并发上限
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        );

        -- 项目（每个项目绑定一个渠道和一个价格）
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,                   -- 项目名称 eg. 淘宝注册
            channel_id INTEGER REFERENCES channels(id),
            sid TEXT NOT NULL,                    -- 项目ID/服务代码（豪猪=数字ID，HeroSMS=tg/go等）
            country TEXT DEFAULT '',              -- 国家代码（HeroSMS 使用）
            location TEXT DEFAULT '',             -- 归属地（豪猪等渠道可用）
            upstream_price_limit_usd REAL DEFAULT 0, -- 最高上游价格（HeroSMS 使用，美元）
            base_price REAL DEFAULT 0,            -- 上游成本/自动加价基准
            base_price_type TEXT DEFAULT 'auto',  -- auto 自动加价 / fixed 固定售价
            category TEXT DEFAULT '',             -- 前台分类
            icon TEXT DEFAULT '',                 -- 前台图标
            color TEXT DEFAULT '#f1f5f9',         -- 前台颜色
            price REAL NOT NULL DEFAULT 1.0,       -- 每码价格(元)
            description TEXT,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        );

        -- 卡密
        CREATE TABLE IF NOT EXISTS cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL UNIQUE,            -- 卡密字符串
            credit REAL NOT NULL DEFAULT 0,        -- 充值金额(元)
            used INTEGER DEFAULT 0,               -- 0未使用 1已使用
            used_at TEXT,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        );

        -- 用户收码账户（按IP/设备聚合，简化版）
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token TEXT NOT NULL UNIQUE,            -- 用户身份token
            balance REAL NOT NULL DEFAULT 0,       -- 余额(元)
            concurrent_limit INTEGER DEFAULT 5,    -- 并发上限
            email TEXT,
            email_verified INTEGER DEFAULT 0,
            password_hash TEXT DEFAULT '',
            referred_by TEXT,                      -- 推荐人token
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        );

        -- 收码会话
        CREATE TABLE IF NOT EXISTS sms_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_token TEXT REFERENCES accounts(token),
            project_id INTEGER REFERENCES projects(id),
            channel_id INTEGER REFERENCES channels(id),
            phone TEXT,                           -- 分配的号码
            activation_id TEXT,                   -- 平台激活ID
            status TEXT DEFAULT 'waiting',        -- waiting / received / released / blacklisted
            cost REAL DEFAULT 0,                  -- 成本(元)
            code TEXT,                            -- 收到的验证码
            sms_content TEXT,                     -- 完整短信
            view_token TEXT NOT NULL UNIQUE,       -- 查看链接token
            expire_at TEXT,                        -- 过期时间
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            received_at TEXT
        );

        -- 验证码（跨worker共享）
        CREATE TABLE IF NOT EXISTS verify_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            code TEXT NOT NULL,
            expire_at REAL NOT NULL,
            used INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        );

        -- 账户流水
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_token TEXT NOT NULL,
            type TEXT NOT NULL,                 -- recharge / consume / refund / bonus
            amount REAL NOT NULL,               -- 充值为正，消费为负
            balance_after REAL NOT NULL DEFAULT 0,
            description TEXT DEFAULT '',
            project_id INTEGER,
            card_id INTEGER,
            session_id INTEGER,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        );

        -- 管理员
        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL
        );

        -- 站点配置
        CREATE TABLE IF NOT EXISTS site_config (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL DEFAULT ''
        );

        -- 公告
        CREATE TABLE IF NOT EXISTS announcements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            priority INTEGER DEFAULT 0,
            active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        );
    ''')
    conn.commit()

    # 尝试迁移旧表（加列）
    _migrate_upgrade(conn)

    # 插入默认管理员
    cur = conn.execute("SELECT COUNT(*) FROM admins")
    if cur.fetchone()[0] == 0:
        from werkzeug.security import generate_password_hash
        from config import ADMIN_USERNAME, ADMIN_PASSWORD
        conn.execute("INSERT INTO admins (username, password) VALUES (?, ?)",
                     (ADMIN_USERNAME, generate_password_hash(ADMIN_PASSWORD)))
        conn.commit()
    conn.close()
