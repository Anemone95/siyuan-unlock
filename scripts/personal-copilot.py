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


def request(path, payload=None, token=None):
    env = dict(os.environ)
    if token:
        env["GH_TOKEN"] = token
    with tempfile.TemporaryDirectory() as folder:
        command = ["gh", "api", path, "-H", "X-GitHub-Api-Version: 2022-11-28"]
        if payload is not None:
            file = Path(folder) / "request.json"
            file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            command += ["--method", "POST", "--input", str(file)]
        return json.loads(subprocess.check_output(command, env=env, text=True))


def issue_body(context):
    marker = f"<!-- upstream-merge-conflict: {context['upstream_commit']} -->"
    paths = "\n".join("- " + json.dumps(path, ensure_ascii=False) for path in context["files"])
    return f"""与上游 {context['version']} 的合并存在冲突。

请从本仓库最新 master 创建修复 PR，合并官方 siyuan-note/siyuan 的 {context['version']} tag，并保留真正的 Git merge 历史。该 tag 已解析为 `{context['upstream_commit']}`；复现时个人分支为 `{context['base_commit']}`。

本次冲突文件：

{paths}

将修改限定为本次合并所需内容，保留个人恢复模块及其 hook。iOS 恢复继续仅由事件回调驱动，保留编辑状态、未确认事务和 WebSocket session 身份校验。沿用当前固定 iOS 壳和解锁补丁提交；Android 壳对应版本的提交为 `{context['android_commit']}`。

完成后运行发布工具回归、适用的 Go race 测试、前端恢复测试及 lint，并在 PR 中说明解决方式和实际测试结果。PR 合并由维护者确认，发布由现有同步工作流接续。

验证入口：

```sh
python -m unittest discover -s scripts -p 'test_personal_*.py'
```

Go 测试在 kernel 目录执行 `go test -race -timeout 120s ./server/mobiletransport` 和 `go test -vet=off -race -tags fts5 -timeout 120s ./util ./server -run 'Test(PushSession|Recovery|Mobile)'`。前端在 app 目录执行 `node --test tests/ios*.test.mjs` 和 `pnpm run lint`。

{marker}
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
    marker = f"<!-- upstream-merge-conflict: {context['upstream_commit']} -->"
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
                                 "custom_instructions": "Resolve the pinned upstream tag merge described in the issue and open a pull request for maintainer review."},
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
