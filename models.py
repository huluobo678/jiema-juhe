import sqlite3
import os
from datetime import datetime, timedelta
from config import DATABASE

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
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        );

        -- 项目（每个项目绑定一个渠道和一个价格）
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,                   -- 项目名称 eg. 淘宝注册
            channel_id INTEGER REFERENCES channels(id),
            sid INTEGER NOT NULL,                 -- 豪猪的项目ID
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
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            received_at TEXT
        );

        -- 管理员
        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL
        );
    ''')
    conn.commit()

    # 插入默认管理员
    cur = conn.execute("SELECT COUNT(*) FROM admins")
    if cur.fetchone()[0] == 0:
        from werkzeug.security import generate_password_hash
        from config import ADMIN_USERNAME, ADMIN_PASSWORD
        conn.execute("INSERT INTO admins (username, password) VALUES (?, ?)",
                     (ADMIN_USERNAME, generate_password_hash(ADMIN_PASSWORD)))
        conn.commit()
    conn.close()
