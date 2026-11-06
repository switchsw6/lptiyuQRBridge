"""One-click local deployment for lptiyuQRBridge (Windows).

Double-click run.cmd and follow the prompts: pick an emulator, everything else is
automatic — install check, adb reverse, frida-server, authorization service,
certificate hook, then it opens 步道乐跑's WeChat login page so you can scan.

Usage:
    run.cmd                          # interactive (recommended)
    run.cmd --device 127.0.0.1:16640
    run.cmd --stop                   # stop what this script started
"""
from __future__ import annotations

import argparse
import getpass
import json
import lzma
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".state"
PIDS = STATE / "deploy.pids.json"
FRIDA_VERSION = "16.7.19"
FRIDA_DIR = ROOT / "tools"
PORT = 18371
HELPER = "com.tencent.mm"
TARGET = "com.lptiyu.tanke"
APP_ID = "wx5a2e1ff396785475"
FRIDA_MIRRORS = (
    "https://github.com/frida/frida/releases/download/{version}/frida-server-{version}-android-{abi}.xz",
    "https://ghproxy.net/https://github.com/frida/frida/releases/download/{version}/frida-server-{version}-android-{abi}.xz",
    "https://gh-proxy.com/https://github.com/frida/frida/releases/download/{version}/frida-server-{version}-android-{abi}.xz",
)
ADB_CANDIDATES = (
    r"C:\Program Files\platform-tools\adb.exe",
    r"C:\Program Files\Netease\MuMu\nx_main\adb.exe",
    r"C:\Program Files\Netease\MuMu\nx_device\12.0\shell\adb.exe",
    r"C:\Program Files\Netease\MuMu\nx_device\15.0\shell\adb.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe"),
)

try:  # keep console output readable on legacy code pages
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
except Exception:  # noqa: BLE001
    pass


def say(message: str = "") -> None:
    print(message, flush=True)


def fail(message: str):
    print(f"\n[x] {message}", flush=True)
    raise SystemExit(1)


