#!/usr/bin/env python3
"""根据代理与构建完成事件推进修复，产物通过验收后请求维护者审核。"""
import argparse
import base64
import io
import json
import os
from pathlib import Path
import re
import runpy
import subprocess
from urllib.parse import urlencode
import zipfile

COPILOT = runpy.run_path(str(Path(__file__).with_name("personal-copilot.py")))
request = COPILOT["request"]
REPOSITORY = COPILOT["REPOSITORY"]
OWNER, NAME = REPOSITORY.split("/")
PREFIX = f"repos/{REPOSITORY}/"
CHECK_PATH = ".github/workflows/personal-check.yml"
AGENT_PATH = "dynamic/copilot-swe-agent/copilot"
AUTHORS = {OWNER, "github-actions[bot]"}
DESKTOP = {"linux.tar.gz", "linux-arm64.tar.gz", "linux.AppImage", "mac.dmg", "mac-arm64.dmg", "win.exe"}
INPUTS = {"inputs-android", "inputs-ios", "inputs-docker"} | {"inputs-desktop-" + name for name in DESKTOP}
ASSETS = {"assets-android", "assets-ios", "assets-docker"} | {"assets-desktop-" + name for name in DESKTOP | {"linux.deb", "linux-arm64.deb"}}
RUN_TITLE = re.compile(r"Repair PR #(\d+) @([0-9a-f]{40})")


def pages(path, key=None):
    result = []
    page = 1
    while True:
        response = request(PREFIX + path + ("&" if "?" in path else "?") + f"per_page=100&page={page}")
        items = response[key] if key else response
        result.extend(items)
        if len(items) < 100:
            return result
        page += 1


def context_from_issue(issue):
    if issue["user"]["login"] not in AUTHORS:
        return None
    lines = [line for line in (issue.get("body") or "").splitlines() if line.startswith(COPILOT["CONTEXT_MARKER"])]
    if len(lines) != 1 or not lines[0].endswith(" -->"):
        return None
    try:
        context = json.loads(lines[0][len(COPILOT["CONTEXT_MARKER"]):-4])
    except ValueError:
        return None
    if not isinstance(context, dict):
        return None
    if not isinstance(context.get("version"), str) or not re.fullmatch(r"v\d+\.\d+\.\d+", context["version"]):
        return None
    if not all(isinstance(context.get(key), str) and re.fullmatch(r"[0-9a-f]{40}", context[key]) for key in ("upstream_commit", "base_commit", "android_commit")):
        return None
    if context.get("kind", "merge") not in ("merge", "patch"):
        return None
    if context.get("kind") == "patch" and (not isinstance(context.get("unlock_commit"), str)
            or not re.fullmatch(r"[0-9a-f]{40}", context["unlock_commit"])):
        return None
    if COPILOT["conflict_marker"](context) not in issue["body"]:
        return None
    return context


def managed_pr(number):
    pr = request(PREFIX + f"pulls/{number}")
    if (pr["state"] != "open" or pr["base"]["ref"] != "master" or not pr["head"]["ref"].startswith("copilot/")
            or (pr["head"].get("repo") or {}).get("full_name") != REPOSITORY
            or pr["user"]["login"].lower() not in {"copilot", "copilot-swe-agent[bot]", "copilot-swe-agent"}):
        return None
    query = f'query {{ repository(owner:"{OWNER}",name:"{NAME}") {{ pullRequest(number:{int(number)}) {{ closingIssuesReferences(first:100) {{ nodes {{ number repository {{ nameWithOwner }} }} }} }} }} }}'
    links = request("graphql", {"query": query})["data"]["repository"]["pullRequest"]["closingIssuesReferences"]["nodes"]
    for link in links:
        if link["repository"]["nameWithOwner"] == REPOSITORY:
            context = context_from_issue(request(PREFIX + f"issues/{link['number']}"))
            if context:
                return pr, context
    return None


