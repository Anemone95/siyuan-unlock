#!/usr/bin/env python3
"""为上游 tag 的合并冲突建立一次 Copilot 任务，由维护者审核修复 PR。"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

REPOSITORY = "Anemone95/siyuan-unlock"
COPILOT = "copilot-swe-agent[bot]"
CONTEXT_MARKER = "<!-- siyuan-repair-context: "


def request(path, payload=None, token=None, method="POST"):
    env = dict(os.environ)
    if token:
        env["GH_TOKEN"] = token
    with tempfile.TemporaryDirectory() as folder:
        command = ["gh", "api", path, "-H", "X-GitHub-Api-Version: 2022-11-28"]
        if payload is not None:
            file = Path(folder) / "request.json"
            file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            command += ["--method", method, "--input", str(file)]
        output = subprocess.check_output(command, env=env, text=True)
        return json.loads(output) if output.strip() else None


def conflict_marker(context):
    return f"<!-- upstream-merge-conflict: {context['upstream_commit']} -->"


def issue_body(context):
    marker = conflict_marker(context)
    record = {key: context[key] for key in ("version", "upstream_commit", "base_commit", "android_commit")}
    paths = "\n".join("- " + json.dumps(path, ensure_ascii=False) for path in context["files"])
    return f"""与上游 {context['version']} 的合并存在冲突。

请从本仓库最新 master 创建修复 PR，合并官方 siyuan-note/siyuan 的 {context['version']} tag，并保留真正的 Git merge 历史。该 tag 已解析为 `{context['upstream_commit']}`；复现时个人分支为 `{context['base_commit']}`。

本次冲突文件：

{paths}

将修改限定为本次适配所需内容，保留个人恢复模块及其 hook。iOS 恢复继续仅由事件回调驱动，保留编辑状态、未确认事务和 WebSocket session 身份校验。Android 壳对应版本的提交为 `{context['android_commit']}`。

解锁功能直接维护在本仓库源码中，随上游改动一并适配并保留完整行为。沿用当前固定 iOS 壳和 Android 壳补丁提交。

修复与验证期间保持草稿 PR。完成代码后，自动验收控制器会固定最新提交运行四平台 CI/CD；失败日志会反馈到本 PR，请持续修复并提交新的候选。控制器核验该提交的检查、构建来源与全部产物后，才会转为待审核并请求维护者 review。若日志证实是临时外部故障，请说明诊断；代理完成事件会推动同一提交重新验证。合并与正式发布仍由维护者确认后接续。

验证入口：

```sh
python -m unittest discover -s scripts -p 'test_personal_*.py'
```

Go 测试在 kernel 目录执行 `go test -race -timeout 120s ./server/mobiletransport` 和 `go test -vet=off -race -tags fts5 -timeout 120s ./util ./server -run 'Test(PushSession|Recovery|Mobile)'`。前端在 app 目录执行 `node --test tests/ios*.test.mjs` 和 `pnpm run lint`。

提交验收清单：

1. 在修复 PR 分支真实合并目标 tag，执行 `git merge-base --is-ancestor {context['upstream_commit']} HEAD` 并确认成功。核对 `app/package.json` 与 `kernel/util/working.go` 的版本均为 `{context['version'].removeprefix('v')}`。
2. 使用已提交且干净的候选 HEAD 执行 `python scripts/prepare-personal-build.py --source . --destination <新临时目录>/siyuan --version {context['version']}` 生成独立构建目录，在其中执行受影响 API、账户同步（`bash scripts/check-account-free.sh <新临时目录>/siyuan`）及恢复回归。记录验证时的 HEAD，以及构建记录中的 `source_commit`、`source_edits`，使测试对象与 PR 最新提交一致。
3. 若代理采用 partial clone、缺少 SDK 或工具，先在独立完整检出中验证同一 HEAD；保留原测试断言，将仍无法运行的检查明确列为环境限制，交由正常 CI 复验。
4. PR 描述列出实际命令、通过项、失败项及未验证项。失败和未运行的检查保留准确状态；每次修改后补齐对应回归。提交保留在修复 PR 分支，由维护者确认合并后接续发布。

{marker}
{CONTEXT_MARKER}{json.dumps(record, sort_keys=True)} -->
"""


def check_access(token):
    if not token:
        raise ValueError("Set COPILOT_AGENT_TOKEN to a repository-scoped user token")
    owner, repo = REPOSITORY.split("/")
    query = f'query {{ repository(owner:"{owner}", name:"{repo}") {{ suggestedActors(capabilities:[CAN_BE_ASSIGNED], first:100) {{ nodes {{ login }} }} }} }}'
    result = request("graphql", {"query": query}, token)
    if result.get("errors"):
        raise ValueError("Copilot access query failed: " + "; ".join(error["message"] for error in result["errors"]))
    actors = result["data"]["repository"]["suggestedActors"]["nodes"]
    if not any(actor["login"] == "copilot-swe-agent" for actor in actors):
        raise ValueError("Copilot cloud agent is not available to this user token in the repository")
    return "Copilot cloud agent account and repository access verified"


def delegate(context, token):
    if not token:
        raise ValueError("Set COPILOT_AGENT_TOKEN to a repository-scoped user token to assign merge conflicts to Copilot")
    marker = conflict_marker(context)
    issue = None
    page = 1
    while True:
        items = request(f"repos/{REPOSITORY}/issues?state=all&per_page=100&page={page}")
        matches = [item for item in items if "pull_request" not in item and marker in (item.get("body") or "")
                   and item["user"]["login"] in {"github-actions[bot]", REPOSITORY.split("/")[0]}]
        if matches:
            issue = matches[0]
            break
        if len(items) < 100:
            break
        page += 1
    if issue is None:
        payload = {"title": f"Merge conflicts with upstream {context['version']}", "body": issue_body(context)}
        created = request(f"repos/{REPOSITORY}/issues", payload)
        issue = request(f"repos/{REPOSITORY}/issues/{created['number']}")
        if issue["title"] != payload["title"] or issue["body"] != payload["body"]:
            raise ValueError("Conflict issue read-back does not match the requested content")
    if issue["state"] == "closed":
        return "Conflict already tracked; resume the existing Copilot task or PR: " + issue["html_url"]
    if not any(assignee["login"].lower() in {"copilot", "copilot-swe-agent", COPILOT} for assignee in issue["assignees"]):
        request(f"repos/{REPOSITORY}/issues/{issue['number']}/assignees", {
            "assignees": [COPILOT],
            "agent_assignment": {"target_repo": REPOSITORY, "base_branch": "master",
                                 "custom_instructions": "Resolve the exact upstream tag integration failure described in the issue and preserve the merge ancestry. Keep the PR in draft while addressing automated CI feedback. The artifact validation controller requests maintainer review only after all four platforms pass for the current commit."},
        }, token)
        issue = request(f"repos/{REPOSITORY}/issues/{issue['number']}")
        if not any(assignee["login"].lower() in {"copilot", "copilot-swe-agent", COPILOT} for assignee in issue["assignees"]):
            raise ValueError("GitHub did not assign Copilot; verify the user token and Copilot repository access")
    return "Copilot conflict-resolution PR requested; maintainer review required: " + issue["html_url"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-access", action="store_true")
    args = parser.parse_args()
    token = os.environ.get("COPILOT_AGENT_TOKEN")
    print(check_access(token) if args.check_access else delegate(json.load(sys.stdin), token))
