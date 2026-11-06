"""Dump the OpenSDK client checks that decide how the helper must identify itself."""
import sys
from pathlib import Path

from loguru import logger

logger.remove()

from androguard.core.dex import DEX  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
RECOVERY = ROOT / ".work" / "wechat-login-4.2.0" / "recovery"
OUT = ROOT / ".work" / "qr-login-20261107" / "wxapi-client-checks.txt"

METHODS = {"isWXAppInstalled", "isWXAppSupportAPI", "getWXAppSupportMaxAPI", "checkArgs", "sendReq"}

lines = []
for index in range(1, 9):
    path = RECOVERY / f"recovered{index}-verified.dex"
    if not path.exists():
        continue
    dex = DEX(path.read_bytes())
    for name in ("Lcom/tencent/mm/opensdk/openapi/WXApiImplV10;",
                 "Lcom/tencent/mm/opensdk/openapi/BaseWXApiImplV10;",
                 "Lcom/tencent/mm/opensdk/openapi/WXApiImplV10$1;"):
        if dex.get_class(name) is None:
            continue
        cls = dex.get_class(name)
        lines.append(f"\n######## {path.name} :: {name}")
        for method in cls.get_methods():
            if methods_filter := METHODS:
                if method.get_name() not in methods_filter:
                    continue
            lines.append(f"\n=== {method.get_name()}{method.get_descriptor()}")
            for ins in method.get_instructions():
                lines.append(f"    {ins.get_name()} {ins.get_output()}".rstrip())
    del dex

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text("\n".join(lines), encoding="utf-8")
print(f"saved -> {OUT} lines={len(lines)}", file=sys.stderr)
print("\n".join(lines[:200]))
