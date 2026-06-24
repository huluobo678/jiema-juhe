"""豪猪接码平台适配器"""
import requests
import time

API_PATHS = {
    'login': '/sms/?api=login',
    'summary': '/sms/?api=getSummary',
    'getPhone': '/sms/?api=getPhone',
    'getMessage': '/sms/?api=getMessage',
    'addBlacklist': '/sms/?api=addBlacklist',
}

class HaoZhuMa:
    def __init__(self, api_url, api_user, api_pass, token=None):
        self.api_url = api_url.rstrip('/')
        self.api_user = api_user
        self.api_pass = api_pass
        self._token = token

    def _req(self, path, params):
        url = self.api_url + path
        try:
            r = requests.get(url, params=params, timeout=15)
            return r.json()
        except Exception as e:
            return {'code': -1, 'msg': str(e)}

    def _is_ok(self, data):
        """豪猪code可能是字符串'0'或数字0"""
        code = data.get('code')
        return code == 0 or code == '0'

    def login(self):
        """登录获取token"""
        data = self._req(API_PATHS['login'], {
            'user': self.api_user,
            'pass': self.api_pass,
        })
        if self._is_ok(data):
            self._token = data.get('token')
        return data

    def get_summary(self):
        """查询余额"""
        return self._req(API_PATHS['summary'], {'token': self._token})

    def get_phone(self, sid, isp=None, province=None, uid=None, author=None):
        """获取号码"""
        params = {'token': self._token, 'sid': sid}
        if isp: params['isp'] = isp
        if province: params['Province'] = province
        if uid: params['uid'] = uid
        if author: params['author'] = author
        return self._req(API_PATHS['getPhone'], params)

    def get_message(self, sid, phone):
        """获取验证码"""
        return self._req(API_PATHS['getMessage'], {
            'token': self._token,
            'sid': sid,
            'phone': phone,
        })

    def add_blacklist(self, sid, phone):
        """拉黑号码"""
        return self._req(API_PATHS['addBlacklist'], {
            'token': self._token,
            'sid': sid,
            'phone': phone,
        })

    def wait_for_sms(self, sid, phone, max_wait=120, interval=3):
        """轮询等待验证码"""
        deadline = time.time() + max_wait
        while time.time() < deadline:
            data = self.get_message(sid, phone)
            if self._is_ok(data):
                return data  # 包含 yzm 和 sms 字段
            time.sleep(interval)
        return {'code': -1, 'msg': '超时未收到验证码'}