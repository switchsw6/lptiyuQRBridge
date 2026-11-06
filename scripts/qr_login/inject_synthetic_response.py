"""Send a synthetic WeChat auth response to the target app through the bridge process.

This is an isolated contract check for the callback that the helper builds: the
checksum, the extras and the code extraction are exercised with a synthetic
authorization code. WeChat rejects that code during the token exchange, so the
business login is expected to stop there; the point is to prove the app accepts
the response format produced by src/lepao_qr_bridge/android/WXEntryActivity.java.

Usage:
    python -B scripts/qr_login/inject_synthetic_response.py --device 127.0.0.1:16640 \
        --code SYNTHETIC-CODE-000
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import frida

ROOT = Path(__file__).resolve().parents[2]
APP_ID = "wx5a2e1ff396785475"
TARGET = ("com.lptiyu.tanke", "com.lptiyu.tanke.wxapi.WXEntryActivity")

SCRIPT = r"""
Java.perform(function () {
    var Intent = Java.use('android.content.Intent');
    var Bundle = Java.use('android.os.Bundle');
    var ActivityThread = Java.use('android.app.ActivityThread');
    var bytes = Java.array('byte', %(checksum_bytes)s);
    // Explicit putXxx calls keep Java types exact: putExtra(String, byte) would
    // otherwise be selected for small integer literals and the handler would read
    // the default 0 for _wxapi_command_type.
    var extras = Bundle.$new();
    extras.putString('wx_token_key', 'com.tencent.mm.openapi.token');
    extras.putString('_mmessage_appPackage', 'com.tencent.mm');
    extras.putString('_mmessage_content', %(content)s);
    extras.putInt('_mmessage_sdkVersion', 638058496);
    extras.putByteArray('_mmessage_checksum', bytes);
    extras.putInt('_wxapi_command_type', 1);
    extras.putInt('_wxapi_baseresp_errcode', 0);
    extras.putString('_wxapi_baseresp_transaction', 'synthetic-transaction');
    extras.putString('_wxapi_sendauth_resp_token', %(code)s);
    extras.putString('_wxapi_sendauth_resp_state', 'sharesdk_wechat_auth');
    extras.putString('_wxapi_sendauth_resp_url', %(url)s);
    extras.putBoolean('_wxapi_sendauth_resp_auth_result', true);
    extras.putString('_wxapi_sendauth_resp_lang', 'zh_CN');
    extras.putString('_wxapi_sendauth_resp_country', 'CN');
    var intent = Intent.$new();
    intent.setClassName(%(target_pkg)s, %(target_cls)s);
    intent.addFlags(268435456);
    intent.putExtras(extras);
    var thread = ActivityThread.currentActivityThread();
    var context = thread.currentApplication();
    if (context === null) {
        context = thread.getSystemContext();
    }
    context.startActivity(intent);
    send({event: 'intent-dispatched', component: %(target_pkg)s + '/' + %(target_cls)s,
          callerProcess: ActivityThread.currentProcessName()});
});
"""


def checksum(content: str, package_name: str, sdk_version: int) -> bytes:
    """Mirror of com.tencent.mm.opensdk.utils.b / ShareSDK WechatCore checksum."""
    value = (content or "") + str(sdk_version) + package_name + "mMcShCsTr"
    digest = hashlib.md5(value[1:9].encode("utf-8")).digest()
    return digest.hex().encode("ascii")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", default="127.0.0.1:16640")
    parser.add_argument("--code", default="SYNTHETICCODE0001")
    parser.add_argument("--process", default="com.tencent.mm")
    parser.add_argument("--log", type=Path, default=ROOT / ".work/qr-login-20261107/synthetic-response.jsonl")
    args = parser.parse_args()

    content = f"weixin://sendresp?appid={APP_ID}"
    digest = checksum(content, "com.tencent.mm", 638058496)
    url = f"weixin://oauth?code={args.code}&state=sharesdk_wechat_auth"
    source = SCRIPT % {
        "checksum_bytes": json.dumps(list(digest)),
        "target_pkg": json.dumps(TARGET[0]),
        "target_cls": json.dumps(TARGET[1]),
        "content": json.dumps(content),
        "code": json.dumps(args.code),
        "url": json.dumps(url),
    }

    device = frida.get_device(args.device, timeout=10)
    try:
        pid = device.get_process(args.process).pid
    except frida.ProcessNotFoundError:
        # frida 16 sometimes omits secondary app processes on MuMu; fall back to adb.
        import subprocess
        adb = r"C:\Program Files\platform-tools\adb.exe"
        out = subprocess.run([adb, "-s", args.device, "shell", "pidof", args.process],
                             capture_output=True, text=True).stdout.split()
        if not out:
            raise SystemExit(f"{args.process} is not running on {args.device}")
        pid = int(out[-1])
    session = device.attach(pid)
    messages = []

    def on_message(message, data):
        messages.append(message)

    script = session.create_script(source)
    script.on("message", on_message)
    script.load()
    time.sleep(3)
    session.detach()

    record = {
        "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "device": args.device,
        "sender_process": args.process, "sender_pid": pid,
        "target": f"{TARGET[0]}/{TARGET[1]}",
        "content": content,
        "checksum_hex": digest.decode(),
        "code": args.code,
        "url": url,
        "messages": messages,
        "synthetic": True,
    }
    args.log.parent.mkdir(parents=True, exist_ok=True)
    with args.log.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(json.dumps(record, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

