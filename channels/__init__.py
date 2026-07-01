"""Channel registry bootstrap."""
from .base import ChannelRegistry, registry as _registry


def get_registry() -> ChannelRegistry:
    return _registry


def init_channels(db):
    """Load enabled channels from the database and register adapters."""
    from channels.factory import create_channel_adapter

    rows = db.execute("SELECT * FROM channels WHERE enabled=1").fetchall()
    registered = 0
    for row in rows:
        adapter = create_channel_adapter(row)
        if not adapter:
            continue
        if hasattr(adapter, 'login'):
            try:
                adapter.login()
            except Exception:
                pass
        _registry.register(adapter)
        registered += 1

    print(f"[Channels] initialized {registered}/{len(rows)} enabled channels")
    return _registry


def auto_register_channel(db_row, adapter_class):
    """Manually register one channel adapter."""
    config = {k: db_row[k] for k in ('api_url', 'api_user', 'api_pass', 'token', 'concurrent_limit') if k in db_row.keys()}
    config['channel_id'] = db_row['id']
    adapter = adapter_class(db_row['id'], db_row['name'], config)
    if hasattr(adapter, 'login'):
        try:
            adapter.login()
        except Exception:
            pass
    _registry.register(adapter)
    return adapter
