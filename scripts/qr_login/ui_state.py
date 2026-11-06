"""Dump the current UI hierarchy and list clickable / textual nodes."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ADB = r"C:\Program Files\platform-tools\adb.exe"
DEVICE = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1:16640"
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / ".work" / "qr-login-20261107" / "ui-current.xml"


def adb(*args):
    return subprocess.run([ADB, "-s", DEVICE, *args], capture_output=True)


adb("shell", "uiautomator", "dump", "/sdcard/ui.xml")
adb("pull", "/sdcard/ui.xml", str(OUT))
adb("shell", "rm", "-f", "/sdcard/ui.xml")
text = OUT.read_text(encoding="utf-8", errors="replace")

NODE = re.compile(r"<node ([^>]*?)/>")
ATTR = re.compile(r'([\w:-]+)="([^"]*)"')

rows = []
for match in NODE.finditer(text):
    attrs = dict(ATTR.findall(match.group(1)))
    label = attrs.get("text") or attrs.get("content-desc") or ""
    clickable = attrs.get("clickable") == "true"
    if not label and not clickable:
        continue
    rows.append({
        "text": label,
        "class": attrs.get("class", "").rsplit(".", 1)[-1],
        "id": attrs.get("resource-id", ""),
        "clickable": clickable,
        "bounds": attrs.get("bounds", ""),
        "pkg": attrs.get("package", ""),
    })

for row in rows:
    print(f"{row['pkg']:28s} {row['class']:14s} click={str(row['clickable']):5s} "
          f"{row['bounds']:24s} id={row['id']:40s} text={row['text'][:50]}")
print(f"\n{len(rows)} nodes -> {OUT}")
