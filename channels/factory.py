"""渠道工厂 - 根据 channel_type 创建对应适配器实例"""
from channels.base import ChannelBase

def create_channel_adapter(db_row) -> ChannelBase | None:
    """
    根据数据库行记录创建对应类型的渠道适配器实例。
    不注册到注册中心，仅用于一次性操作（测试登录、余额查询等）。
    """
    def _g(row, key, default=''):
        try:
            v = row[key]
            return v if v is not None else default
        except (KeyError, IndexError):
            return default

    channel_type = (_g(db_row, 'channel_type') or '').lower()
    name = (_g(db_row, 'name') or '').lower()
    cid = _g(db_row, 'id', 0)
    cname = _g(db_row, 'name', '')
    config = {
        'api_url': _g(db_row, 'api_url', ''),
        'api_user': _g(db_row, 'api_user', ''),
        'api_pass': _g(db_row, 'api_pass', ''),
        'token': _g(db_row, 'token', ''),
        'concurrent_limit': _g(db_row, 'concurrent_limit', 5),
        'vip_only': _g(db_row, 'vip_only', 0),
        'channel_id': cid,
    }

    if channel_type == 'herosms' or 'herosms' in name:
        from .herosms import HeroSMS
        return HeroSMS(cid, cname, config)

    if channel_type == 'haozhuma' or 'haozhuma' in name or 'hz' in name or '豪猪' in name:
        from .haozhuma import HaoZhuMa
        return HaoZhuMa(cid, cname, config)

    # 默认按名称匹配
    if 'herosms' in name:
        from .herosms import HeroSMS
        return HeroSMS(cid, cname, config)

    if 'haozhuma' in name or 'hz' in name or '豪猪' in name:
        from .haozhuma import HaoZhuMa
        return HaoZhuMa(cid, cname, config)

    return None