def run(command, check=True):
    result = subprocess.run(command, capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    if check and result.returncode:
        fail(f"命令失败({result.returncode}): {' '.join(str(p) for p in command)}\n"
             f"{result.stderr or result.stdout}")
    return result


def adb_shell(adb: str, device: str, *args: str, check: bool = True) -> str:
    return run([adb, "-s", device, "shell", *args], check=check).stdout


# ---------------------------------------------------------------- adb / devices

def find_adb(explicit: str | None) -> str:
    if explicit:
        if Path(explicit).exists():
            return explicit
        fail(f"指定的 adb 不存在: {explicit}")
    for candidate in ADB_CANDIDATES:
        if candidate and Path(candidate).exists():
            return candidate
    from shutil import which
    found = which("adb")
    if found:
        return found
    fail("找不到 adb：装一个 Android platform-tools，或把 adb 加入 PATH 后重试")
    return ""


def list_devices(adb: str):
    devices = []
    for line in run([adb, "devices", "-l"]).stdout.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 2 or parts[1] != "device":
            continue
        info = {"id": parts[0], "model": "", "android": ""}
        for part in parts[2:]:
            if part.startswith("model:"):
                info["model"] = part.split(":", 1)[1]
        info["android"] = adb_shell(adb, info["id"], "getprop", "ro.build.version.release",
                                    check=False).strip()
        info["emulator"] = is_emulator(info["id"])
        devices.append(info)
    # emulators first: this tool is meant for emulators, physical phones are listed after
    devices.sort(key=lambda item: (not item["emulator"], item["id"]))
    return devices


def is_emulator(device_id: str) -> bool:
    return device_id.startswith(("emulator-", "127.0.0.1:", "localhost:"))


def pick_device(adb: str, explicit: str | None) -> str:
    devices = list_devices(adb)
    if explicit:
        if explicit not in [item["id"] for item in devices]:
            fail(f"设备 {explicit} 未连接。当前: {[item['id'] for item in devices] or '无'}")
        return explicit
    if not devices:
        fail("没检测到设备：先打开模拟器，等桌面出来后重跑 run.cmd")
    say(f"检测到 {len(devices)} 台设备：")
    for index, item in enumerate(devices, 1):
        kind = "模拟器" if item["emulator"] else "真机"
        label = f"Android {item['android']}" if item["android"] else ""
        say(f"  {index}) {item['id']:<22} {item['model']:<16} {kind}  {label}")
    if len(devices) == 1:
        say(f"只有一台，直接使用 {devices[0]['id']}")
        return devices[0]["id"]
    try:
        raw = input("选择设备序号 [1]: ").strip() or "1"
    except EOFError:  # non-interactive shell: fall back to the first device
        raw = "1"
        say("（非交互环境，默认 1）")
    try:
        return devices[int(raw) - 1]["id"]
    except (ValueError, IndexError):
        fail("序号无效")
    return ""


# ---------------------------------------------------------------- local files

def find_apk(explicit: str | None) -> Path:
    if explicit:
        path = Path(explicit)
        if not path.exists():
            fail(f"指定的 APK 不存在: {path}")
        return path
    candidates = sorted((ROOT / "release").glob("*.apk")) if (ROOT / "release").exists() else []
    if not candidates:
        fail("release 目录里没有 APK：先跑 scripts/build_qr_bridge.py")
    return candidates[-1]


def find_local_target_apk() -> Path | None:
    """Optional local copy of 步道乐跑 so a fresh emulator can be set up in one run."""
    for folder in (ROOT / "app", ROOT):
        if not folder.is_dir():
            continue
        for candidate in sorted(folder.glob("*.apk")):
            name = candidate.name
            if any(mark in name for mark in ("lptiyuQRBridge", "LepaoQRBridge", "扫码步道乐跑")):
                continue
            if "步道乐跑" in name or "lepao" in name.lower() or "tanke" in name.lower():
                return candidate
    return None


def expected_version(apk: Path) -> int | None:
    info = apk.parent / "build-info.json"
    if info.exists():
        try:
            return int(json.loads(info.read_text(encoding="utf-8"))["version_code"])
        except Exception:  # noqa: BLE001
            return None
    from shutil import which
    aapt2 = which("aapt2")
    if aapt2:
        result = run([aapt2, "dump", "badging", str(apk)], check=False)
        for line in result.stdout.splitlines():
            if line.startswith("package:") and "versionCode='" in line:
                return int(line.split("versionCode='")[1].split("'")[0])
    return None


def installed_version(adb: str, device: str, package: str) -> tuple[int | None, str]:
    dump = adb_shell(adb, device, "dumpsys", "package", package, check=False)
    code, name = None, ""
    for line in dump.splitlines():
        stripped = line.strip()
        if stripped.startswith("versionCode="):
            code = int(stripped.split("=")[1].split()[0])
        elif stripped.startswith("versionName="):
            name = stripped.split("=", 1)[1].strip()
    return code, name


def installed_apk_size(adb: str, device: str, package: str) -> int | None:
    """0-length when the package is absent; the size identifies our helper vs real WeChat."""
    output = adb_shell(adb, device, "pm", "path", package, check=False)
    for line in output.splitlines():
        if not line.startswith("package:"):
            continue
        remote = line.split(":", 1)[1].strip()
        raw = adb_shell(adb, device, "stat", "-c", "%s", remote, check=False).strip()
        if raw.isdigit():
            return int(raw)
    return 0


CRED_HOME = Path(os.environ.get("APPDATA") or Path.home()) / "lptiyuQRBridge"


def apk_token(apk: Path) -> str:
    with zipfile.ZipFile(apk) as archive:
        return json.loads(archive.read("assets/bridge.json").decode("utf-8"))["bridge_token"]


def remember(secret: str, token: str) -> Path:
    """Store the pair under %APPDATA% so later runs never ask again."""
    CRED_HOME.mkdir(parents=True, exist_ok=True)
    path = CRED_HOME / "credentials.json"
    path.write_text(json.dumps({"app_secret": secret, "bridge_token": token}, indent=2),
                    encoding="utf-8")
    if os.name == "nt":
        subprocess.run(["icacls", str(path), "/inheritance:r",
                        "/grant:r", f"{os.environ.get('USERNAME', 'user')}:F"], capture_output=True)
    return path


def credential_files() -> list[Path]:
    """Every place a previously used credential pair may live, newest first."""
    found: list[Path] = []
    found.append(ROOT / "credentials.private.json")
    found.append(CRED_HOME / "credentials.json")
    for base in [ROOT, *list(ROOT.parents)[:3]]:
        work = base / ".work"
        if work.is_dir():
            found.extend(sorted(work.glob("*/credentials.private.json"),
                                key=lambda item: item.stat().st_mtime, reverse=True))
    unique, seen = [], set()
    for path in found:
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        unique.append(path)
    return unique


def secret_from_dex(path: Path) -> str | None:
    """Pull the AppSecret literal out of a recovered DEX (const-string adjacency)."""
    import struct
    data = path.read_bytes()
    if not data.startswith(b"dex\n"):
        return None
    string_ids_size, string_ids_off = struct.unpack_from("<II", data, 0x38)
    if not string_ids_size or string_ids_off + string_ids_size * 4 > len(data):
        return None
    offsets = struct.unpack_from(f"<{string_ids_size}I", data, string_ids_off)

    def read_uleb(position: int) -> tuple[int, int]:
        result = shift = 0
        while True:
            byte = data[position]
            position += 1
            result |= (byte & 0x7F) << shift
            if not byte & 0x80:
                return result, position
            shift += 7

    def string_at(offset: int) -> str | None:
        if not offset or offset >= len(data):
            return None
        _, start = read_uleb(offset)
        end = data.find(b"\x00", start)
        if end < 0:
            return None
        try:
            return data[start:end].decode("utf-8")
        except UnicodeDecodeError:
            return None

    appsecret_indices = []
    hex32 = {}
    for index, offset in enumerate(offsets):
        value = string_at(offset)
        if value is None:
            continue
        if value == "AppSecret":
            appsecret_indices.append(index)
        elif len(value) == 32 and all(c in "0123456789abcdef" for c in value):
            hex32[index] = value
    if not appsecret_indices or not hex32:
        return None

    # Collect every const-string / const-string-jumbo reference, then look for a hex32
    # literal right after the "AppSecret" key (0x1a = 16-bit index, 0x1b = jumbo).
    references = []
    for match in re.finditer(b"[\x1a\x1b]", data):
        position = match.start()
        if data[position] == 0x1A:
            if position + 4 > len(data):
                continue
            references.append((position, struct.unpack_from("<H", data, position + 2)[0]))
        else:
            if position + 6 > len(data):
                continue
            references.append((position, struct.unpack_from("<I", data, position + 2)[0]))

    anchors = [position for position, index in references if index in appsecret_indices]
    for anchor in anchors:
        for position, index in references:
            if position <= anchor:
                continue
            if position - anchor > 96:
                break
            if index in hex32:
                return hex32[index]
    return None


def validate_secret(secret: str) -> bool:
    body = json.dumps({"appid": APP_ID, "secret": secret, "grant_type": "client_credential",
                       "force_refresh": False}).encode()
    request = urllib.request.Request("https://api.weixin.qq.com/cgi-bin/stable_token", data=body,
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read())
        return bool(payload.get("access_token"))
    except Exception:  # noqa: BLE001
        return False


def resolve_secret(apk: Path) -> tuple[str, str]:
    """Return (secret, source description). Never asks when a local copy exists."""
    for path in credential_files():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            secret = data.get("app_secret", "")
        except Exception:  # noqa: BLE001
            continue
        if len(secret) >= 16:
            return secret, f"复用 {path}"
    for base in [ROOT, *list(ROOT.parents)[:3]]:
        recovery = base / ".work"
        if not recovery.is_dir():
            continue
        for dex in sorted(recovery.glob("*/recovery/recovered*-verified.dex")):
            candidate = secret_from_dex(dex)
            if candidate and validate_secret(candidate):
                return candidate, f"从 {dex.name} 里提取并已向微信验证"
    return "", ""


def prepare_credentials(explicit: str | None, apk: Path, app_secret: str | None):
    token = apk_token(apk)
    if explicit:
        path = Path(explicit)
        if not path.exists():
            fail(f"指定的凭据文件不存在: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        return remember(data["app_secret"], token), token

    secret, source = resolve_secret(apk) if app_secret is None else (app_secret, "--app-secret")
    if not secret:
        say("本机没有可用的 AppSecret（缓存、工程 .work、已恢复 DEX 都没找到）")
        try:
            secret = getpass.getpass("只需输入这一次，之后自动记住: ").strip()
        except EOFError:
            fail("需要一次 AppSecret 才能向微信换二维码；可用 --app-secret 传入")
        if len(secret) < 16:
            fail("AppSecret 长度异常（应为 32 位）")
        source = "手工输入（已记住）"
    path = remember(secret, token)
    say(f"凭据：{source}")
    return path, token


# ---------------------------------------------------------------- frida pieces

def frida_server_pid(adb: str, device: str) -> str:
    for line in adb_shell(adb, device, "ps", "-A", check=False).splitlines():
        if "frida-server" in line:
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                return parts[1]
    return ""


def python_with_frida16() -> str | None:
    candidates = [sys.executable]
    for relative in ("venv/Scripts/python.exe", ".venv/Scripts/python.exe"):
        candidate = ROOT / relative
        if candidate.exists():
            candidates.append(str(candidate))
    from shutil import which
    for name in ("python3", "python"):
        found = which(name)
        if found:
            candidates.append(found)
    for candidate in dict.fromkeys(candidates):
        result = run([candidate, "-c", "import frida;print(frida.__version__)"], check=False)
        if result.returncode == 0 and result.stdout.strip().startswith("16."):
            return candidate
    return None


def ensure_frida_client() -> str:
    found = python_with_frida16()
    if found:
        return found
    venv = ROOT / "venv"
    venv_python = venv / "Scripts/python.exe"
    say("本机没有 frida 16.x，正在 venv 里安装（frida 17 已移除 Java bridge）")
    if not venv_python.exists():
        run([sys.executable, "-m", "venv", str(venv)])
    install = run([str(venv_python), "-m", "pip", "install", "--quiet",
                   "--disable-pip-version-check", f"frida=={FRIDA_VERSION}"], check=False)
    if install.returncode:
        fail("安装 frida 失败（检查网络）：\n" + (install.stderr or install.stdout)[-800:])
    return str(venv_python)


def ensure_frida_server(adb: str, device: str) -> None:
    if frida_server_pid(adb, device):
        return
    abi = adb_shell(adb, device, "getprop", "ro.product.cpu.abilist").strip()
    arch = "x86_64" if "x86_64" in abi else "arm64" if "arm64" in abi else "arm"
    FRIDA_DIR.mkdir(exist_ok=True)
    local = FRIDA_DIR / f"frida-server-{FRIDA_VERSION}-android-{arch}"
    if not local.exists():
        say(f"下载 frida-server {FRIDA_VERSION} ({arch})，约 33 MB …")
        errors = []
        for template in FRIDA_MIRRORS:
            url = template.format(version=FRIDA_VERSION, abi=arch)
            try:
                with urllib.request.urlopen(url, timeout=180) as response:
                    local.write_bytes(lzma.decompress(response.read()))
                break
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{url} -> {type(exc).__name__}")
        else:
            fail("frida-server 下载失败，可手动放到 tools/：\n  " + "\n  ".join(errors))
    remote = "/data/local/tmp/frida-server"
    run([adb, "-s", device, "push", str(local), remote])
    adb_shell(adb, device, "chmod", "755", remote)
    adb_shell(adb, device, "-c", f"nohup {remote} -D >/data/local/tmp/frida.log 2>&1 &", check=False)
    for _ in range(20):
        time.sleep(0.5)
        if frida_server_pid(adb, device):
            return
    device_log = adb_shell(adb, device, "cat", "/data/local/tmp/frida.log", check=False).strip()
    fail("frida-server 启动失败：\n" + (device_log or "(无输出)"))


# ---------------------------------------------------------------- processes

def start_detached(python: str, args: list[str], log_path: Path) -> subprocess.Popen:
    STATE.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    stream = log_path.open("a", encoding="utf-8")
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    return subprocess.Popen([python, "-B", *args], cwd=str(ROOT), stdout=stream,
                            stderr=subprocess.STDOUT, creationflags=flags,
                            env={**os.environ, "PYTHONIOENCODING": "utf-8"})


def tail(path: Path, lines: int = 10) -> str:
    if not path.exists():
        return "(无输出)"
    return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])


