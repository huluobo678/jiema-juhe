# SPEC: 接码中转平台 Phase 1 + Phase 2

> 渠道聚合层 + 并发API层 · 一次性开发交付

---

## 一、整体架构

```
                  客户（浏览器/脚本）
                         │
                    HTTP 请求
                         │
                   gunicorn (4-8 worker)
                         │
              ┌──────────┴──────────┐
              │   Flask APP (无改动)  │
              │  routes / views / api │
              └──────────┬──────────┘
                         │
              ┌──────────┴──────────┐
              │   core/queue.py      │  ← 后台线程池
              │   core/scheduler.py  │  ← 轮询调度器
              └──────────┬──────────┘
                         │
              ┌──────────┴──────────┐
              │   channels/router.py │  ← 智能路由
              └──────────┬──────────┘
                         │
         ┌───────────────┼───────────────┐
         │               │               │
   channels/haozhuma  channels/fivesim  channels/xxx...
```

### 数据流（取号）

```
1. 客户请求取号
2. API层校验余额 → 通过
3. 调用 router.get_best_channel(service, country) → 选中渠道
4. 扣除余额 → 写入 session 记录（status=waiting）
5. 将任务提交到后台线程池
6. 立即返回号码给客户（不阻塞）
7. 后台线程：调用渠道取号 → 等待验证码 → 写入DB
8. 客户轮询查状态 → API 直接读DB → 立即返回
```

---

## 二、channels/ 渠道层

### 2.1 `channels/base.py` — 渠道驱动基类

所有渠道驱动必须继承此类。

```python
class ChannelDriver(ABC):
    """渠道驱动基类"""

    def __init__(self, config: dict):
        """
        config: 从 channels 表读取的配置 JSON
        包含: api_key, endpoint, 及其他渠道特定参数
        """
        self.config = config
        self._login()

    @abstractmethod
    def _login(self) -> bool:
        """登录/鉴权，初始化 session"""
        pass

    @abstractmethod
    def get_balance(self) -> float:
        """查询余额，返回人民币金额"""
        pass

    @abstractmethod
    def get_number(self, service_id: str, country: str = None) -> dict:
        """
        获取号码
        返回: {
            "session_id": str,   # 渠道侧的激活ID/订单ID
            "phone": str,        # 完整手机号
            "price": float,      # 本次消费金额（人民币）
        }
        失败: 抛出 ChannelError
        """
        pass

    @abstractmethod
    def get_sms(self, session_id: str, phone: str) -> dict:
        """
        查询验证码
        返回: {
            "status": str,       # "waiting" / "received" / "expired" / "blacklisted"
            "code": str | None,  # 验证码字符串
            "sms_text": str | None,  # 完整短信内容
        }
        """
        pass

    @abstractmethod
    def release(self, session_id: str, phone: str) -> bool:
        """
        释放号码（取消/完成），让渠道可以回收
        返回: True 成功 / False 失败
        """
        pass

    @abstractmethod
    def get_price(self, service_id: str, country: str = None) -> float:
        """
        查询指定服务在渠道的价格（人民币）
        返回: float 价格
        失败: 抛出 ChannelError（该渠道不支持此服务）
        """
        pass
```

### 2.2 `channels/haozhuma.py` — 豪猪渠道（重构版）

**继承 ChannelDriver，改造成统一接口。**

- 读取 `config.api_key`（豪猪的 token）
- 豪猪 API 端点: `https://api.haozhuma.com/sms/`（示例，实际按真实端点写）
- 错误处理：网络错误重试 3 次，HTTP 非 200 直接报错

### 2.3 `channels/fivesim.py` — 5sim 预留模板

**仅创建文件结构，方法体留 `raise NotImplementedError`。**

```python
class FiveSimDriver(ChannelDriver):
    def _login(self): raise NotImplementedError
    def get_balance(self): raise NotImplementedError
    def get_number(self, service_id, country=None): raise NotImplementedError
    def get_sms(self, session_id, phone): raise NotImplementedError
    def release(self, session_id, phone): raise NotImplementedError
    def get_price(self, service_id, country=None): raise NotImplementedError
```

### 2.4 `channels/router.py` — 智能路由

