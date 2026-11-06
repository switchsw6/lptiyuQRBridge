"""Extract the WeChat signing certificate literal from the recovered ShareSDK handler."""
import hashlib
import json
import re
from pathlib import Path

from loguru import logger

logger.remove()

from androguard.core.dex import DEX  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
RECOVERY = ROOT / ".work" / "wechat-login-4.2.0" / "recovery"
OUT = ROOT / "assets" / "qr-login" / "wechat-cert.json"

dex_path = RECOVERY / "recovered1-verified.dex"
dex = DEX(dex_path.read_bytes())
cls = dex.get_class("Lcn/sharesdk/wechat/utils/j$4;")
literals = []
for method in cls.get_methods():
    if method.get_name() != "onResponse":
        continue
    for instruction in method.get_instructions():
        if instruction.get_name() in ("const-string", "const-string/jumbo"):
            literals.append(instruction.get_output().split()[-1].strip('"'))

candidates = [value for value in literals if re.fullmatch(r"[0-9a-f]{1000,}", value)]
if len(candidates) != 1:
    raise SystemExit(f"expected exactly one certificate literal, found {len(candidates)}")
cert_hex = candidates[0]
record = {
    "source_dex": str(dex_path.relative_to(ROOT)),
    "source_class": "Lcn/sharesdk/wechat/utils/j$4;",
    "source_method": "onResponse(Lcom/mob/tools/utils/DH$DHResponse;)V",
    "purpose": "ShareSDK compares PackageInfo signatures of com.tencent.mm to this DER hex",
    "cert_der_hex": cert_hex,
    "cert_der_bytes": len(bytes.fromhex(cert_hex)),
    "cert_sha256": hashlib.sha256(bytes.fromhex(cert_hex)).hexdigest(),
}
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(record, indent=2), encoding="utf-8")
print(json.dumps({k: v for k, v in record.items() if k != "cert_der_hex"}, indent=2))
