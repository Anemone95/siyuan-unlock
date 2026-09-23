#!/usr/bin/env python3
"""复制当前源码、应用固定提交的解锁补丁，并记录构建输入。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

PATCHES = ["disable-update.patch", "default-config.patch", "mock-vip-user.patch",
           "hide-account-entry.patch", "first-launch-notice.patch"]


def git(repo, *args, input=None):
    return subprocess.check_output(["git", "-C", str(repo), *args], input=input)


def prepare(source, patches, destination, version):
    if destination.exists():
        raise ValueError(f"Build destination already exists: {destination}")
    package = json.loads((source / "app/package.json").read_text(encoding="utf-8"))
    if version.removeprefix("v") != package["version"]:
        raise ValueError("Build version must match the checked-out source package.json")
    kernel_version = re.findall(r'^const Ver = "([^"]+)"',
                                (source / "kernel/util/working.go").read_text(encoding="utf-8"), re.M)
    if kernel_version != [package["version"]]:
        raise ValueError("Kernel and frontend versions must match")
    source_commit = git(source, "rev-parse", "HEAD").decode().strip()
    patch_commit = git(patches, "rev-parse", "HEAD").decode().strip()
    selected = []
    contents = []
    for name in PATCHES:
        path = "patches/siyuan/" + name
        if git(patches, "diff", "--name-only", "HEAD", "--", path).strip():
            raise ValueError(f"Patch has uncommitted modifications: {name}")
        # 使用 Git 对象中的补丁原文，使 Windows 换行转换不影响输入哈希。
        data = git(patches, "show", f"{patch_commit}:{path}")
        selected.append({"path": path, "sha256": hashlib.sha256(data).hexdigest()})
        contents.append(data)
    # 本地评审构建包含直接源码修改，CI 使用已提交的源码。
    changed = set(filter(None, git(source, "diff", "--name-only", "--no-renames", "HEAD", "-z").decode().split("\0")))
    changed.update(filter(None, git(source, "ls-files", "--others", "--exclude-standard", "-z").decode().split("\0")))
    deleted = set(filter(None, git(source, "diff", "--name-only", "--no-renames", "--diff-filter=D", "HEAD", "-z").decode().split("\0")))
    subprocess.run(["git", "clone", "--quiet", "--shared", "--no-checkout", str(source), str(destination)], check=True)
    git(destination, "checkout", "--quiet", "--detach", source_commit)
    edits = {}
    for relative in sorted(deleted):
        (destination / relative).unlink(missing_ok=True)
        edits[relative] = None
    for relative in sorted(changed - deleted):
        original, copied = source / relative, destination / relative
        if original.is_file() or original.is_symlink():
            copied.parent.mkdir(parents=True, exist_ok=True)
            if copied.is_symlink():
                copied.unlink()
            elif copied.is_dir():
                shutil.rmtree(copied)
            shutil.copy2(original, copied, follow_symlinks=False)
            content = str(copied.readlink()).encode() if copied.is_symlink() else copied.read_bytes()
            edits[relative] = hashlib.sha256(content).hexdigest()
        else:
            copied.unlink(missing_ok=True)
            edits[relative] = None
    for data in contents:
        git(destination, "apply", "--check", "-", input=data)
        git(destination, "apply", "-", input=data)
    record = {"source_commit": source_commit, "source_edits": edits,
              "unlock_repository": "appdev/siyuan-unlock", "unlock_commit": patch_commit,
              "patches": selected, "version": package["version"],
              "package_manager": package["packageManager"]}
    (destination.parent / (destination.name + "-build-inputs.json")).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"Prepared {destination}: source {source_commit}, unlock {patch_commit}")
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--patch-repo", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    prepare(args.source.resolve(), args.patch_repo.resolve(), args.destination.resolve(), args.version)
