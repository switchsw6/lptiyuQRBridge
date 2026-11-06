"""Small binary-safe adb driver for the QR login verification runs."""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

ADB = r"C:\Program Files\platform-tools\adb.exe"
ROOT = Path(__file__).resolve().parents[2]
CASE = ROOT / ".work" / "qr-login-20261107"
DEFAULT_DEVICE = "127.0.0.1:16640"


def adb(device: str, *args: str, binary: bool = False):
    result = subprocess.run([ADB, "-s", device, *args], capture_output=True)
    if binary:
        return result.stdout, result
    return result.stdout.decode("utf-8", "replace") + result.stderr.decode("utf-8", "replace"), result


def shot(device: str, name: str) -> Path:
    CASE.mkdir(parents=True, exist_ok=True)
    remote = f"/sdcard/{name}.png"
    adb(device, "shell", "screencap", "-p", remote)
    local = CASE / f"{name}.png"
    adb(device, "pull", remote, str(local))
    adb(device, "shell", "rm", "-f", remote)
    return local


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", default=DEFAULT_DEVICE)
    parser.add_argument("action", choices=["shot", "tap", "text", "key", "swipe", "start", "stop",
                                          "pid", "packages", "install", "uninstall", "logcat",
                                          "reverse", "wake"])
    parser.add_argument("args", nargs="*")
    args = parser.parse_args()
    device = args.device
    if args.action == "shot":
        path = shot(device, args.args[0] if args.args else f"shot-{int(time.time())}")
        print(json.dumps({"png": str(path), "size": path.stat().st_size}))
    elif args.action == "tap":
        print(adb(device, "shell", "input", "tap", args.args[0], args.args[1])[0])
    elif args.action == "text":
        print(adb(device, "shell", "input", "text", args.args[0])[0])
    elif args.action == "key":
        print(adb(device, "shell", "input", "keyevent", args.args[0])[0])
    elif args.action == "swipe":
        print(adb(device, "shell", "input", "swipe", *args.args)[0])
    elif args.action == "start":
        print(adb(device, "shell", "am", "start", "-W", *args.args)[0])
    elif args.action == "stop":
        print(adb(device, "shell", "am", "force-stop", args.args[0])[0])
    elif args.action == "pid":
        out, _ = adb(device, "shell", "pidof", args.args[0])
        print(out.strip())
    elif args.action == "packages":
        print(adb(device, "shell", "pm", "list", "packages", *args.args)[0])
    elif args.action == "install":
        print(adb(device, "install", "-r", *args.args)[0])
    elif args.action == "uninstall":
        print(adb(device, "uninstall", args.args[0])[0])
    elif args.action == "logcat":
        print(adb(device, "logcat", "-d", *args.args)[0])
    elif args.action == "reverse":
        print(adb(device, "reverse", *args.args)[0])
    elif args.action == "wake":
        adb(device, "shell", "input", "keyevent", "224")
        print(adb(device, "shell", "wm", "size")[0])


if __name__ == "__main__":
    main()