def resolve_event(event, event_name):
    if event_name == "workflow_dispatch":
        number = int(event["inputs"]["pr_number"])
        return number if managed_pr(number) else None
    run = request(PREFIX + f"actions/runs/{int(event['workflow_run']['id'])}")
    if run["path"].split("@", 1)[0] not in {CHECK_PATH, AGENT_PATH} or (run.get("head_repository") or {}).get("full_name") != REPOSITORY:
        return None
    match = RUN_TITLE.fullmatch(run.get("display_title", ""))
    if match:
        number = int(match[1])
        return number if managed_pr(number) else None
    branch = run["head_branch"]
    if not branch.startswith("copilot/"):
        return None
    for pr in request(PREFIX + "pulls?" + urlencode({"state": "open", "head": OWNER + ":" + branch})):
        if managed_pr(pr["number"]):
            return pr["number"]
    return None


def candidate_run(run, pr):
    if (run["path"].split("@", 1)[0] != CHECK_PATH or run["event"] != "workflow_dispatch"
            or run["head_branch"] != pr["head"]["ref"] or run["head_sha"] != pr["head"]["sha"]):
        return False
    match = RUN_TITLE.fullmatch(run.get("display_title", ""))
    if match:
        return int(match[1]) == pr["number"] and match[2] == pr["head"]["sha"]
    return True


def current_head(pr):
    current = request(PREFIX + f"pulls/{pr['number']}")
    return current["state"] == "open" and current["head"]["sha"] == pr["head"]["sha"]


def set_draft(pr, draft):
    if draft and OWNER in {reviewer["login"] for reviewer in pr["requested_reviewers"]}:
        request(PREFIX + f"pulls/{pr['number']}/requested_reviewers", {"reviewers": [OWNER]}, method="DELETE")
        pr["requested_reviewers"] = [reviewer for reviewer in pr["requested_reviewers"] if reviewer["login"] != OWNER]
    if pr["draft"] == draft:
        return
    mutation = "convertPullRequestToDraft" if draft else "markPullRequestReadyForReview"
    query = f'mutation {{ {mutation}(input:{{pullRequestId:"{pr["node_id"]}"}}) {{ pullRequest {{ isDraft }} }} }}'
    result = request("graphql", {"query": query})
    if result.get("errors") or result["data"][mutation]["pullRequest"]["isDraft"] != draft:
        raise ValueError("GitHub did not update the repair PR draft state")
    pr["draft"] = draft


def has_marker(comments, marker):
    return any(item["user"]["login"] in AUTHORS and marker in item["body"] for item in comments)


def feedback(pr, comments, key, detail):
    marker = f"<!-- siyuan-repair-feedback: {pr['head']['sha']} {key} -->"
    if has_marker(comments, marker):
        return "Waiting for Copilot to produce a new candidate commit; this failure was already reported."
    if not current_head(pr):
        return "Ignored obsolete failure after the PR head changed."
    token = os.environ.get("COPILOT_AGENT_TOKEN")
    if not token:
        raise ValueError("COPILOT_AGENT_TOKEN is required for automatic Copilot follow-up")
    body = (f"@copilot 当前候选 `{pr['head']['sha']}` 尚未通过完整产物验收。\n\n{detail}\n\n"
            "请读取具体失败日志，合并最新 master 的验收工作流，保留初始任务的 tag、版本、补丁和恢复语义要求，持续修复并提交新的候选。"
            "修复期间保持草稿；自动控制器会再次构建四个平台，全部产物验收后统一请求维护者审核。\n\n" + marker)
    request(PREFIX + f"issues/{pr['number']}/comments", {"body": body}, token)
    return "Reported the failure to Copilot; the PR remains a draft."


def source_file(head, path):
    response = request(PREFIX + f"contents/{path}?ref={head}")
    return base64.b64decode(response["content"]).decode("utf-8")


def preflight(pr, context):
    head = pr["head"]["sha"]
    comparison = request(PREFIX + f"compare/{context['upstream_commit']}...{head}")
    if comparison["behind_by"] or comparison["merge_base_commit"]["sha"] != context["upstream_commit"]:
        return "请在修复分支真实合并官方 tag，并验证 `git merge-base --is-ancestor " + context["upstream_commit"] + " HEAD`。"
    version = context["version"][1:]
    package = json.loads(source_file(head, "app/package.json"))
    kernel = re.findall(r'^const Ver = "([^"]+)"', source_file(head, "kernel/util/working.go"), re.M)
    if package["version"] != version or kernel != [version]:
        return "前端与内核版本必须均为 " + version + "，并对应目标 tag。"
    return None