```python
class ChannelRouter:
    """
    路由调度器，负责:
    1. 按价格选择最优渠道
    2. 活渠道检查
    3. 渠道故障降级
    4. 并发上限控制
    """

    def __init__(self):
        self.drivers = {}  # channel_id -> ChannelDriver 实例
        self._locks = {}   # channel_id -> threading.Semaphore（并发控制）

    def load_drivers(self):
        """从数据库读取所有已启用的渠道配置，初始化驱动实例"""
        pass

    def get_best_channel(self, project_id: int, service_id: str, country: str = None) -> dict:
        """
        为项目选择最优渠道
        规则:
        1. 排除项目配置的"固定渠道"之外的其他渠道
        2. 按项目配置的渠道优先级排序（后台可拖拽排序）
        3. 如有多个渠道支持该服务，选价格最低且未达并发上限的
        4. 如价格相同，选成功率较高的
        5. 所有渠道均不可用 → 抛出 NoAvailableChannelError
        
        返回: {
            "channel_id": int,
            "driver": ChannelDriver,
            "price": float,
        }
        """
        pass

    def acquire_slot(self, channel_id: int) -> bool:
        """
        尝试获取渠道并发槽位
        返回 True 获取成功 / False 已达上限需等待
        """
        pass

    def release_slot(self, channel_id: int):
        """释放渠道并发槽位"""
        pass
```

### 2.5 错误定义

```python
class ChannelError(Exception):
    """渠道调用异常"""
    pass

class ChannelNoServiceError(ChannelError):
    """渠道不支持该服务"""
    pass

class ChannelNoNumberError(ChannelError):
    """渠道暂无可用号码"""
    pass

class NoAvailableChannelError(Exception):
    """无可用的渠道"""
    pass
```

---

## 三、数据库模型变更

### 3.1 新增 `channels` 表

```sql
CREATE TABLE channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,                    -- 渠道名称，如"豪猪"
    driver_class TEXT NOT NULL,            -- 驱动类名，如"HaozhumaDriver"
    config TEXT NOT NULL,                  -- JSON: api_key, endpoint 等
    enabled INTEGER DEFAULT 1,             -- 1启用 0禁用
    concurrency_limit INTEGER DEFAULT 5,   -- 最大并发请求数
    sort_order INTEGER DEFAULT 0,          -- 排序（小→大）
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT DEFAULT (datetime('now', 'localtime'))
);
```

### 3.2 新增 `channel_prices` 表（渠道×项目定价）

```sql
CREATE TABLE channel_prices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id INTEGER NOT NULL,           -- 关联 channels.id
    project_id INTEGER NOT NULL,           -- 关联 projects.id
    country TEXT DEFAULT 'cn',             -- 国家代码
    price REAL NOT NULL DEFAULT 0,         -- 该渠道该项目的单价（元）
    priority INTEGER DEFAULT 0,            -- 优先级（数字小优先）
    enabled INTEGER DEFAULT 1,
    UNIQUE(channel_id, project_id, country)
);
```

### 3.3 修改 `sessions` 表（增加字段）

```sql
-- 已有 sessions 表基础上增加:
ALTER TABLE sessions ADD COLUMN channel_id INTEGER REFERENCES channels(id);
ALTER TABLE sessions ADD COLUMN cost REAL DEFAULT 0;           -- 本次实际成本
ALTER TABLE sessions ADD COLUMN expire_at TEXT;                -- 超时自动释放时间
ALTER TABLE sessions ADD COLUMN project_id INTEGER REFERENCES projects(id);  -- 如果已有则跳过
```

### 3.4 修改 `projects` 表（增加价格字段）

```sql
-- 已有 projects 表基础上增加:
ALTER TABLE projects ADD COLUMN default_price REAL DEFAULT 0;  -- 默认单价
ALTER TABLE projects ADD COLUMN timeout_seconds INTEGER DEFAULT 120;  -- 取号倒计时(秒)
ALTER TABLE projects ADD COLUMN sort_order INTEGER DEFAULT 0;
```

### 3.5 新增 `channel_stats` 表（渠道统计）

```sql
CREATE TABLE channel_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id INTEGER NOT NULL,
    date TEXT NOT NULL,                    -- 统计日期 YYYY-MM-DD
    total_requests INTEGER DEFAULT 0,      -- 总请求次数
    success_count INTEGER DEFAULT 0,       -- 成功次数
    fail_count INTEGER DEFAULT 0,          -- 失败次数
    total_cost REAL DEFAULT 0,             -- 总成本
    avg_response_time REAL DEFAULT 0,      -- 平均响应时间(秒)
    UNIQUE(channel_id, date)
);
```

---

## 四、核心引擎 core/

### 4.1 `core/__init__.py`

空文件或包声明。

### 4.2 `core/queue.py` — 后台任务队列

