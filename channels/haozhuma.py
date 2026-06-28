"""豪猪接码平台适配器 - 实现 ChannelBase 接口"""
import requests
import time
from channels.base import ChannelBase
from lib.circuit import circuit_registry

class HaoZhuMa(ChannelBase):
    """豪猪渠道适配器"""
    
    API_PATHS = {
        'login': '/sms/?api=login',
        'summary': '/sms/?api=getSummary',
        'getPhone': '/sms/?api=getPhone',
        'getMessage': '/sms/?api=getMessage',
        'addBlacklist': '/sms/?api=addBlacklist',
    }

    def __init__(self, channel_id, name, config: dict):
        super().__init__(channel_id, name, config)
        self._token = config.get('token')
        self.circuit = circuit_registry.get(f'channel:{name}')
    
    def _req(self, path, params):
        url = self.config['api_url'].rstrip('/') + path
        try:
            r = requests.get(url, params=params, timeout=15)
            return r.json()
        except requests.Timeout:
            return {'code': -1, 'msg': '请求超时'}
        except requests.ConnectionError as e:
            return {'code': -1, 'msg': f'连接失败: {e}'}
        except Exception as e:
            return {'code': -1, 'msg': str(e)}

    def _is_ok(self, data):
        code = data.get('code')
        return code == 0 or code == '0'

    def login(self):
        """登录获取token"""
        data = self._req(self.API_PATHS['login'], {
            'user': self.config['api_user'],
            'pass': self.config['api_pass'],
        })
        if self._is_ok(data):
            self._token = data.get('token')
        return data

    # ---- ChannelBase 接口实现 ----

    def ping(self) -> bool:
        """健康检查：查余额/登录"""
        if not self._token:
            self.login()
        if not self._token:
            return False
        data = self._req(self.API_PATHS['summary'], {'token': self._token})
        ok = self._is_ok(data)
        self.circuit.record(ok)
        return ok

    def get_phone(self, project_sid) -> dict:
        if not self._token:
            self.login()
        params = {'token': self._token, 'sid': project_sid}
        data = self._req(self.API_PATHS['getPhone'], params)
        self.circuit.record(self._is_ok(data))
        return data

    def get_phone_by_number(self, project_sid, phone) -> dict:
        """指定号码取号"""
        if not self._token:
            self.login()
        params = {'token': self._token, 'sid': project_sid, 'phone': phone}
        data = self._req(self.API_PATHS['getPhone'], params)
        self.circuit.record(self._is_ok(data))
        return data

    def get_message(self, project_sid, phone, activation_id=None) -> dict:
        if not self._token:
            self.login()
        data = self._req(self.API_PATHS['getMessage'], {
            'token': self._token, 'sid': project_sid, 'phone': phone
        })
        ok = self._is_ok(data)
        self.circuit.record(ok)
        # 豪猪 code=0 表示请求成功，不是验证码已到
        # 验证码在 yzm 字段，未到时 yzm=0（整数）
        yzm_raw = data.get('yzm', 0)
        yzm = str(yzm_raw) if yzm_raw else ''
        if ok and yzm:
            return {'code': 0, 'yzm': yzm, 'sms': data.get('sms', '')}
        if not yzm:
            return {'code': -1, 'msg': '等待验证码中...', 'waiting': True}
        return data

    def add_blacklist(self, project_sid, phone, activation_id=None) -> bool:
        if not self._token:
            self.login()
        data = self._req(self.API_PATHS['addBlacklist'], {
            'token': self._token, 'sid': project_sid, 'phone': phone
        })
        return self._is_ok(data)

    def get_balance(self) -> float:
        if not self._token:
            self.login()
        data = self._req(self.API_PATHS['summary'], {'token': self._token})
        if self._is_ok(data):
            return float(data.get('money', 0))
        return 0.0