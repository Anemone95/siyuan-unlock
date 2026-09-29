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
    if context.get("kind") == "patch":
        return f"<!-- upstream-patch-conflict: {context['upstream_commit']} {context['unlock_commit']} -->"
    return f"<!-- upstream-merge-conflict: {context['upstream_commit']} -->"


def issue_body(context):
    marker = conflict_marker(context)
    record = {key: context[key] for key in ("version", "upstream_commit", "base_commit", "android_commit", "unlock_commit", "kind") if key in context}
    problem = f"与上游 {context['version']} 的合并存在冲突。"
    patch_guidance = "沿用当前固定 iOS 壳和解锁补丁提交。"
    if context.get("kind") == "patch":
        problem = f"解锁补丁与上游 {context['version']} 不兼容。"
        patch_guidance = f"""当前解锁补丁来自 appdev/siyuan-unlock@`{context['unlock_commit']}`，适用性检查报告：

```text
{context['details'].strip()}
```

先检查补丁提供方是否已有兼容提交，经验证后更新 `scripts/personal-build-inputs.json` 中的固定 SHA。若补丁源尚未适配，在本仓库维护最小、可审查的兼容补丁，并同步构建准备逻辑和回归测试。保持五个解锁补丁的完整功能，以及上游源码与独立构建目录的边界。沿用当前固定 iOS 壳提交。

复现时检出固定补丁源，再执行 `python scripts/prepare-personal-build.py --source . --patch-repo <补丁检出目录> --destination <新临时目录>/siyuan --version {context['version']}`，确认全部补丁依次通过检查和应用。"""
    paths = "\n".join("- " + json.dumps(path, ensure_ascii=False) for path in context["files"])
    return f"""{problem}

请从本仓库最新 master 创建修复 PR，合并官方 siyuan-note/siyuan 的 {context['version']} tag，并保留真正的 Git merge 历史。该 tag 已解析为 `{context['upstream_commit']}`；复现时个人分支为 `{context['base_commit']}`。

本次冲突文件：

{paths}

将修改限定为本次适配所需内容，保留个人恢复模块及其 hook。iOS 恢复继续仅由事件回调驱动，保留编辑状态、未确认事务和 WebSocket session 身份校验。Android 壳对应版本的提交为 `{context['android_commit']}`。

{patch_guidance}

修复与验证期间保持草稿 PR。完成代码后，自动验收控制器会固定最新提交运行四平台 CI/CD；失败日志会反馈到本 PR，请持续修复并提交新的候选。控制器核验该提交的检查、构建来源与全部产物后，才会转为待审核并请求维护者 review。若日志证实是临时外部故障，请说明诊断；代理完成事件会推动同一提交重新验证。合并与正式发布仍由维护者确认后接续。

验证入口：

```sh
python -m unittest discover -s scripts -p 'test_personal_*.py'
```

Go 测试在 kernel 目录执行 `go test -race -timeout 120s ./server/mobiletransport` 和 `go test -vet=off -race -tags fts5 -timeout 120s ./util ./server -run 'Test(PushSession|Recovery|Mobile)'`。前端在 app 目录执行 `node --test tests/ios*.test.mjs` 和 `pnpm run lint`。

提交验收清单：

1. 在修复 PR 分支真实合并目标 tag，执行 `git merge-base --is-ancestor {context['upstream_commit']} HEAD` 并确认成功。核对 `app/package.json` 与 `kernel/util/working.go` 的版本均为 `{context['version'].removeprefix('v')}`。
2. 若涉及本地版本化补丁覆盖，确保 `{context['version']}` 与 `{context['version'].removeprefix('v')}` 选择同一补丁；明确拒绝补丁的未提交修改、删除及未跟踪文件，并为这些情况补充回归。应用已提交 Git 对象中的规范字节，记录实际应用补丁的 SHA-256，保留 Windows 换行一致性。
3. 使用已提交且干净的候选 HEAD 生成独立构建目录，确认五个补丁依次检查并应用成功，再在应用补丁后的源码中执行受影响 API、账户同步及恢复回归。记录验证时的 HEAD，以及构建记录中的 `source_commit`、`source_edits`，使测试对象与 PR 最新提交一致。
4. 若代理采用 partial clone、缺少 SDK 或工具，先在独立完整检出中验证同一 HEAD；保留原测试断言，将仍无法运行的检查明确列为环境限制，交由正常 CI 复验。
5. PR 描述列出实际命令、通过项、失败项及未验证项。失败和未运行的检查保留准确状态；每次修改后补齐对应回归。提交保留在修复 PR 分支，由维护者确认合并后接续发布。

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
        title = "Unlock patch incompatibility" if context.get("kind") == "patch" else "Merge conflicts"
        payload = {"title": f"{title} with upstream {context['version']}", "body": issue_body(context)}
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
