"""渠道注册中心 + 自动发现"""
import threading
from .base import ChannelRegistry, registry as _registry

# get_registry returns the shared singleton from base.py

def get_registry() -> ChannelRegistry:
    return _registry

# ---- 自动注册 (从数据库加载渠道) ----
def init_channels(db):
    """
    从数据库读取 enabled 渠道，自动初始化适配器并注册
    """
    from models import get_db
    rows = db.execute("SELECT * FROM channels WHERE enabled=1").fetchall()
    
    registered = 0
    for row in rows:
        name = row['name'].lower()
        config = {
            'api_url': row['api_url'],
            'api_user': row['api_user'] or '',
            'api_pass': row['api_pass'] or '',
            'token': row['token'] if 'token' in row.keys() else '',
            'concurrent_limit': row['concurrent_limit'] if 'concurrent_limit' in row.keys() else 5,
            'channel_id': row['id'],
        }
        
        adapter = None
        channel_type = (row['channel_type'] if 'channel_type' in row.keys() else '').lower()

        if 'haozhuma' in name or 'hz' in name or '豪猪' in name or channel_type == 'haozhuma':
            from .haozhuma import HaoZhuMa
            adapter = HaoZhuMa(row['id'], row['name'], config)
        elif 'herosms' in name or channel_type == 'herosms':
            from .herosms import HeroSMS
            adapter = HeroSMS(row['id'], row['name'], config)
        # 未来其他渠道可以在这里加 elif
        # elif 'other' in name or channel_type == 'mychannel':
        #     from .mychannel import MyChannel
        #     adapter = MyChannel(row['id'], row['name'], config)
        
        if adapter:
            # 首次登录
            try:
                adapter.login()
            except:
                pass
            _registry.register(adapter)
            registered += 1
    
    print(f"[Channels] 初始化完成：注册 {registered}/{len(rows)} 个渠道")
    return _registry


def auto_register_channel(db_row, adapter_class):
    """手动注册一个渠道适配器"""
    config = {k: db_row[k] for k in ('api_url', 'api_user', 'api_pass', 'token', 'concurrent_limit') if k in db_row}
    config['channel_id'] = db_row['id']
    adapter = adapter_class(db_row['id'], db_row['name'], config)
    try:
        adapter.login()
    except:
        pass
    _registry.register(adapter)
    return adapter