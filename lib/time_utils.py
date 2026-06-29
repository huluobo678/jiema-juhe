from datetime import datetime, timedelta, timezone

BEIJING_TZ = timezone(timedelta(hours=8))


def beijing_now():
    return datetime.now(BEIJING_TZ)


def beijing_now_str():
    return beijing_now().strftime('%Y-%m-%d %H:%M:%S')


def beijing_after(seconds):
    return (beijing_now() + timedelta(seconds=seconds)).strftime('%Y-%m-%d %H:%M:%S')
