"""HeroSMS adapter using the SMS-Activate compatible API."""
import json
from urllib.parse import parse_qs, urlparse

import requests

from channels.base import ChannelBase
from lib.circuit import circuit_registry


class HeroSMS(ChannelBase):
    def __init__(self, channel_id, name, config: dict):
        super().__init__(channel_id, name, config)
        self._api_key = config.get('token') or config.get('api_key') or ''
        self.base_url = (config.get('api_url') or 'https://hero-sms.com/stubs/handler_api.php').rstrip('/')
        self.circuit = circuit_registry.get(f'channel:{name}')
        self._phone_activation_map: dict[str, str] = {}

    def _req(self, params: dict) -> str:
        params = dict(params)
        params['api_key'] = self._api_key
        try:
            response = requests.get(self.base_url, params=params, timeout=15)
            return response.text.strip()
        except requests.Timeout:
            return 'ERROR:request timeout'
        except requests.ConnectionError as exc:
            return f'ERROR:connection failed: {exc}'
        except Exception as exc:
            return f'ERROR:{exc}'

    def _get_country_param(self) -> str:
        parsed = urlparse(self.base_url)
        query = parse_qs(parsed.query)
        if query.get('country'):
            return query['country'][0]
        country = self.config.get('country', '')
        return str(country or '16')

    def _parse_project_sid(self, project_sid):
        if isinstance(project_sid, dict):
            service = str(project_sid.get('sid') or project_sid.get('service') or '').strip()
            country = str(project_sid.get('country') or '').strip() or self._get_country_param()
            return service, country
        service = str(project_sid or '').strip()
        country = self._get_country_param()
        if '@' in service:
            service, country_part = service.split('@', 1)
            country = country_part.strip() or country
        return service.strip(), country

    def _parse_json_number(self, text: str) -> dict | None:
        if text.startswith('{'):
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                return None
            if 'activationId' in data and 'phoneNumber' in data:
                return data
        return None

    def ping(self) -> bool:
        text = self._req({'action': 'getBalance'})
        ok = text.startswith('ACCESS_BALANCE:')
        self.circuit.record(ok)
        return ok

    def get_phone(self, project_sid: str) -> dict:
        service, country = self._parse_project_sid(project_sid)
        params = {'action': 'getNumberV2', 'service': service}
        if country:
            params['country'] = country
        return self._do_get_phone(params)

    def get_phone_by_number(self, project_sid: str, phone: str) -> dict:
        service, country = self._parse_project_sid(project_sid)
        params = {'action': 'getNumberV2', 'service': service, 'phone': phone}
        if country:
            params['country'] = country
        return self._do_get_phone(params)

    def _do_get_phone(self, params: dict) -> dict:
        text = self._req(params)
        data = self._parse_json_number(text)
        if data:
            phone = str(data['phoneNumber'])
            activation_id = str(data['activationId'])
            self._phone_activation_map[phone] = activation_id
            self.circuit.record(True)
            return {'code': 0, 'phone': phone, 'activation_id': activation_id}

        if text.startswith('ACCESS_NUMBER:'):
            parts = text.split(':')
            if len(parts) >= 3:
                activation_id = parts[1].strip()
                phone = parts[2].strip()
                self._phone_activation_map[phone] = activation_id
                self.circuit.record(True)
                return {'code': 0, 'phone': phone, 'activation_id': activation_id}

        self.circuit.record(False)
        return {'code': -1, 'msg': self._translate_error(text)}

    def get_message(self, project_sid, phone, activation_id: str | None = None) -> dict:
        aid = activation_id or self._phone_activation_map.get(phone, '')
        params = {'action': 'getStatus'}
        if aid:
            params['id'] = aid
        else:
            params['phone'] = phone

        text = self._req(params)
        if text.startswith('{'):
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                data = {}
            status = data.get('status', '')
            code = data.get('code', '')
            if status == 'STATUS_OK' or code:
                self.circuit.record(True)
                return {'code': 0, 'yzm': code, 'sms': data.get('sms', code)}
            if status in ('STATUS_WAIT_CODE', 'STATUS_WAIT_RETRY', 'STATUS_ON_HOLD'):
                return {'code': -1, 'msg': '等待验证码中...', 'waiting': True}
            if status == 'STATUS_CANCEL':
                return {'code': -1, 'msg': '已取消'}

        if text.startswith('STATUS_OK:'):
            code = text.split(':', 1)[1].strip()
            self.circuit.record(True)
            return {'code': 0, 'yzm': code, 'sms': code}
        if text in ('STATUS_WAIT_CODE', 'STATUS_WAIT_RETRY', 'STATUS_ON_HOLD'):
            return {'code': -1, 'msg': '等待验证码中...', 'waiting': True}
        if text == 'STATUS_CANCEL':
            return {'code': -1, 'msg': '已取消'}

        self.circuit.record(False)
        return {'code': -1, 'msg': f'未知状态: {text[:80]}'}

    def add_blacklist(self, project_sid, phone, activation_id: str | None = None) -> bool:
        aid = activation_id or self._phone_activation_map.get(phone, '')
        params = {'action': 'setStatus', 'status': '8'}
        if aid:
            params['id'] = aid
        else:
            params['phone'] = phone
        return self._req(params) in ('ACCESS_CANCEL', 'ACCESS_READY')

    def get_balance(self) -> float:
        text = self._req({'action': 'getBalance'})
        if text.startswith('ACCESS_BALANCE:'):
            try:
                return float(text.split(':', 1)[1].strip())
            except (ValueError, IndexError):
                return 0.0
        return 0.0

    def _translate_error(self, text: str) -> str:
        error_map = {
            'NO_BALANCE': '上游余额不足',
            'NO_NUMBERS': '暂无可用号码',
            'NO_ACTIVATION': '激活记录不存在',
            'BAD_ACTION': '非法操作',
            'BAD_SERVICE': '服务代码不存在',
            'BAD_KEY': 'API Key 无效',
        }
        for prefix, message in error_map.items():
            if text.startswith(prefix):
                return message
        if text.startswith('ERROR:'):
            return f'上游错误: {text[6:80]}'
        return f'HeroSMS 未知响应: {text[:80]}'