def read_provenance(artifact):
    if artifact["size_in_bytes"] > 1_048_576:
        raise ValueError("Build provenance archive is unexpectedly large")
    data = subprocess.check_output(["gh", "api", PREFIX + f"actions/artifacts/{artifact['id']}/zip"])
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if archive.namelist() != ["siyuan-build-inputs.json"] or archive.infolist()[0].file_size > 1_048_576:
            raise ValueError("Unexpected provenance archive contents")
        return json.loads(archive.read("siyuan-build-inputs.json"))


def verify_artifacts(artifacts, records, head, version, pins, signer):
    by_name = {item["name"]: item for item in artifacts}
    if len(by_name) != len(artifacts) or not (INPUTS | ASSETS) <= by_name.keys():
        raise ValueError("Missing or ambiguous four-platform build artifacts")
    if any(by_name[name]["expired"] or by_name[name]["size_in_bytes"] <= 0 for name in INPUTS | ASSETS):
        raise ValueError("Expired or empty build artifact")
    if set(records) != INPUTS:
        raise ValueError("Missing build provenance")
    patches = None
    for name, record in records.items():
        if (not isinstance(record, dict) or record.get("source_commit") != head or record.get("source_edits") != {}
                or record.get("version") != version[1:] or record.get("unlock_commit") != pins["unlock_commit"]):
            raise ValueError("Build source mismatch: " + name)
        selected = record.get("patches")
        if not isinstance(selected, list) or len(selected) != 5 or any(not isinstance(item, dict) or not re.fullmatch(r"[0-9a-f]{64}", str(item.get("sha256", ""))) for item in selected):
            raise ValueError("Invalid patch provenance: " + name)
        if patches is not None and record["patches"] != patches:
            raise ValueError("Platform patch inputs differ")
        patches = record["patches"]
        if name == "inputs-ios" and record.get("ios_commit") != pins["ios_commit"]:
            raise ValueError("iOS source mismatch")
        if name == "inputs-android" and (record.get("android_commit") != pins["android_commit"]
                or not re.fullmatch(r"[0-9a-f]{64}", signer) or record.get("android_signer_sha256") != signer):
            raise ValueError("Android source or signer mismatch")


def start_build(pr, comments, reason="initial"):
    marker = f"<!-- siyuan-repair-build: {pr['head']['sha']} {reason} -->"
    if has_marker(comments, marker):
        raise ValueError("A build was already dispatched for this commit; inspect the existing run before resuming")
    if not current_head(pr):
        return "PR changed before build dispatch; waiting for its next event."
    token = os.environ.get("COPILOT_AGENT_TOKEN")
    if not token:
        raise ValueError("COPILOT_AGENT_TOKEN is required to preserve downstream workflow events")
    request(PREFIX + "actions/workflows/personal-check.yml/dispatches", {
        "ref": pr["head"]["ref"], "inputs": {"full_build": "true", "repair_pr": str(pr["number"])}}, token)
    request(PREFIX + f"issues/{pr['number']}/comments", {
        "body": f"已启动候选 `{pr['head']['sha']}` 的四平台产物验证；通过后自动转为待审核。\n\n{marker}"})
    return "Dispatched four-platform validation for the candidate branch; results are tied to its actual commit."