def health_ok(token: str) -> bool:
    request = urllib.request.Request(f"http://127.0.0.1:{PORT}/health",
                                     headers={"X-Bridge-Token": token})
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            return json.loads(response.read()).get("status") == "ready"
    except Exception:  # noqa: BLE001
        return False


def port_in_use() -> bool:
    with socket.socket() as probe:
        return probe.connect_ex(("127.0.0.1", PORT)) == 0


def load_pids() -> dict:
    return json.loads(PIDS.read_text(encoding="utf-8")) if PIDS.exists() else {}


def save_pids(data: dict) -> None:
    STATE.mkdir(exist_ok=True)
    PIDS.write_text(json.dumps(data, indent=2), encoding="utf-8")


def stop_all() -> int:
    data = load_pids()
    stopped = []
    for name, pid in data.items():
        if subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                          capture_output=True).returncode == 0:
            stopped.append(name)
    PIDS.unlink(missing_ok=True)
    say("已停止: " + (", ".join(stopped) if stopped else "没有由本脚本启动的组件"))
    return 0


# ---------------------------------------------------------------- app launch

def bring_app_forward(adb: str, device: str) -> None:
    """Restart 步道乐跑 so ShareSDK re-checks the WeChat client, then leave the UI alone.

    The app caches "wechat client valid" in-process; an instance started before the
    certificate hook would keep reporting 微信未安装. No taps happen here on purpose:
    the user clicks 微信登录 themselves.
    """
    adb_shell(adb, device, "am", "force-stop", TARGET, check=False)
    time.sleep(1)
    adb_shell(adb, device, "am", "start", "-n",
              f"{TARGET}/.activities.splash.SplashActivity", check=False)
    time.sleep(3)


