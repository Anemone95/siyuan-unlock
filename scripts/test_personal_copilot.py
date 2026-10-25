import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("personal_copilot", Path(__file__).with_name("personal-copilot.py"))
COPILOT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(COPILOT)


class CopilotConflictTest(unittest.TestCase):
    def setUp(self):
        self.context = {"version": "v3.8.6", "upstream_commit": "a" * 40, "base_commit": "b" * 40,
                        "android_commit": "c" * 40, "files": ["kernel/server/serve.go", "path with spaces.ts"]}
        self.issue = {"number": 7, "title": "Merge conflicts with upstream v3.8.6", "state": "open",
                      "body": COPILOT.issue_body(self.context), "assignees": [],
                      "user": {"login": "github-actions[bot]"}, "html_url": "https://github.com/owner/repo/issues/7"}
        self.assigned = {**self.issue, "assignees": [{"login": "copilot-swe-agent[bot]"}]}

    def test_creates_verified_issue_and_assigns_using_user_token(self):
        with patch.object(COPILOT, "request", side_effect=[[], self.issue, self.issue, {}, self.assigned]) as request:
            result = COPILOT.delegate(self.context, "user-token-fixture")
        self.assertIn(self.issue["html_url"], result)
        self.assertEqual(request.call_args_list[1].args[1]["body"], self.issue["body"])
        args = request.call_args_list[3].args
        self.assertEqual(args[2], "user-token-fixture")
        self.assertEqual(args[1]["agent_assignment"]["base_branch"], "master")
        self.assertIn(self.context["upstream_commit"], self.issue["body"])

    def test_assigned_issue_is_reused_without_writes(self):
        with patch.object(COPILOT, "request", return_value=[self.assigned]) as request:
            COPILOT.delegate(self.context, "user-token-fixture")
        self.assertEqual(request.call_count, 1)

    def test_closed_issue_preserves_the_existing_task(self):
        with patch.object(COPILOT, "request", return_value=[{**self.assigned, "state": "closed"}]) as request:
            self.assertIn("existing Copilot task", COPILOT.delegate(self.context, "user-token-fixture"))
        self.assertEqual(request.call_count, 1)

    def test_foreign_issue_or_pull_request_cannot_replace_our_task(self):
        foreign = {**self.issue, "user": {"login": "unrelated-user"}}
        pull = {**self.issue, "pull_request": {}}
        with patch.object(COPILOT, "request", side_effect=[[foreign, pull], self.issue, self.issue, {}, self.assigned]) as request:
            COPILOT.delegate(self.context, "user-token-fixture")
        self.assertEqual(request.call_args_list[1].args[1]["title"], self.issue["title"])

    def test_missing_token_does_not_create_an_issue(self):
        with patch.object(COPILOT, "request") as request:
            with self.assertRaisesRegex(ValueError, "COPILOT_AGENT_TOKEN"):
                COPILOT.delegate(self.context, "")
        request.assert_not_called()

    def test_silently_dropped_assignment_is_reported_as_failure(self):
        with patch.object(COPILOT, "request", side_effect=[[self.issue], {}, self.issue]):
            with self.assertRaisesRegex(ValueError, "did not assign Copilot"):
                COPILOT.delegate(self.context, "user-token-fixture")

    def test_lookup_paginates_before_creating_a_duplicate(self):
        page = [{**self.issue, "body": "unrelated task"} for _ in range(100)]
        with patch.object(COPILOT, "request", side_effect=[page, [self.assigned]]) as request:
            COPILOT.delegate(self.context, "user-token-fixture")
        self.assertEqual(request.call_count, 2)
        self.assertIn("page=2", request.call_args.args[0])

    def test_access_check_uses_the_configured_user_identity(self):
        for actors in [[{"login": "copilot-swe-agent"}], []]:
            response = {"data": {"repository": {"suggestedActors": {"nodes": actors}}}}
            with self.subTest(actors=actors), patch.object(COPILOT, "request", return_value=response) as request:
                if actors:
                    self.assertIn("verified", COPILOT.check_access("user-token-fixture"))
                else:
                    with self.assertRaises(ValueError):
                        COPILOT.check_access("user-token-fixture")
                self.assertEqual(request.call_args.args[2], "user-token-fixture")
        with patch.object(COPILOT, "request", return_value={"errors": [{"message": "Resource not accessible"}]}):
            with self.assertRaisesRegex(ValueError, "Resource not accessible"):
                COPILOT.check_access("user-token-fixture")

    def test_initial_tasks_include_the_integration_acceptance_checks(self):
        body = COPILOT.issue_body(self.context)
        for requirement in ["git merge-base --is-ancestor " + self.context["upstream_commit"] + " HEAD",
                            "app/package.json", "kernel/util/working.go", "解锁功能直接维护在本仓库源码中",
                            "scripts/prepare-personal-build.py --source . --destination", "scripts/check-account-free.sh",
                            "source_commit", "source_edits", "partial clone", "通过项、失败项及未验证项", "由维护者确认合并",
                            "保持草稿 PR", "四平台 CI/CD", "临时外部故障", "全部产物"]:
            self.assertIn(requirement, body)
        self.assertNotIn("--patch-repo", body)

    def test_api_accepts_empty_successful_workflow_dispatch_response(self):
        with patch.object(COPILOT.subprocess, "check_output", return_value=""):
            self.assertIsNone(COPILOT.request("repos/owner/repo/actions/workflows/check.yml/dispatches", {"ref": "master"}))

    def test_api_can_remove_premature_review_requests(self):
        with patch.object(COPILOT.subprocess, "check_output", return_value="{}") as command:
            COPILOT.request("repos/owner/repo/pulls/2/requested_reviewers", {"reviewers": ["owner"]}, method="DELETE")
        arguments = command.call_args.args[0]
        self.assertEqual(arguments[arguments.index("--method") + 1], "DELETE")


if __name__ == "__main__":
    unittest.main()
