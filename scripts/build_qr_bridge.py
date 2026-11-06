"""Build the ABI independent Android QR companion with the local Android SDK.

The helper app is signed locally and carries only the loopback bridge token. The
WeChat AppSecret stays in the ignored credentials file and is read by server.py.

Usage:
    python -B scripts/build_qr_bridge.py --toolchain <sdk-root> [--case <dir>]

Toolchain layout expected (as produced by the local Android SDK):
    <sdk-root>/bt35/android-15/{aapt2.exe,zipalign.exe,lib/d8.jar,lib/apksigner.jar}
    <sdk-root>/pf/android-11/android.jar
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_APPLICATION = ROOT / ".work/wechat-login-4.2.0/sdk-trace/sources/com/lptiyu/tanke/application/RunApplication.java"
PACKAGE = "com.tencent.mm"


def run(case: Path, label: str, command, cwd: Path | None = None):
    result = subprocess.run(command, capture_output=True, cwd=cwd)
    entry = {
        "label": label,
        "time_stamp": subprocess.run(["cmd", "/c", "echo", "%TIME%"], capture_output=True).stdout.decode(errors="replace").strip(),
        "command": [str(part) for part in command],
        "cwd": str(cwd) if cwd else None,
        "exit_status": result.returncode,
        "stdout": result.stdout.decode("utf-8", "replace"),
        "stderr": result.stderr.decode("utf-8", "replace"),
    }
    with (case / "build-events.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(json.dumps({k: entry[k] for k in ("label", "exit_status", "stderr")}, ensure_ascii=True), flush=True)
    if result.returncode:
        raise SystemExit(f"{label} failed with {result.returncode}")
    return entry


def cert_sha256(apk: Path, apksigner: list[str]) -> str:
    result = subprocess.run(apksigner + ["verify", "--print-certs", str(apk)], capture_output=True)
    text = result.stdout.decode("utf-8", "replace") + result.stderr.decode("utf-8", "replace")
    match = re.search(r"certificate SHA-256 digest: ([0-9a-f]+)", text)
    if not match:
        raise SystemExit("apksigner did not report a certificate digest")
    return match.group(1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--toolchain", type=Path, required=True)
    parser.add_argument("--case", type=Path, default=ROOT / ".work/qr-login-20261107")
    parser.add_argument("--recovered-application", type=Path, default=DEFAULT_APPLICATION)
    parser.add_argument("--out-dir", type=Path, default=ROOT / "dist/lepao-qr-login")
    args = parser.parse_args()

    case = args.case.resolve()
    case.mkdir(parents=True, exist_ok=True)
    build = case / "helper-build"
    if build.exists():
        shutil.rmtree(build)
    for folder in ("classes", "dex", "assets"):
        (build / folder).mkdir(parents=True, exist_ok=True)

    # aapt2 rejects non-ASCII absolute paths, so every build input is staged with
    # ASCII names inside the build directory and referenced relatively.
    toolchain = args.toolchain.resolve()
    bt = toolchain / "bt35/android-15"
    android_jar = toolchain / "pf/android-11/android.jar"
    source = ROOT / "src/lepao_qr_bridge/android"
    shim = source / "com/tencent/mm/plugin/base/stub/WXEntryActivity.java"
    activity = source / "com/lptiyu/qrbridge/hc/QRBridgeActivity.java"
    for needed in (bt / "aapt2.exe", bt / "zipalign.exe", bt / "lib/d8.jar",
                   bt / "lib/apksigner.jar", android_jar, shim, activity,
                   source / "AndroidManifest.xml"):
        if not needed.exists():
            raise SystemExit(f"missing build input: {needed}")
    shutil.copy2(android_jar, build / "android.jar")
    shutil.copy2(source / "AndroidManifest.xml", build / "AndroidManifest.xml")
    manifest_text = (source / "AndroidManifest.xml").read_text(encoding="utf-8")
    version_code = int(re.search(r'android:versionCode="(\d+)"', manifest_text).group(1))
    version_name = re.search(r'android:versionName="([^"]+)"', manifest_text).group(1)

    credentials = case / "credentials.private.json"
    if not credentials.exists():
        recovered = args.recovered_application.read_text(encoding="utf-8")
        match = re.search(r'put\("AppSecret",\s*"([^"]+)"\)', recovered)
        if not match:
            raise SystemExit("AppSecret not found in the recovered application")
        credentials.write_text(
            json.dumps({"app_secret": match.group(1), "bridge_token": secrets.token_urlsafe(32)}, indent=2),
            encoding="utf-8")
    private = json.loads(credentials.read_text(encoding="utf-8"))
    if len(private.get("bridge_token", "")) < 32:
        raise SystemExit("bridge_token in the credentials file is too short")
    (build / "assets/bridge.json").write_text(
        json.dumps({"bridge_token": private["bridge_token"]}), encoding="utf-8")

    keystore = case / "bridge-signing.p12"
    keystore_pass = "local-build-only"
    if not keystore.exists():
        run(case, "keytool", [
            "keytool", "-genkeypair", "-keystore", str(keystore), "-storetype", "PKCS12",
            "-storepass", keystore_pass, "-keypass", keystore_pass, "-alias", "bridge",
            "-keyalg", "RSA", "-keysize", "2048", "-validity", "3650",
            "-dname", "CN=Lepao QR Bridge, OU=local, O=local, C=CN"])

    run(case, "javac", [
        "javac", "-J-Duser.language=en", "-J-Duser.country=US", "-encoding", "UTF-8",
        "--release", "8", "-classpath", str(build / "android.jar"),
        "-d", str(build / "classes"), str(activity), str(shim)])
    run(case, "jar", ["jar", "cf", str(build / "classes.jar"), "-C", str(build / "classes"), "."])
    run(case, "d8", [
        "java", "-cp", str(bt / "lib/d8.jar"), "com.android.tools.r8.D8",
        "--lib", str(build / "android.jar"), "--min-api", "24",
        "--output", str(build / "dex"), str(build / "classes.jar")])
    run(case, "aapt2", [str(bt / "aapt2.exe"), "link", "-o", "base.apk", "-I", "android.jar",
                        "--manifest", "AndroidManifest.xml", "-A", "assets"], cwd=build)

    with zipfile.ZipFile(build / "base.apk", "a") as archive:
        archive.write(build / "dex/classes.dex", "classes.dex", compress_type=zipfile.ZIP_DEFLATED)
    run(case, "zipalign", [str(bt / "zipalign.exe"), "-p", "-f", "4",
                           "base.apk", "aligned.apk"], cwd=build)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    output = args.out_dir / "LepaoQRBridge-universal.apk"
    if output.exists():
        output.unlink()
    signer = ["java", "-jar", str(bt / "lib/apksigner.jar")]
    run(case, "sign", signer + ["sign", "--ks", str(keystore), "--ks-type", "PKCS12",
                                "--ks-pass", f"pass:{keystore_pass}", "--ks-key-alias", "bridge",
                                "--min-sdk-version", "24", "--v1-signing-enabled", "true",
                                "--v2-signing-enabled", "true", "--v3-signing-enabled", "true",
                                "--v4-signing-enabled", "false",
                                "--out", str(output), str(build / "aligned.apk")])
    run(case, "verify-signature", signer + ["verify", "--verbose", "--print-certs", str(output)])

    with zipfile.ZipFile(output) as archive:
        names = archive.namelist()
        native = [name for name in names if name.startswith("lib/")]
        if native:
            raise SystemExit(f"unexpected native libraries: {native}")
        dex_present = [name for name in names if name.endswith(".dex")]
        if not dex_present:
            raise SystemExit("no dex inside the helper apk")
        embedded = json.loads(archive.read("assets/bridge.json").decode("utf-8"))
        if embedded.get("bridge_token") != private["bridge_token"]:
            raise SystemExit("embedded bridge token does not match the credentials file")
        if private["app_secret"].encode() in archive.read("assets/bridge.json"):
            raise SystemExit("app secret leaked into the helper apk")
        manifest = archive.read("AndroidManifest.xml")

    record = {
        "apk": str(output),
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "size": output.stat().st_size,
        "package": PACKAGE,
        "version_code": version_code,
        "version_name": version_name,
        "certificate_sha256": cert_sha256(output, signer),
        "keystore": str(keystore),
        "bridge_token_sha256": hashlib.sha256(private["bridge_token"].encode()).hexdigest(),
        "native_libraries": [],
        "architectures": ["arm64-v8a", "x86_64"],
        "dex_entries": dex_present,
        "manifest_entry_bytes": len(manifest),
        "runtime_tested": [
            "127.0.0.1:16640 install and launch",
            "127.0.0.1:16640 auth request intent received from com.lptiyu.tanke",
            "127.0.0.1:16640 WeChat QR authorization completed with a phone scan",
        ],
        "credentials": str(credentials),
    }
    (case / "helper-build-result.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    # Consumed by scripts/deploy_local.py to decide whether an install is needed.
    (output.parent / "build-info.json").write_text(json.dumps({
        "apk": output.name, "version_code": version_code, "version_name": version_name,
        "sha256": record["sha256"], "package": PACKAGE,
    }, indent=2), encoding="utf-8")
    print(json.dumps(record, ensure_ascii=True, indent=2))
    print("\nReminder: run `adb reverse tcp:18371 tcp:18371` before launching the helper.",
          file=sys.stderr)


if __name__ == "__main__":
    main()


