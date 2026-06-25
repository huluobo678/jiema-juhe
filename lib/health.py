"""健康检查器 - 定期检查渠道可用性"""
import time, threading

class HealthChecker:
    """定时检查所有注册渠道的健康状态"""
    
    def __init__(self, registry, interval=60):
        self.registry = registry
        self.interval = interval           # 检查间隔(秒)
        self.max_fails = 2                 # 连续失败N次标记死亡
        self._running = False
        self._thread = None
    
    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name='health-checker')
        self._thread.start()
        print(f"[HealthChecker] 已启动，每{self.interval}秒检查一次")
    
    def stop(self):
        self._running = False
    
    def _loop(self):
        while self._running:
            try:
                self._check_all()
            except Exception as e:
                print(f"[HealthChecker] 检查异常: {e}")
            time.sleep(self.interval)
    
    def _check_all(self):
        """逐一 ping 所有渠道"""
        for ch in self.registry.get_all():
            try:
                ok = ch.ping()
                if ok:
                    ch.mark_alive()
                else:
                    ch.fail_count += 1
                    if ch.fail_count >= self.max_fails:
                        ch.mark_dead()
                        print(f"[HealthChecker] ⛔ {ch.name} 已连续{ch.fail_count}次失败，标记死亡")
            except Exception as e:
                ch.fail_count += 1
                if ch.fail_count >= self.max_fails:
                    ch.mark_dead()
                    print(f"[HealthChecker] ⛔ {ch.name} 异常: {e}")
    
    def status(self) -> list[dict]:
        """获取所有渠道健康状态"""
        return [{
            'id': ch.channel_id,
            'name': ch.name,
            'alive': ch.alive,
            'fail_count': ch.fail_count,
            'concurrency': ch.concurrency,
            'max_concurrency': ch.max_concurrency,
        } for ch in self.registry.get_all()]

# 全局单例
health_checker = None

def init_health_checker(registry):
    global health_checker
    health_checker = HealthChecker(registry)
    health_checker.start()
    return health_checker