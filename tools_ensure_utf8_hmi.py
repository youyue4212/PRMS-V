# -*- coding: utf-8 -*-
"""Verify and force-save hmi_web/index.html as UTF-8 (no BOM)."""
from pathlib import Path

p = Path(__file__).resolve().parent / "hmi_web" / "index.html"
raw = p.read_bytes()
text = None
for enc in ("utf-8", "utf-8-sig", "gbk", "gb2312"):
    try:
        text = raw.decode(enc)
        print("decoded_as", enc)
        break
    except Exception as e:
        print(enc, "fail", e)

if text is None:
    raise SystemExit("cannot decode index.html")

# strip BOM if present in text
if text.startswith("\ufeff"):
    text = text.lstrip("\ufeff")

p.write_text(text, encoding="utf-8", newline="\n")
check = p.read_bytes()
assert check[:3] != b"\xef\xbb\xbf"
assert "\u884c\u4eba\u901a\u9053\u8f90\u5c04\u76d1\u6d4b\u7cfb\u7edf".encode("utf-8") in check
assert b"alarmIcon" in check
print("utf8_ok", "cn_ok", "size", len(check))