```python
class TaskQueue:
    """
    全局异步任务队列
    - 所有上游调用的网络操作丢入线程池执行
    - HTTP API 层不阻塞
    """

    MAX_WORKERS = 20  # 全局最大线程数

    def __init__(self):
        self._executor = ThreadPoolExecutor(max_workers=self.MAX_WORKERS)
        self._tasks = {}  # task_id -> Future

    def submit_get_number(self, session_id: int, channel: ChannelDriver, project: dict) -> Future:
        """
        提交取号任务到线程池
        - 调用渠道取号
        - 成功后更新 sessions 表（phone, expire_at）
        - 失败则标记 session 为 failed
        """
        pass

    def submit_wait_sms(self, session_id: int, channel: ChannelDriver) -> Future:
        """
        提交等待验证码任务
        - 循环调用渠道 get_sms（间隔 2-5 秒）
        - 收到验证码后更新 sessions 表
        - 超时后标记为 expired 并释放号码
        """
        pass

    def get_task_status(self, task_id: str) -> str:
        """查询任务状态: pending / running / done / failed"""
        pass
```

### 4.3 `core/scheduler.py` — 后台调度器

```python
class Scheduler:
    """
    后台调度器（独立线程运行）
    职责:
    1. 定期检查超时未收到验证码的 session，自动释放
    2. 更新渠道统计
    3. 健康检查渠道连通性
    """

    CHECK_INTERVAL = 30  # 检查间隔（秒）

    def start(self):
        """启动调度器线程"""
        pass

    def _expire_check(self):
        """检查超时 session:
        - sessions.status='waiting' AND expire_at < now
        - → 调用渠道 release()
        - → 标记 sessions.status='expired'
        """
        pass

    def _update_stats(self):
        """汇总渠道统计，写入 channel_stats"""
        pass

    def _health_check(self):
        """对所有已启用渠道调 get_balance()，不可用时自动禁用并记录日志"""
        pass

    def stop(self):
        """停止调度器"""
        pass
```

---

## 五、对外 API（api/）

### 5.1 `api/__init__.py`

空文件。

### 5.2 `api/routes.py` — 统一 REST API

所有 API 返回 JSON：

```json
{
    "code": 0,      // 0=成功, 非0=错误码
    "msg": "ok",
    "data": { ... }
}
```

#### `POST /api/v1/number` — 取号

**请求：**
```json
{
    "project_id": 1,
    "country": "cn"
}
```

**响应：**
```json
{
    "code": 0,
    "data": {
        "session_id": 123,
        "phone": "13800138000",
        "expire_at": "2026-06-24 15:00:00"
    }
}
```

**错误：**
- 1001: 项目不存在
- 1002: 余额不足
- 1003: 无可用的渠道
- 1004: 渠道暂无号码

#### `GET /api/v1/number/:session_id` — 查验证码

**响应：**
```json
{
    "code": 0,
    "data": {
        "session_id": 123,
        "status": "waiting",    // waiting / received / expired / failed
        "phone": "13800138000",
        "code": null,           // 收到时返回验证码
        "sms_text": null        // 收到时返回完整短信
    }
}
```

#### `POST /api/v1/number/:session_id/release` — 释放号码

**响应：**
```json
{
    "code": 0,
    "msg": "ok"
}
```

#### `GET /api/v1/projects` — 获取可用项目列表

**响应：**
```json
{
    "code": 0,
    "data": [
        {
            "id": 1,
            "name": "抖音",
            "price": 1.5,
            "timeout": 120
        }
    ]
}
```

#### `GET /api/v1/balance` — 查询余额

**响应：**
```json
{
    "code": 0,
    "data": {
        "balance": 100.0
    }
}
```

### 5.3 `api/auth.py` — 鉴权

```
方式1: Cookie 登录（前台网页使用）
方式2: X-API-Key Header（脚本使用）
```

API Key 从 `cards` 表生成，每张卡密关联一个 API Key。

---

## 六、管理后台新增功能

### 6.1 渠道管理页

**新增路径：** `/admin/channels`

| 功能 | 说明 |
|------|------|
| 渠道列表 | 显示所有渠道，名称/驱动类/状态/并发上限/排序 |
| 新增渠道 | 选驱动类、填配置 JSON、设并发上限 |
| 编辑渠道 | 修改配置 |
| 启用/禁用 | 切换 status |
| 测连通性 | 调 `get_balance()`，显示结果 |
| 渠道拖拽排序 | 排序影响路由优先级 |

### 6.2 项目编辑（扩展）

在原有项目编辑基础上新增：

