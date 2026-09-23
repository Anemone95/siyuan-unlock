#!/usr/bin/env python3
"""校验发布来源，创建或复用同一组源码对应的草稿。"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

MARKER = "<!-- siyuan-build-inputs: "


def inputs(version, tag, source, unlock, ios, android, package_version, android_signer):
    if version != "v" + package_version or not tag.startswith(version + "-"):
        raise ValueError("Version must match package.json; use a distinct personal release tag")
    if (not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}", tag)
            or subprocess.run(["git", "check-ref-format", "refs/tags/" + tag]).returncode):
        raise ValueError("Release tag must be valid for both Git and the container registry")
    commits = {"source_commit": source, "unlock_commit": unlock, "ios_commit": ios, "android_commit": android}
    if not all(re.fullmatch(r"[0-9a-fA-F]{40}", value) for value in commits.values()):
        raise ValueError("All source references must be full commit SHAs")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", android_signer):
        raise ValueError("Android signing certificate must have a SHA-256 fingerprint")
    return {"version": package_version, "release_tag": tag,
            "android_signer_sha256": android_signer.lower(),
            **{key: value.lower() for key, value in commits.items()}}


def release_body(record):
    return (f"Source: {record['source_commit']}\n\n"
            f"Unlock patches: appdev/siyuan-unlock@{record['unlock_commit']}\n\n"
            f"iOS: Anemone95/siyuan-ios@{record['ios_commit']}\n\n"
            f"Android: siyuan-note/siyuan-android@{record['android_commit']}\n\n"
            + MARKER + json.dumps(record, sort_keys=True) + " -->\n")


def verify_draft(release, record):
    markers = [line for line in (release.get("body") or "").splitlines() if line.startswith(MARKER)]
    expected = MARKER + json.dumps(record, sort_keys=True) + " -->"
    if (not release.get("draft") or release.get("target_commitish") != record["source_commit"]
            or release.get("tag_name") != record["release_tag"] or markers != [expected]):
        raise ValueError("Existing release belongs to different inputs or has already been published")


def api(path, payload=None, missing_ok=False):
    request = Request("https://api.github.com/" + path,
                      data=None if payload is None else json.dumps(payload).encode(),
                      headers={"Authorization": "Bearer " + os.environ["GH_TOKEN"],
                               "Accept": "application/vnd.github+json", "User-Agent": "siyuan-personal-release",
                               "Content-Type": "application/json"})
    try:
        with urlopen(request) as response:
            return json.load(response)
    except HTTPError as error:
        if missing_ok and error.code == 404:
            return None
        raise RuntimeError(f"GitHub API returned HTTP {error.code} for {path}") from None


def find_release(prefix, tag):
    # 按标签查询接口只返回已发布版本；草稿通过有权限的发布列表查找。
    matches = []
    page = 1
    while True:
        releases = api(prefix + f"releases?per_page=100&page={page}")
        matches.extend(release for release in releases if release["tag_name"] == tag)
        if len(releases) < 100:
            break
        page += 1
    if len(matches) > 1:
        raise ValueError("Multiple releases use this tag; resolve the duplicate drafts first")
    return matches[0] if matches else None


def ensure_draft(repo, record, create=True):
    prefix = f"repos/{repo}/"
    tag = quote(record["release_tag"], safe="")
    reference = api(prefix + "git/ref/tags/" + tag, missing_ok=True)
    if reference:
        target = reference["object"]
        while target["type"] == "tag":
            target = api(prefix + "git/tags/" + target["sha"])["object"]
        if target["type"] != "commit" or target["sha"] != record["source_commit"]:
            raise ValueError("Existing tag points to a different source commit")
    release = find_release(prefix, record["release_tag"])
    if release:
        verify_draft(release, record)
        return release
    if not create:
        raise ValueError("Expected release draft is missing")
    release = api(prefix + "releases", {"tag_name": record["release_tag"],
                  "target_commitish": record["source_commit"], "name": record["release_tag"],
                  "body": release_body(record), "draft": True})
    verify_draft(release, record)
    return release


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    version = json.loads((root / "app/package.json").read_text(encoding="utf-8"))["version"]
    defaults = json.loads((root / "scripts/personal-build-inputs.json").read_text(encoding="utf-8"))
    record = inputs(os.environ["BUILD_VERSION"], os.environ["RELEASE_TAG"], os.environ["GITHUB_SHA"],
                    os.environ.get("UNLOCK_REF") or defaults["unlock_commit"],
                    os.environ.get("IOS_REF") or defaults["ios_commit"],
                    os.environ.get("ANDROID_REF") or defaults["android_commit"],
                    version, os.environ["ANDROID_SIGNING_SHA256"])
    result = ensure_draft(os.environ["GITHUB_REPOSITORY"], record, create=not args.verify_only)
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
            for name in ["unlock", "ios", "android"]:
                stream.write(f"{name}_ref={record[name + '_commit']}\n")
    print(f"Verified release draft {result['id']} for {record['source_commit']}")
