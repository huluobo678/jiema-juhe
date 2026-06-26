#!/usr/bin/env python3
import sys
sys.path.insert(0, "/root/sms-platform")
import sqlite3

print("=== 1. Import test ===")
from channels.herosms import HeroSMS
from channels.factory import create_channel_adapter
print("OK: imports work")

print("=== 2. Direct HeroSMS get_phone ===")
h = HeroSMS(2, "HeroSMS", {"token": "029c8f714273753958A496b86cA5669e"})
r = h.get_phone("dr")
print("Result:", r)
print("  ok=" + str(r.get("code")==0), "phone=" + str(r.get("phone")), "aid=" + str(r.get("activation_id")))

print("=== 3. Via factory ===")
db = sqlite3.connect("/root/sms-platform/sms.db")
db.row_factory = sqlite3.Row
ch = db.execute("SELECT * FROM channels WHERE id=2").fetchone()
db.close()
if ch:
    adapter = create_channel_adapter(ch)
    print("Adapter:", type(adapter).__name__)
    print("Ping:", adapter.ping())
    r2 = adapter.get_phone("dr")
    print("get_phone dr:", r2)

print("=== 4. Projects ===")
db = sqlite3.connect("/root/sms-platform/sms.db")
db.row_factory = sqlite3.Row
print("Channels:")
for c in db.execute("SELECT id, name, channel_type FROM channels"):
    print("  [{}] {} ({})".format(c["id"], c["name"], c["channel_type"]))
print("Projects:")
for p in db.execute("SELECT id, name, sid, channel_id FROM projects"):
    print("  [{}] {} sid={} channel={}".format(p["id"], p["name"], p["sid"], p["channel_id"]))
db.close()