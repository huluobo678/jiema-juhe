"""渠道基类 - 所有接码渠道的抽象接口"""
import time, threading, json
from abc import ABC, abstractmethod

class ChannelBase(ABC):
    """接码渠道抽象基类"""
    
    def __init__(self, channel_id, name, config: dict):
        self.channel_id = channel_id
        self.name = name
        self.config = config  # api_url, api_user, api_pass, token, etc.
        self.alive = True     # 健康状态
        self.dead_since = 0   # 标记死亡的时间戳
        self.fail_count = 0   # 连续失败次数
        self.concurrency = 0  # 当前并发请求数
        self.max_concurrency = int(config.get('concurrent_limit', 5))
        self.vip_only = bool(int(config.get('vip_only') or 0))
        self._lock = threading.Lock()
    
    @abstractmethod
    def ping(self) -> bool:
        """健康检查 - 余额/状态查询"""
        pass
    
    @abstractmethod
    def get_phone(self, project_sid) -> dict:
        """获取号码（随机分配）"""
        pass
    
    def get_phone_by_number(self, project_sid: str, phone: str) -> dict:
        """
        指定号码取号。
        基类默认不支持，子类可覆盖。
        返回格式同 get_phone。
        """
        return {'code': -1, 'msg': '该渠道不支持指定号码取号'}
    
    @abstractmethod
    def get_message(self, project_sid, phone, activation_id: str | None = None) -> dict:
        """获取短信/验证码"""
        pass
    
    @abstractmethod
    def add_blacklist(self, project_sid, phone, activation_id: str | None = None) -> bool:
        """释放/拉黑号码"""
        pass
    
    @abstractmethod
    def get_balance(self) -> float:
        """查询渠道余额"""
        pass

    # ---- 并发控制 ----
    def acquire(self) -> bool:
        """尝试获取并发槽位"""
        with self._lock:
            if self.concurrency >= self.max_concurrency:
                return False
            self.concurrency += 1
            return True
    
    def release(self):
        """释放并发槽位"""
        with self._lock:
            self.concurrency = max(0, self.concurrency - 1)
    
    def mark_dead(self):
        """标记为死渠道"""
        self.alive = False
        self.dead_since = time.time()
        self.fail_count += 1
    
    def mark_alive(self):
        """标记为活渠道"""
        self.alive = True
        self.dead_since = 0
        self.fail_count = 0

    def is_dead(self) -> bool:
        if not self.alive:
            # 30秒后自动试活（半开状态）
            if time.time() - self.dead_since > 30:
                self.alive = True  # 暂时活
                return False
            return True
        return False


# ---- 注册中心 ----
class ChannelRegistry:
    """渠道注册中心 - 管理所有可用渠道"""
    
    def __init__(self):
        self._channels: dict[int, ChannelBase] = {}
        self._lock = threading.Lock()
    
    def register(self, channel: ChannelBase):
        with self._lock:
            self._channels[channel.channel_id] = channel
    
    def unregister(self, channel_id: int):
        with self._lock:
            self._channels.pop(channel_id, None)
    
    def get(self, channel_id: int) -> ChannelBase | None:
        return self._channels.get(channel_id)
    
    def get_all_alive(self) -> list[ChannelBase]:
        """获取所有活着的渠道"""
        with self._lock:
            return [c for c in self._channels.values() if not c.is_dead() and c.alive]
    
    def get_all(self) -> list[ChannelBase]:
        with self._lock:
            return list(self._channels.values())

    def get_by_name(self, name: str) -> ChannelBase | None:
        with self._lock:
            for c in self._channels.values():
                if c.name == name:
                    return c
            return None

# ---- 全局单例 ----
registry = ChannelRegistry()
