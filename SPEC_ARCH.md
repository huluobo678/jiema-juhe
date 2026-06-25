# Architecture Upgrade SPEC: 多渠道智能调度 + 并发控制

## 目标
借鉴 sub2api 的后端架构模式，给接码平台加上**多渠道自动切换、健康检查、并发排队、熔断保护**。

## 当前问题
1. 只有一个渠道（豪猪），挂了就全挂
2. 没有健康检查——用户点了才知道渠道不可用
3. 没并发控制——多人同时用同一渠道可能被上游限速
4. 没熔断——渠道反复失败还继续尝试

## 架构改造

### 1. 渠道层抽象（已有 base.py，扩展）

```
channels/
├── __init__.py    - 注册中心 + 自动发现
├── base.py       - BaseChannel 抽象类
├── haozhuma.py   - 豪猪通道（已有）
├── backup.py     - 备用通道（如 xhzy/maiMai）
```

### 2. 健康检查器 (HealthChecker)

```python
# lib/health.py
class HealthChecker:
    - 每 60s 轮询所有 enabled 渠道
    - ping 测试（调用渠道的余额/状态 API）
    - 连续失败 N 次标记为 dead
    - 恢复：30s 后自动重试
```

### 3. 智能调度器 (SmartScheduler)

```python
# lib/scheduler.py
class SmartScheduler:
    - pick_best_channel(project_id) → 返回最优渠道
    - 策略：优先选活着的、负载最低、成本最低
    - 支持 sticky session（同一会话绑定同一渠道）
```

### 4. 并发控制器 (ConcurrencyController)

```python
# lib/throttle.py
class Throttle:
    - per_channel_semaphore: 每个渠道最多 N 个并发请求
    - per_project_queue: 同一项目排队
    - timeout: 排队超时返回"繁忙"提示
```

### 5. 熔断器 (CircuitBreaker)

```python
# lib/circuit.py
class CircuitBreaker:
    - 记录近 60s 失败率
    - 失败率 > 50% → 熔断 30s
    - 半开状态 → 放一个请求试探
```
