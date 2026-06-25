"""智能调度器 - 为项目选择最优渠道"""
import time, random
from channels.base import registry as channel_registry
from lib.circuit import circuit_registry

class SmartScheduler:
    """
    智能调度器 - 多策略选择最优渠道
    
    策略：
    1. 优先 alive 的渠道
    2. 排除熔断中的渠道
    3. 按并发负载排序（低→高）
    4. 同负载选成本最低的
    5. 支持 sticky session（同一对话绑定同一渠道）
    """
    
    def __init__(self):
        self._sticky: dict[str, int] = {}  # view_token → channel_id
    
    def pick_channel(self, project, exclude_ids: set = None) -> tuple:
        """
        为项目选择最优渠道
        返回: (channel_adapter, channel_db_row) or (None, None)
        """
        if exclude_ids is None:
            exclude_ids = set()
        
        candidates = []
        
        # 项目可以绑定多个渠道（通过 project_channels 表）
        # 或回退到所有可用渠道
        for ch in channel_registry.get_all_alive():
            if ch.channel_id in exclude_ids:
                continue
            if ch.is_dead():
                continue
            
            cb = circuit_registry.get(f'channel:{ch.name}')
            if not cb.allow_request():
                continue
            
            # 分数 = 并发数 + (0 if alive else 999)
            score = ch.concurrency
            if not ch.alive:
                score += 999
            
            candidates.append((score, ch))
        
        if not candidates:
            return None
        
        # 按分数升序（并发最低的优先）
        candidates.sort(key=lambda x: x[0])
        return candidates[0][1]
    
    def pick_channel_for_project(self, project_channels, exclude_ids: set = None):
        """
        从项目的渠道列表中选最优
        project_channels: [(channel_id, channel_name, order)]
        """
        if exclude_ids is None:
            exclude_ids = set()
        
        for pc in project_channels:
            cid = pc['channel_id']
            if cid in exclude_ids:
                continue
            ch = channel_registry.get(cid)
            if ch is None:
                continue
            if ch.is_dead():
                continue
            cb = circuit_registry.get(f'channel:{ch.name}')
            if not cb.allow_request():
                continue
            if not ch.acquire():
                continue  # 并发满，跳过
            
            return ch
        
        return None
    
    def set_sticky(self, view_token: str, channel_id: int):
        """绑定粘性会话"""
        self._sticky[view_token] = channel_id
    
    def get_sticky(self, view_token: str) -> int | None:
        """获取粘性会话绑定的渠道"""
        return self._sticky.get(view_token)
    
    def release_sticky(self, view_token: str):
        """释放粘性会话"""
        self._sticky.pop(view_token, None)

    def status(self) -> list[dict]:
        """调度器状态"""
        result = []
        for ch in channel_registry.get_all():
            cb = circuit_registry.get(f'channel:{ch.name}')
            s = cb.stats()
            result.append({
                'id': ch.channel_id,
                'name': ch.name,
                'alive': ch.alive,
                'concurrency': ch.concurrency,
                'max_concurrency': ch.max_concurrency,
                'circuit_state': s['state'],
                'fail_rate': round(s['fail_rate'] * 100, 1),
            })
        return result


# 全局单例
scheduler = SmartScheduler()