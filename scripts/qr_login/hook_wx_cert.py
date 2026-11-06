"""Serve the WeChat signing certificate to ShareSDK without touching the target APK.

The target app asks PackageManager for com.tencent.mm and compares the reported
signature to the literal recovered from its own ShareSDK copy. Re-signing the app
trips its native integrity check, so the comparison input is spoofed in
system_server instead: the app itself stays byte-identical to the published APK.

Usage:
    python -B scripts/qr_login/hook_wx_cert.py --device 127.0.0.1:16640
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import frida

ROOT = Path(__file__).resolve().parents[2]

SCRIPT = r"""
const certHex = %(cert_hex)s;
const packageName = %(package)s;

function hexToJavaBytes(hex) {
    const values = [];
    for (let i = 0; i < hex.length; i += 2) {
        let value = parseInt(hex.substr(i, 2), 16);
        if (value > 127) value -= 256;
        values.push(value);
    }
    return Java.array('byte', values);
}

Java.perform(function () {
    const Signature = Java.use('android.content.pm.Signature');
    const PMS = Java.use('com.android.server.pm.PackageManagerService');
    const spoofed = Signature.$new(hexToJavaBytes(certHex));
    let hits = 0;
    PMS.getPackageInfo.overload('java.lang.String', 'int', 'int').implementation = function (pkg, flags, userId) {
        const info = this.getPackageInfo(pkg, flags, userId);
        try {
            if (info !== null && pkg === packageName) {
                info.signatures.value = Java.array('android.content.pm.Signature', [spoofed]);
                hits += 1;
                if (hits <= 5 || hits %% 20 === 0) {
                    send({event: 'spoofed', pkg: pkg, flags: flags, userId: userId, count: hits});
                }
            }
        } catch (e) {
            send({event: 'spoof-failed', error: String(e)});
        }
        return info;
    };
    send({event: 'hook-installed', pkg: packageName, certBytes: certHex.length / 2,
          androidVersion: Java.androidVersion});
});
"""


def default_cert_json() -> Path:
    """Support both the analysis tree (assets/qr-login) and the published repo (assets)."""
    for candidate in (ROOT / "assets" / "wechat-cert.json",
                      ROOT / "assets" / "qr-login" / "wechat-cert.json"):
        if candidate.exists():
            return candidate
    return ROOT / "assets" / "wechat-cert.json"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", default="127.0.0.1:16640")
    parser.add_argument("--cert-json", type=Path, default=default_cert_json())
    parser.add_argument("--package", default="com.tencent.mm")
    parser.add_argument("--log", type=Path, default=ROOT / ".work/qr-login-20261107/hook-wx-cert.jsonl")
    parser.add_argument("--seconds", type=float, default=0.0, help="0 keeps running until interrupted")
    args = parser.parse_args()
    if not args.cert_json.exists():
        raise SystemExit(f"证书文件不存在: {args.cert_json}（用 --cert-json 指定，或用 extract_wechat_cert.py 生成）")

    cert = json.loads(args.cert_json.read_text(encoding="utf-8"))["cert_der_hex"]
    source = SCRIPT % {"cert_hex": json.dumps(cert), "package": json.dumps(args.package)}
    args.log.parent.mkdir(parents=True, exist_ok=True)

    def record(entry):
        with args.log.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry, ensure_ascii=False) + "\n")
        print(json.dumps(entry, ensure_ascii=False), flush=True)

    device = frida.get_device(args.device, timeout=10)
    process = device.get_process("system_server")
    session = device.attach(process.pid)

    def on_message(message, data):
        if message.get("type") == "send":
            record(message["payload"])
        else:
            record({"event": "script-error", "message": message})

    script = session.create_script(source)
    script.on("message", on_message)
    script.load()
    record({"event": "attached", "device": args.device, "pid": process.pid,
            "started": time.strftime("%Y-%m-%dT%H:%M:%S")})
    if args.seconds:
        time.sleep(args.seconds)
        session.detach()
        return
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        record({"event": "interrupted"})
    finally:
        session.detach()


if __name__ == "__main__":
    sys.exit(main())
