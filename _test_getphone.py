#!/usr/bin/env python3
import sys
sys.path.insert(0, "/root/sms-platform")

from channels.herosms import HeroSMS
h = HeroSMS(2, "HeroSMS", {"token": "029c8f714273753958A496b86cA5669e"})
print("Balance:", h.get_balance())
r = h.get_phone("dr")
print("get_phone(dr):", r)
if r.get("ok"):
    print("  phone:", r.get("phone"), "activation:", r.get("activation_id"))
else:
    print("  error:", r.get("msg"))