def reconcile(number):
    managed = managed_pr(number)
    if not managed:
        return "Ignored an unmanaged or closed PR."
    pr, context = managed
    comments = pages(f"issues/{number}/comments")
    branch_runs = pages("actions/runs?" + urlencode({"branch": pr["head"]["ref"]}), "workflow_runs")
    agents = [run for run in branch_runs if run["path"].split("@", 1)[0] == AGENT_PATH]
    if any(run["status"] != "completed" for run in agents):
        set_draft(pr, True)
        return "Waiting for the active Copilot session."
    agent = max(agents, key=lambda run: run["id"], default=None)
    try:
        problem = preflight(pr, context)
    except (ValueError, KeyError, TypeError) as error:
        problem = "候选提交的版本或 tag 信息无法验证：" + str(error)
    if problem:
        set_draft(pr, True)
        key = "preflight" + (f"-agent-{agent['id']}" if agent and agent["conclusion"] == "success" else "")
        return feedback(pr, comments, key, problem)
    runs = pages("actions/workflows/personal-check.yml/runs?event=workflow_dispatch", "workflow_runs")
    candidates = sorted((run for run in runs if candidate_run(run, pr)), key=lambda run: run["id"], reverse=True)
    if not candidates:
        set_draft(pr, True)
        return start_build(pr, comments)
    run = candidates[0]
    if run["status"] != "completed":
        set_draft(pr, True)
        return "Waiting for candidate build: " + run["html_url"]
    if run["conclusion"] in {"failure", "timed_out"}:
        set_draft(pr, True)
        if agent and agent["conclusion"] == "success" and agent["created_at"] > run["updated_at"]:
            return start_build(pr, comments, f"agent-{agent['id']}")
        jobs = pages(f"actions/runs/{run['id']}/jobs?filter=latest", "jobs")
        failed = [job["name"] for job in jobs if job["conclusion"] in {"failure", "timed_out"}]
        return feedback(pr, comments, f"{run['id']}-{run['run_attempt']}",
                        "构建失败：" + run["html_url"] + "\n\n失败任务：" + json.dumps(failed, ensure_ascii=False))
    if run["conclusion"] != "success":
        set_draft(pr, True)
        raise ValueError("Build is cancelled or requires external action: " + run["html_url"])
    artifacts = pages(f"actions/runs/{run['id']}/artifacts", "artifacts")
    if not (INPUTS | ASSETS) <= {item["name"] for item in artifacts} and not RUN_TITLE.fullmatch(run.get("display_title", "")):
        set_draft(pr, True)
        return start_build(pr, comments)
    try:
        pins = json.loads(source_file(pr["head"]["sha"], "scripts/personal-build-inputs.json"))
        records = {item["name"]: read_provenance(item) for item in artifacts if item["name"] in INPUTS}
        verify_artifacts(artifacts, records, pr["head"]["sha"], context["version"], pins, os.environ.get("ANDROID_SIGNING_SHA256", "").lower())
    except (ValueError, KeyError, TypeError, zipfile.BadZipFile) as error:
        set_draft(pr, True)
        return feedback(pr, comments, f"{run['id']}-{run['run_attempt']}", "产物验收失败：" + str(error) + "\n\n" + run["html_url"])
    if not current_head(pr):
        return "Ignored completed artifacts for an obsolete PR head."
    set_draft(pr, False)
    marker = f"<!-- siyuan-repair-ready: {pr['head']['sha']} -->"
    if not has_marker(comments, marker):
        request(PREFIX + f"issues/{number}/comments", {
            "body": f"候选 `{pr['head']['sha']}` 已通过四平台检查，产物与来源记录已核验，可以审核。\n\n构建及下载：{run['html_url']}\n\n{marker}"})
    current = request(PREFIX + f"pulls/{number}")
    if current["state"] != "open" or current["head"]["sha"] != pr["head"]["sha"]:
        return "PR changed before requesting review; waiting for its next event."
    if OWNER not in {reviewer["login"] for reviewer in current["requested_reviewers"]}:
        request(PREFIX + f"pulls/{number}/requested_reviewers", {"reviewers": [OWNER]})
    return "Artifacts verified; PR is ready for maintainer review: " + pr["html_url"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["resolve", "reconcile"])
    parser.add_argument("--pr", type=int)
    args = parser.parse_args()
    if args.mode == "resolve":
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
        number = resolve_event(event, os.environ["GITHUB_EVENT_NAME"])
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            output.write("pr_number=" + (str(number) if number else "") + "\n")
        message = f"Managed repair PR: {number}" if number else "No managed repair PR for this event."
    else:
        if not args.pr:
            parser.error("--pr is required for reconciliation")
        message = reconcile(args.pr)
    print(message)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as output:
            output.write(message + "\n")
