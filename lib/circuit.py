"""熔断器 - 防止渠道反复失败"""
import time
from collections import deque

class CircuitBreaker:
    """
    熔断器状态机:
      CLOSED  (正常) → 失败率超阈值 → OPEN (熔断)
      OPEN    (熔断) → 超时 → HALF_OPEN (半开)
      HALF_OPEN (半开) → 成功 → CLOSED
      HALF_OPEN (半开) → 失败 → OPEN (再次熔断)
    """
    
    def __init__(self, name: str, failure_threshold: float = 0.5, 
                 window_seconds: int = 60, open_seconds: int = 30):
        self.name = name
        self.failure_threshold = failure_threshold  # 失败率阈值 0.5 = 50%
        self.window_seconds = window_seconds        # 统计窗口(秒)
        self.open_seconds = open_seconds             # 熔断时长(秒)
        
        # 状态
        self.state = 'CLOSED'    # CLOSED / OPEN / HALF_OPEN
        self.state_changed_at = 0
        
        # 滑动窗口记录
        self._records = deque()  # [(timestamp, True=success, False=fail)]
        self._lock = __import__('threading').Lock()
    
    def _trim(self):
        """清理过期记录"""
        now = time.time()
        cutoff = now - self.window_seconds
        while self._records and self._records[0][0] < cutoff:
            self._records.popleft()
    
    def record(self, success: bool):
        """记录一次请求结果"""
        with self._lock:
            self._records.append((time.time(), success))
            self._trim()
            
            total = len(self._records)
            if total < 5:  # 样本太少不熔断
                return
            
            fails = sum(1 for _, s in self._records if not s)
            fail_rate = fails / total
            
            if self.state == 'CLOSED' and fail_rate >= self.failure_threshold:
                self.state = 'OPEN'
                self.state_changed_at = time.time()
            elif self.state == 'HALF_OPEN':
                if success:
                    self.state = 'CLOSED'
                    self.state_changed_at = 0
                    self._records.clear()
                else:
                    self.state = 'OPEN'
                    self.state_changed_at = time.time()
    
    def allow_request(self) -> bool:
        """判断是否允许通过"""
        with self._lock:
            if self.state == 'CLOSED':
                return True
            if self.state == 'OPEN':
                if time.time() - self.state_changed_at >= self.open_seconds:
                    self.state = 'HALF_OPEN'
                    return True
                return False
            # HALF_OPEN - 放行试探
            return True
    
    def stats(self) -> dict:
        """当前状态"""
        with self._lock:
            self._trim()
            total = len(self._records)
            fails = sum(1 for _, s in self._records if not s)
            return {
                'state': self.state,
                'fail_rate': fails / total if total > 0 else 0,
                'total_requests': total,
                'fails': fails,
            }


class CircuitRegistry:
    """熔断器注册中心"""
    
    def __init__(self):
        self._breakers: dict[str, CircuitBreaker] = {}
    
    def get(self, name: str) -> CircuitBreaker:
        if name not in self._breakers:
            self._breakers[name] = CircuitBreaker(name)
        return self._breakers[name]
    
    def stats_all(self) -> dict:
        return {name: cb.stats() for name, cb in self._breakers.items()}

circuit_registry = CircuitRegistry()