#!/usr/bin/env python3
"""在临时 Android 构建目录使用官方依赖仓库。"""
from pathlib import Path
import sys


def prepare_repositories(source):
    path = source / "build.gradle"
    content = path.read_text(encoding="utf-8")
    for mirror, official in {
        "google": "https://dl.google.com/dl/android/maven2/",
        "public": "https://repo.maven.apache.org/maven2/",
        "gradle-plugin": "https://plugins.gradle.org/m2/",
    }.items():
        content = content.replace("https://maven.aliyun.com/repository/" + mirror, official)
    path.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    prepare_repositories(Path(sys.argv[1]))
