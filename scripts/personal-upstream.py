#!/usr/bin/env python3
"""按官方正式 Release 的 tag 合并源码，并触发固定提交的个人发布。"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

UPSTREAM = "siyuan-note/siyuan"
REPOSITORY = "Anemone95/siyuan-unlock"


def gh(*args):
    return subprocess.check_output(["gh", *args], text=True)


def api(path):
    return json.loads(gh("api", path))


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def version_number(tag):
    if not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
        raise ValueError(f"Expected a stable version tag, got {tag}")
    return tuple(map(int, tag[1:].split(".")))


def next_release(release, existing, refs, current_version):
    if release["draft"] or release["prerelease"]:
        return None
    version = release["tag_name"]
    number = version_number(version)
    if any(item["tag_name"].startswith(version + "-") for item in existing):
        return None
    if number < version_number("v" + current_version):
        raise ValueError("Upstream release is older than the current source version")
    tag = version + "-unlock.1"
    if any(item["ref"] == "refs/tags/" + tag for item in refs):
        return None
    return version, tag


def tag_commit(repository, tag):
    target = api(f"repos/{repository}/git/ref/tags/{tag}")["object"]
    while target["type"] == "tag":
        target = api(f"repos/{repository}/git/tags/{target['sha']}")["object"]
    if target["type"] != "commit":
        raise ValueError(f"Release tag does not resolve to a commit: {repository}@{tag}")
    return target["sha"]


def merge_tag(root, upstream_url, version, expected_commit, android_commit):
    if git(root, "status", "--porcelain"):
        raise ValueError("Run upstream synchronization in a clean checkout")
    git(root, "fetch", "--no-tags", upstream_url, f"refs/tags/{version}:refs/tags/{version}")
    if git(root, "rev-parse", version + "^{commit}") != expected_commit:
        raise ValueError("Upstream tag changed after release detection")
    git(root, "merge", "--no-ff", "-m", f":twisted_rightwards_arrows: Merge upstream release {version}", version)
    package = json.loads((root / "app/package.json").read_text(encoding="utf-8"))
    if "v" + package["version"] != version:
        raise ValueError("Merged package version does not match the upstream release tag")
    path = root / "scripts/personal-build-inputs.json"
    pins = json.loads(path.read_text(encoding="utf-8"))
    if pins["android_commit"] != android_commit:
        pins["android_commit"] = android_commit
        path.write_text(json.dumps(pins, indent=2) + "\n", encoding="utf-8")
        git(root, "add", str(path))
        git(root, "commit", "-m", f":ci: Pin Android source for {version}")
    return git(root, "rev-parse", "HEAD")


def check_patches(root, version):
    pins = json.loads((root / "scripts/personal-build-inputs.json").read_text(encoding="utf-8"))
    if not all(re.fullmatch(r"[0-9a-f]{40}", value) for value in pins.values()):
        raise ValueError("Build inputs must be pinned to commit SHAs")
    with tempfile.TemporaryDirectory() as folder:
        patches = Path(folder) / "patches"
        git(Path(folder), "clone", "--quiet", "--filter=blob:none", "--no-checkout", "--depth=1",
            "https://github.com/appdev/siyuan-unlock.git", str(patches))
        git(patches, "sparse-checkout", "set", "patches")
        git(patches, "fetch", "--depth=1", "origin", pins["unlock_commit"])
        git(patches, "checkout", "--detach", "FETCH_HEAD")
        subprocess.run([sys.executable, str(root / "scripts/prepare-personal-build.py"),
                        "--source", str(root), "--patch-repo", str(patches),
                        "--destination", str(Path(folder) / "siyuan"), "--version", version], check=True)


def publish(root, version, tag):
    git(root, "tag", tag)
    # 同时推送主分支和发布标签，远端并发更新时由正常快进检查阻止覆盖。
    git(root, "push", "--atomic", "origin", "HEAD:refs/heads/master", f"refs/tags/{tag}")
    # 使用标签触发，使发布工作流检出本次合并的固定提交。
    print(gh("workflow", "run", "personal-release.yml", "--repo", REPOSITORY,
             "--ref", tag, "-f", "version=" + version, "-f", "release_tag=" + tag).strip())


def synchronize(root, check_only=False):
    if check_only and os.environ.get("COPILOT_AGENT_TOKEN"):
        print(subprocess.check_output([sys.executable, str(root / "scripts/personal-copilot.py"), "--check-access"], text=True).strip())
    release = api(f"repos/{UPSTREAM}/releases/latest")
    pages = json.loads(gh("api", f"repos/{REPOSITORY}/releases?per_page=100", "--paginate", "--slurp"))
    refs = api(f"repos/{REPOSITORY}/git/matching-refs/tags/{release['tag_name']}-unlock.")
    current = json.loads((root / "app/package.json").read_text(encoding="utf-8"))["version"]
    selected = next_release(release, [item for page in pages for item in page], refs, current)
    if selected is None:
        return f"No new stable release to publish ({release['tag_name']}). Existing drafts/tags are resumed through their release workflow."
    version, tag = selected
    upstream_commit = tag_commit(UPSTREAM, version)
    android_commit = tag_commit("siyuan-note/siyuan-android", version)
    if check_only:
        return f"Would merge {UPSTREAM}@{version} ({upstream_commit}) into master and publish {tag}."
    try:
        commit = merge_tag(root, "https://github.com/" + UPSTREAM + ".git", version, upstream_commit, android_commit)
    except subprocess.CalledProcessError:
        conflicts = subprocess.check_output(["git", "-C", str(root), "diff", "--name-only", "--diff-filter=U", "-z"],
                                            text=True).split("\0")
        conflicts = [path for path in conflicts if path]
        if not conflicts:
            raise
        context = {"version": version, "upstream_commit": upstream_commit, "android_commit": android_commit,
                   "base_commit": git(root, "rev-parse", "HEAD"), "files": conflicts}
        return subprocess.check_output([sys.executable, str(root / "scripts/personal-copilot.py")],
                                       input=json.dumps(context), text=True).strip()
    check_patches(root, version)
    publish(root, version, tag)
    return f"Merged {version} into master at {commit}; dispatched release {tag}."


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    message = synchronize(Path(__file__).resolve().parents[1], args.check_only)
    print(message)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as output:
            output.write(message + "\n")
