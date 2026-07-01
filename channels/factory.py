"""娓犻亾宸ュ巶 - 鏍规嵁 channel_type 鍒涘缓瀵瑰簲閫傞厤鍣ㄥ疄渚?"""
from channels.base import ChannelBase

def create_channel_adapter(db_row) -> ChannelBase | None:
    """
    鏍规嵁鏁版嵁搴撹璁板綍鍒涘缓瀵瑰簲绫诲瀷鐨勬笭閬撻€傞厤鍣ㄥ疄渚嬨€?
    涓嶆敞鍐屽埌娉ㄥ唽涓績锛屼粎鐢ㄤ簬涓€娆℃€ф搷浣滐紙娴嬭瘯鐧诲綍銆佷綑棰濇煡璇㈢瓑锛夈€?
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
        'channel_id': cid,
    }

    if channel_type == 'herosms' or 'herosms' in name:
        from .herosms import HeroSMS
        return HeroSMS(cid, cname, config)

    if channel_type == 'haozhuma' or 'haozhuma' in name or 'hz' in name or '璞尓' in name:
        from .haozhuma import HaoZhuMa
        return HaoZhuMa(cid, cname, config)

    if 'herosms' in name:
        from .herosms import HeroSMS
        return HeroSMS(cid, cname, config)

    if 'haozhuma' in name or 'hz' in name or '璞尓' in name:
        from .haozhuma import HaoZhuMa
        return HaoZhuMa(cid, cname, config)

    return None
