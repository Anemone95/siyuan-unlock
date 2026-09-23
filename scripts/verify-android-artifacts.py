#!/usr/bin/env python3
"""按 Gradle 输出元数据定位 APK，并校验包名、版本与发布签名。"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess


def command(*args):
    return subprocess.check_output(list(map(str, args)), stderr=subprocess.STDOUT, text=True)


def verify(source, sdk, version, fingerprint):
    if not re.fullmatch(r"[0-9a-fA-F]{64}", fingerprint):
        raise ValueError("ANDROID_SIGNING_SHA256 must contain a SHA-256 certificate fingerprint")
    tools = sdk / "build-tools/36.0.0"
    verified = []
    for flavor, package, suffix in [("googleplay", "org.b3log.siyuan", ""), ("appdev", "com.appdev.siyuan", "-appdev")]:
        output = source / "app/build/outputs/apk" / flavor / "release"
        metadata = json.loads((output / "output-metadata.json").read_text(encoding="utf-8"))
        if metadata["applicationId"] != package or len(metadata["elements"]) != 1:
            raise ValueError(f"Unexpected Gradle output for {flavor}: {metadata}")
        apk = (output / metadata["elements"][0]["outputFile"]).resolve()
        if not apk.is_relative_to(output.resolve()) or not apk.is_file() or not apk.stat().st_size:
            raise ValueError(f"Missing or invalid APK path: {apk}")
        badging = command(tools / "aapt", "dump", "badging", apk)
        if f"package: name='{package}'" not in badging or f"versionName='{version.removeprefix('v')}'" not in badging:
            raise ValueError(f"APK identity/version mismatch for {apk}: {badging}")
        certificates = command(tools / "apksigner", "verify", "--print-certs", apk)
        digests = re.findall(r"^Signer #\d+ certificate SHA-256 digest: ([0-9a-fA-F]+)", certificates, re.M)
        if {digest.lower() for digest in digests} != {fingerprint.lower()}:
            raise ValueError(f"APK signer mismatch for {apk}: {certificates}")
        print(f"Verified {package}: {apk.name}, SHA-256 {fingerprint.lower()}")
        verified.append((apk, f"siyuan-unlock-{version}-android-arm64{suffix}.apk"))
    destination = source.parent / "release-assets"
    destination.mkdir(exist_ok=True)
    for apk, name in verified:
        shutil.copy2(apk, destination / name)
    provenance = source.parent / "siyuan-build-inputs.json"
    record = json.loads(provenance.read_text(encoding="utf-8"))
    record["android_signer_sha256"] = fingerprint.lower()
    provenance.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--sdk", type=Path, required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    try:
        verify(args.source.resolve(), args.sdk.resolve(), args.version, os.environ["ANDROID_SIGNING_SHA256"])
    except subprocess.CalledProcessError as error:
        raise SystemExit(f"APK verification command failed: {error.output}") from None
