"""HeroSMS 渠道适配器

基于 SMS-Activate 兼容协议，适合海外号码接码。

协议说明：
  getBalance → "ACCESS_BALANCE:100.5"
  getNumberV2 → JSON {"activationId":"...","phoneNumber":"...","activationCost":...}
  getStatus → "STATUS_OK:code" 或 "STATUS_WAIT_CODE" 等
  setStatus → "ACCESS_READY"/"ACCESS_CANCEL" 等

使用方式：
  1. 后台渠道管理添加渠道，类型选 herosms
  2. API地址填 https://hero-sms.com/stubs/handler_api.php
  3. Token 填你的 API Key（而非用户名密码）
"""
import requests
import json
import time
from channels.base import ChannelBase
from lib.circuit import circuit_registry


# SMS-Activate status strings → 内部状态
STATUS_MAP = {
    'STATUS_WAIT_CODE': 'waiting',
    'STATUS_OK': 'received',
    'STATUS_CANCEL': 'canceled',
    'STATUS_WAIT_RETRY': 'waiting',
}


class HeroSMS(ChannelBase):
    """HeroSMS 渠道适配器"""

    def __init__(self, channel_id, name, config: dict):
        super().__init__(channel_id, name, config)
        self._api_key = config.get('token') or config.get('api_key', '')
        self.base_url = (config.get('api_url') or
                         'https://hero-sms.com/stubs/handler_api.php').rstrip('/')
        self.circuit = circuit_registry.get(f'channel:{name}')
        # 缓存 phone → activation_id 映射（备用）
        self._phone_activation_map: dict[str, str] = {}

    # ── 底层请求 ──────────────────────────────────

    def _req(self, params: dict) -> str:
        """发起 GET 请求，返回原始文本"""
        url = self.base_url
        params['api_key'] = self._api_key
        try:
            r = requests.get(url, params=params, timeout=15)
            return r.text.strip()
        except requests.Timeout:
            return 'ERROR:请求超时'
        except requests.ConnectionError as e:
            return f'ERROR:连接失败: {e}'
        except Exception as e:
            return f'ERROR:{e}'

    def _is_success(self, text: str) -> bool:
        """判断是否成功（非错误响应）"""
        return (not text.startswith('ERROR:') and
                not text.startswith('BAD_') and
                not text.startswith('NO_') and
                text not in ('', 'TIMEOUT'))

    # ── 辅助：解析 getNumberV2 JSON ────────────────

    def _get_country_param(self) -> str:
        """尝试从 api_url 查询字符串或 config 读取 country 参数"""
        # 从 api_url 的查询字符串提取 ?country=XX
        if '?' in self.base_url:
            qs = self.base_url.split('?', 1)[1]
            for part in qs.split('&'):
                if '=' in part:
                    k, v = part.split('=', 1)
                    if k == 'country':
                        return v
        # 从 config 指定
        country = self.config.get('country', '')
        if country:
            return country
        # 默认：荷兰（号码池最大）
        return '48'

    def _parse_json_number(self, text: str) -> dict | None:
        """尝试解析 JSON 格式的 getNumberV2 响应"""
        if text.startswith('{'):
            try:
                data = json.loads(text)
                if 'activationId' in data and 'phoneNumber' in data:
                    return data
            except json.JSONDecodeError:
                pass
        return None

    # ── ChannelBase 接口实现 ─────────────────────

    def ping(self) -> bool:
        """健康检查：查余额"""
        text = self._req({'action': 'getBalance'})
        ok = text.startswith('ACCESS_BALANCE:')
        self.circuit.record(ok)
        return ok

    def get_phone(self, project_sid: str) -> dict:
        """
        获取号码。

        project_sid 是 SMS-Activate 的 service 代码，如 tg/wa/go/al/ub 等。

        返回：
            {'code': 0, 'phone': '...', 'activation_id': '...'}
            或 {'code': -1, 'msg': '...'}
        """
        # HeroSMS 需要指定 country，默认 48=Netherlands（有最多号码量）
        # 也可以通过渠道配置的 api_url 查询字符串覆盖
        country = self._get_country_param()
        params = {'action': 'getNumberV2', 'service': project_sid}
        if country:
            params['country'] = country

        text = self._req(params)

        # 1) 尝试 JSON 格式 (getNumberV2)
        data = self._parse_json_number(text)
        if data:
            self._phone_activation_map[data['phoneNumber']] = str(data['activationId'])
            self.circuit.record(True)
            return {
                'code': 0,
                'phone': data['phoneNumber'],
                'activation_id': str(data['activationId']),
            }

        # 2) 尝试旧格式 ACCESS_NUMBER:id:phone
        if text.startswith('ACCESS_NUMBER:'):
            parts = text.split(':')
            if len(parts) >= 3:
                activation_id = parts[1].strip()
                phone = parts[2].strip()
                self._phone_activation_map[phone] = activation_id
                self.circuit.record(True)
                return {'code': 0, 'phone': phone, 'activation_id': activation_id}

        # 3) 尝试 getNumber 旧格式（不带 V2）
        if text.startswith('ACCESS_NUMBER'):
            # 再试一次 V1 格式
            parts = text.split(':')
            if len(parts) >= 3:
                aid = parts[1].strip()
                phone = parts[2].strip()
                self._phone_activation_map[phone] = aid
                self.circuit.record(True)
                return {'code': 0, 'phone': phone, 'activation_id': aid}

        # 失败
        self.circuit.record(False)
        error_msg = self._translate_error(text)
        return {'code': -1, 'msg': error_msg}

    def get_message(self, project_sid: str, phone: str, activation_id: str | None = None) -> dict:
        """
        查询验证码。

        参数：
            project_sid: 项目 service 代码
            phone: 手机号
            activation_id: 激活ID（如果已有优先使用）

        返回：
            {'code': 0, 'yzm': '...', 'sms': '...'}
            或 {'code': -1, 'msg': '...', 'waiting': True}
        """
        aid = activation_id or self._phone_activation_map.get(phone, '')

        params = {'action': 'getStatus'}
        if aid:
            params['id'] = aid
        else:
            params['phone'] = phone

        text = self._req(params)

        # STATUS_OK:code — 收到验证码
        if text.startswith('STATUS_OK:'):
            code = text.split(':', 1)[1].strip()
            self.circuit.record(True)
            return {'code': 0, 'yzm': code, 'sms': code}

        # 其他需要等待的状态
        if text in ('STATUS_WAIT_CODE', 'STATUS_WAIT_RETRY', 'STATUS_ON_HOLD'):
            return {'code': -1, 'msg': '等待验证码中...', 'waiting': True}

        if text == 'STATUS_CANCEL':
            return {'code': -1, 'msg': '已取消'}

        if text == 'STATUS_FINISH' or text.startswith('STATUS_OK'):
            # 已经完成但没有 code（不太可能）
            return {'code': -1, 'msg': '已完成但未收到内容'}

        # 未知状态
        self.circuit.record(False)
        return {'code': -1, 'msg': f'未知状态: {text[:80]}'}

    def add_blacklist(self, project_sid: str, phone: str, activation_id: str | None = None) -> bool:
        """释放/取消号码"""
        aid = activation_id or self._phone_activation_map.get(phone, '')
        params = {'action': 'setStatus', 'status': '8'}
        if aid:
            params['id'] = aid
        else:
            params['phone'] = phone

        text = self._req(params)
        ok = text in ('ACCESS_CANCEL', 'ACCESS_READY')
        return ok

    def get_balance(self) -> float:
        """查询上游余额"""
        text = self._req({'action': 'getBalance'})
        if text.startswith('ACCESS_BALANCE:'):
            try:
                return float(text.split(':', 1)[1].strip())
            except (ValueError, IndexError):
                pass
        return 0.0

    # ── 辅助 ──────────────────────────────────

    def _translate_error(self, text: str) -> str:
        """将 SMS-Activate 错误码翻译为中文"""
        error_map = {
            'NO_BALANCE': '余额不足',
            'NO_NUMBERS': '暂无可用的号码',
            'NO_ACTIVATION': '激活记录不存在',
            'BAD_ACTION': '非法操作',
            'BAD_SERVICE': '服务代码不存在',
            'BAD_KEY': 'API Key 无效',
            'ERROR:请求超时': '请求上游超时',
        }
        for prefix, msg in error_map.items():
            if text.startswith(prefix):
                return msg
        if text.startswith('ERROR:'):
            return f'上游错误: {text[6:80]}'
        return f'HeroSMS 未知响应: {text[:80]}'
