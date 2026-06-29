"""Smart channel scheduler."""
from channels.base import registry as channel_registry
from lib.circuit import circuit_registry


class SmartScheduler:
    def __init__(self):
        self._sticky: dict[str, int] = {}

    def _project_channel_id(self, project):
        try:
            value = project['channel_id']
        except (KeyError, IndexError, TypeError):
            value = getattr(project, 'channel_id', None)
        return int(value) if value is not None else None

    def _available(self, channel, exclude_ids: set) -> bool:
        if channel is None:
            return False
        if channel.channel_id in exclude_ids:
            return False
        if channel.is_dead():
            return False
        return circuit_registry.get(f'channel:{channel.name}').allow_request()

    def pick_channel(self, project, exclude_ids: set = None):
        """Pick the channel bound to the project, falling back only when no binding exists."""
        exclude_ids = exclude_ids or set()
        channel_id = self._project_channel_id(project)
        if channel_id is not None:
            channel = channel_registry.get(channel_id)
            return channel if self._available(channel, exclude_ids) else None

        candidates = []
        for channel in channel_registry.get_all_alive():
            if self._available(channel, exclude_ids):
                candidates.append((channel.concurrency, channel))
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0])
        return candidates[0][1]

    def pick_channel_for_project(self, project_channels, exclude_ids: set = None):
        exclude_ids = exclude_ids or set()
        for pc in project_channels:
            channel = channel_registry.get(pc['channel_id'])
            if not self._available(channel, exclude_ids):
                continue
            if not channel.acquire():
                continue
            return channel
        return None

    def set_sticky(self, view_token: str, channel_id: int):
        self._sticky[view_token] = channel_id

    def get_sticky(self, view_token: str) -> int | None:
        return self._sticky.get(view_token)

    def release_sticky(self, view_token: str):
        self._sticky.pop(view_token, None)

    def status(self) -> list[dict]:
        result = []
        for channel in channel_registry.get_all():
            circuit = circuit_registry.get(f'channel:{channel.name}').stats()
            result.append({
                'id': channel.channel_id,
                'name': channel.name,
                'alive': channel.alive,
                'concurrency': channel.concurrency,
                'max_concurrency': channel.max_concurrency,
                'circuit_state': circuit['state'],
                'fail_rate': round(circuit['fail_rate'] * 100, 1),
            })
        return result


scheduler = SmartScheduler()