# ---------------------------------------------------------------- main flow

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--device")
    parser.add_argument("--adb")
    parser.add_argument("--apk")
    parser.add_argument("--credentials")
    parser.add_argument("--app-secret")
    parser.add_argument("--force-install", action="store_true")
    parser.add_argument("--stop", action="store_true")
    args = parser.parse_args()

    if args.stop:
        return stop_all()

    say("=" * 60)
    say(" lptiyuQRBridge 一键部署")
    say("=" * 60)
    adb = find_adb(args.adb)
    device = pick_device(adb, args.device)
    apk = find_apk(args.apk)
    credentials, token = prepare_credentials(args.credentials, apk, args.app_secret)
    saved = load_pids()

    say(f"\n[1/6] 设备 {device}")
    run([adb, "-s", device, "root"], check=False)
    time.sleep(2)
    run([adb, "-s", device, "reverse", f"tcp:{PORT}", f"tcp:{PORT}"])
    say("      端口环回就绪")

    say("[2/6] 检查 App")
    size = installed_apk_size(adb, device, HELPER)
    code, _ = installed_version(adb, device, HELPER)
    want = expected_version(apk)
    ours = bool(size) and size == apk.stat().st_size
    if size and not ours:
        fail(f"这台设备的 com.tencent.mm 是别的东西（{size / 1048576:.0f} MB，应该是真微信）。\n"
             "    本工具需要占用包名 com.tencent.mm，请换一台模拟器，或先卸载：\n"
             f"    adb -s {device} uninstall com.tencent.mm")
    if ours and not args.force_install and (want is None or (code or 0) >= want):
        say(f"      扫码步道乐跑 v{code}：已安装")
    else:
        say("      扫码步道乐跑：安装中 …")
        result = run([adb, "-s", device, "install", "-r", str(apk)], check=False)
        output = result.stdout + result.stderr
        if "Success" not in output:
            if ("INSTALL_FAILED_UPDATE_INCOMPATIBLE" in output
                    or "signatures do not match" in output):
                fail("设备上已有另一个 com.tencent.mm（可能是真微信）。\n"
                     f"    先卸载再重跑：adb -s {device} uninstall com.tencent.mm")
            fail("安装失败:\n" + output[-600:])
        say(f"      扫码步道乐跑 v{want or '?'}：已安装")

    target_code, target_name = installed_version(adb, device, TARGET)
    if target_code:
        say(f"      步道乐跑 {target_name or '?'}（versionCode {target_code}）：已安装")
    else:
        local_target = find_local_target_apk()
        if local_target is not None:
            say(f"      步道乐跑：安装中（{local_target.name}）…")
            run([adb, "-s", device, "install", "-r", str(local_target)], check=False)
            target_code, target_name = installed_version(adb, device, TARGET)
        if not target_code:
            fail("模拟器里没有步道乐跑。\n"
                 "    先装官方 4.2.0 安装包，再重跑 run.cmd：\n"
                 f"    adb -s {device} install -r \"步道乐跑_4.2.0.apk\"\n"
                 "    （也可以把任意 .apk 放进包里的 app\\ 目录，脚本会自动装上）")
        say(f"      步道乐跑 {target_name or '?'}：已安装")
    say("      → 两个 App 齐了，开始部署")

    say("[3/6] frida-server")
    ensure_frida_server(adb, device)
    say(f"      就绪（pid {frida_server_pid(adb, device)}）")

    say("[4/6] 授权服务")
    server_log, hook_log = STATE / "server.log", STATE / "hook.log"
    hook_events = STATE / "hook-events.jsonl"
    if health_ok(token):
        say("      已在运行，复用")
    else:
        if port_in_use():
            fail(f"端口 {PORT} 被别的程序占用，先关掉它")
        server = start_detached(sys.executable,
                                ["src/lepao_qr_bridge/server.py", "--credentials", str(credentials),
                                 "--state-dir", str(STATE / "server"), "--port", str(PORT)],
                                server_log)
        for _ in range(50):
            time.sleep(0.5)
            if health_ok(token):
                break
            if server.poll() is not None:
                fail("授权服务起不来：\n" + tail(server_log))
        else:
            fail("授权服务 25 秒内没就绪：\n" + tail(server_log))
        saved["server"] = server.pid
        say(f"      就绪（pid {server.pid}）")

    say("[5/6] 证书钩子")
    frida_python = ensure_frida_client()
    hook_events.unlink(missing_ok=True)
    hook = start_detached(frida_python,
                          ["scripts/qr_login/hook_wx_cert.py", "--device", device,
                           "--log", str(hook_events)], hook_log)
    for _ in range(60):
        time.sleep(0.5)
        if hook.poll() is not None:
            fail("钩子退出：\n" + tail(hook_log))
        if hook_events.exists() and "hook-installed" in hook_events.read_text(encoding="utf-8"):
            break
    else:
        fail("钩子 30 秒内没装好：\n" + tail(hook_log))
    saved["hook"] = hook.pid
    save_pids(saved)
    say(f"      就绪（pid {hook.pid}）")

    say("[6/6] 启动步道乐跑")
    bring_app_forward(adb, device)
    say("      已启动")
    say("")
    say("部署完成：现在可以点击微信登录进行扫码登录。")
    say("  步道乐跑 → 我的 → 点击登录 → 勾选协议 → 微信登录")
    say("  出现二维码后用手机微信扫码，并在手机上确认")
    say("")
    say("停止后台服务：stop.cmd")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        say("\n[!] 已取消")
        raise SystemExit(130)
