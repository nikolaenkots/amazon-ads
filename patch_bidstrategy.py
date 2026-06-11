import os, ast

path = os.path.expanduser('~/amazon-ads/send.py')
with open(path) as f:
    s = f.read()

OLD = '''        strategy = "AUTO_FOR_SALES" if c.get("type") == "auto" else "MANUAL"'''
NEW = '''        BID_STRATEGY_MAP = {
            "Dynamic bids - down only":   "LEGACY_FOR_SALES",
            "Dynamic bids - up and down": "AUTO_FOR_SALES",
            "Fixed bid":                  "MANUAL",
        }
        strategy = BID_STRATEGY_MAP.get(c.get("bidStrategy"), "LEGACY_FOR_SALES")'''

if OLD in s:
    s = s.replace(OLD, NEW)
    print("bidStrategy mapping: OK")
else:
    print("NOT FOUND — already patched or structure changed")

with open(path,'w') as f:
    f.write(s)

ast.parse(s)
print(f"send.py syntax OK ({len(s)} chars)")