| 字段 | 说明 |
|------|------|
| 默认单价 | 该项目默认价格（元） |
| 超时时间 | 取号倒计时（秒），默认 120 |
| 渠道价格 | 每个渠道的单价 + 优先级（一对多） |

### 6.3 渠道统计页

**新增路径：** `/admin/channel_stats`

| 显示 | 说明 |
|------|------|
| 今日请求数/成功数/失败数 | 每个渠道独立 |
| 成功率 | 百分比 |
| 今日成本 | 总消耗 |
| 平均响应时间 | 从取号到收到验证码的平均耗时 |

### 6.4 充值页面（链动小铺整合）

**新增路径：** `/recharge`

页面展示：
- 一个跳转按钮 → 链动小铺链接
- 下方卡密兑换输入框（已有）

---

## 七、部署配置

### 7.1 新增 `.env` 文件

```ini
# 敏感配置，不进 git
SECRET_KEY=your-secret-key-here
ADMIN_PASSWORD=your-admin-password

# 部署地址（部署后改）
SITE_URL=http://your-domain:5000

# gunicorn 配置
GUNICORN_WORKERS=4
GUNICORN_PORT=5000
```

### 7.2 启动方式变更

```bash
# 旧：python3 app.py (Flask 单线程)
# 新：gunicorn -w 4 -b 0.0.0.0:5000 app:app (多 worker)
```

### 7.3 `app.py` 修改

在 `app.py` 中新增：

```python
# 启动调度器
from core.scheduler import Scheduler
scheduler = Scheduler()

def start_background():
    scheduler.start()

# 在 app.run() 之前或 gunicorn 的 on_starting hook 中调用
```

---

## 八、文件变更清单

### 新增文件

| 文件 | 说明 |
|------|------|
| `channels/base.py` | 渠道驱动基类 |
| `channels/fivesim.py` | 5sim 驱动模板 |
| `channels/router.py` | 智能路由 |
| `core/__init__.py` | 空 |
| `core/queue.py` | 后台任务队列 |
| `core/scheduler.py` | 后台调度器 |
| `api/__init__.py` | 空 |
| `api/routes.py` | 统一 REST API |
| `api/auth.py` | API 鉴权 |
| `.env` | 环境变量（不进 git） |
| `gunicorn_config.py` | gunicorn 配置文件 |
| `templates/admin/channel_prices.html` | 渠道价格管理页 |
| `templates/admin/channel_stats.html` | 渠道统计页 |
| `templates/user/recharge.html` | 充值页 |

### 修改文件

| 文件 | 变更 |
|------|------|
| `channels/haozhuma.py` | 重构为继承 ChannelDriver |
| `channels/__init__.py` | 导出 base 和 router |
| `models.py` | 新增 channels/channel_prices/channel_stats 模型 |
| `app.py` | 注册新蓝图 + 启动调度器 |
| `config.py` | 增加 .env 支持 |
| `views/admin.py` | 新增渠道管理路由 |
| `views/user.py` | 新增充值页路由 + API 路由 |
| `templates/admin/_sidebar.html` | 新增渠道管理/渠道统计菜单 |
| `templates/admin/dashboard.html` | 显示各渠道状态 |
| `requirements.txt` | 增加 gunicorn, python-dotenv |

---

## 九、验收标准

### Phase 1 验收

- [x] 后台可新增/编辑/启用/禁用渠道
- [x] 后台可配置每个渠道每个项目的价格
- [x] 后台可测试渠道连通性
- [x] 取号时自动选择最便宜的可用渠道
- [x] 渠道不可用时自动降级到下一个渠道
- [x] 加一个新渠道 = 新建几十行驱动文件 + 后台启用

### Phase 2 验收

- [x] gunicorn 4 workers 同时运行
- [x] 同时 10 个客户端取号+轮询，互不阻塞
- [x] 每个渠道有独立并发上限（后台可配）
- [x] 超过并发上限的请求自动排队
- [x] 号码倒计时到期自动释放
- [x] 后台调度器每分钟检查超时 session
- [x] 渠道掉线自动禁用

---

## 十、开发顺序

```
Day 1: channels/base.py → channels/haozhuma.py（重构）
        models.py 扩展 → channels/router.py
        views/admin.py 渠道管理页面

Day 2: core/queue.py → core/scheduler.py
        api/routes.py → api/auth.py
        app.py 改造 → gunicorn 接入

Day 3: 后台页面完善（渠道统计、渠道价格管理、充值页）
        .env + gunicorn_config.py
        整体联调测试
        压力测试
```