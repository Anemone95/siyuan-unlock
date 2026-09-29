from contextlib import ExitStack
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("personal_repair", Path(__file__).with_name("personal-repair.py"))
REPAIR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REPAIR)


class RepairLoopTest(unittest.TestCase):
    def setUp(self):
        self.head = "a" * 40
        self.context = {"version": "v3.8.6", "upstream_commit": "b" * 40, "base_commit": "c" * 40,
                        "android_commit": "d" * 40, "unlock_commit": "e" * 40, "kind": "patch"}
        self.pins = {"unlock_commit": "e" * 40, "ios_commit": "f" * 40, "android_commit": "d" * 40}
        self.signer = "1" * 64
        self.pr = {"number": 2, "state": "open", "draft": True, "node_id": "PR_fixture", "html_url": "https://github.com/Anemone95/siyuan-unlock/pull/2",
                   "base": {"ref": "master"}, "head": {"sha": self.head, "ref": "copilot/repair-v386", "repo": {"full_name": REPAIR.REPOSITORY}},
                   "user": {"login": "Copilot"}, "requested_reviewers": [{"login": REPAIR.OWNER}]}
        self.run = {"id": 100, "run_attempt": 1, "status": "completed", "conclusion": "success", "event": "workflow_dispatch",
                    "path": REPAIR.CHECK_PATH, "display_title": f"Repair PR #2 @{self.head}", "head_branch": self.pr["head"]["ref"],
                    "head_sha": self.head, "html_url": "https://github.com/Anemone95/siyuan-unlock/actions/runs/100"}
        self.artifacts = [{"id": i, "name": name, "expired": False, "size_in_bytes": 100}
                          for i, name in enumerate(sorted(REPAIR.INPUTS | REPAIR.ASSETS))]
        record = {"source_commit": self.head, "source_edits": {}, "version": "3.8.6", "unlock_commit": self.pins["unlock_commit"],
                  "patches": [{"path": f"patch-{i}", "sha256": str(i) * 64} for i in range(5)]}
        self.records = {name: deepcopy(record) for name in REPAIR.INPUTS}
        self.records["inputs-ios"]["ios_commit"] = self.pins["ios_commit"]
        self.records["inputs-android"].update(android_commit=self.pins["android_commit"], android_signer_sha256=self.signer)

    def test_machine_context_requires_an_owned_issue_and_valid_tag_identity(self):
        issue = {"user": {"login": "github-actions[bot]"}, "body": REPAIR.COPILOT["issue_body"]({**self.context, "files": [], "details": "patch failed"})}
        self.assertEqual(REPAIR.context_from_issue(issue), self.context)
        self.assertIsNone(REPAIR.context_from_issue({**issue, "user": {"login": "external-user"}}))
        self.assertIsNone(REPAIR.context_from_issue({**issue, "body": issue["body"].replace('"v3.8.6"', '"master"')}))

    def test_foreign_or_unmanaged_pull_requests_are_excluded(self):
        variants = [
            {**self.pr, "user": {"login": "external-user"}},
            {**self.pr, "head": {**self.pr["head"], "repo": {"full_name": "external/fork"}}},
            {**self.pr, "head": {**self.pr["head"], "ref": "feature/unrelated"}},
            {**self.pr, "state": "closed"},
        ]
        for pr in variants:
            with self.subTest(pr=pr), patch.object(REPAIR, "request", return_value=pr) as request:
                self.assertIsNone(REPAIR.managed_pr(2))
                self.assertEqual(request.call_count, 1)

    def test_dynamic_agent_event_uses_workflow_path_instead_of_its_changing_title(self):
        run = {"path": REPAIR.AGENT_PATH, "name": "Addressing comment on PR #2", "head_branch": self.pr["head"]["ref"],
               "head_repository": {"full_name": REPAIR.REPOSITORY}}
        with patch.object(REPAIR, "request", side_effect=[run, [self.pr]]), patch.object(REPAIR, "managed_pr", return_value=(self.pr, self.context)):
            self.assertEqual(REPAIR.resolve_event({"workflow_run": {"id": 50}}, "workflow_run"), 2)

    def test_trusted_build_event_resolves_the_candidate_from_its_title(self):
        run = {**self.run, "head_repository": {"full_name": REPAIR.REPOSITORY}}
        with patch.object(REPAIR, "request", return_value=run), patch.object(REPAIR, "managed_pr", return_value=(self.pr, self.context)):
            self.assertEqual(REPAIR.resolve_event({"workflow_run": {"id": 100}}, "workflow_run"), 2)
        self.assertTrue(REPAIR.candidate_run(self.run, self.pr))
        self.assertFalse(REPAIR.candidate_run({**self.run, "display_title": "Repair PR #2 @" + "0" * 40}, self.pr))

    def test_artifacts_require_every_platform_and_exact_clean_source(self):
        REPAIR.verify_artifacts(self.artifacts, self.records, self.head, "v3.8.6", self.pins, self.signer)
        with self.assertRaises(ValueError):
            REPAIR.verify_artifacts([a for a in self.artifacts if a["name"] != "assets-docker"], self.records, self.head, "v3.8.6", self.pins, self.signer)
        for key, value in [("source_commit", "0" * 40), ("source_edits", {"file": "dirty"}), ("source_edits", None), ("version", "3.8.5")]:
            records = deepcopy(self.records)
            records["inputs-ios"][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                REPAIR.verify_artifacts(self.artifacts, records, self.head, "v3.8.6", self.pins, self.signer)

    def test_artifacts_reject_bad_signer_changed_patch_inputs_and_expiration(self):
        with self.assertRaises(ValueError):
            REPAIR.verify_artifacts(self.artifacts, self.records, self.head, "v3.8.6", self.pins, "0" * 64)
        records = deepcopy(self.records)
        records["inputs-ios"]["patches"][0]["sha256"] = "f" * 64
        with self.assertRaises(ValueError):
            REPAIR.verify_artifacts(self.artifacts, records, self.head, "v3.8.6", self.pins, self.signer)
        artifacts = deepcopy(self.artifacts)
        artifacts[0]["expired"] = True
        with self.assertRaises(ValueError):
            REPAIR.verify_artifacts(artifacts, self.records, self.head, "v3.8.6", self.pins, self.signer)

    def test_feedback_uses_user_identity_and_is_sent_once_per_failure(self):
        with patch.object(REPAIR, "current_head", return_value=True), patch.object(REPAIR, "request") as request, \
                patch.dict(os.environ, {"COPILOT_AGENT_TOKEN": "user-token-fixture"}):
            REPAIR.feedback(self.pr, [], "100-1", "Build log URL")
            body = request.call_args.args[1]["body"]
            self.assertIn("@copilot", body)
            self.assertEqual(request.call_args.args[2], "user-token-fixture")
            request.reset_mock()
            REPAIR.feedback(self.pr, [{"body": body, "user": {"login": REPAIR.OWNER}}], "100-1", "Build log URL")
            request.assert_not_called()

    def test_only_copilot_can_request_retest_for_the_exact_failed_run(self):
        marker = f"<!-- siyuan-repair-retest: {self.head} 100 -->"
        comment = {"id": 10, "body": marker, "user": {"login": "Copilot"}}
        self.assertEqual(REPAIR.retest_request([comment], self.pr, self.run), "retest-10")
        self.assertIsNone(REPAIR.retest_request([{**comment, "user": {"login": REPAIR.OWNER}}], self.pr, self.run))
        self.assertIsNone(REPAIR.retest_request([{**comment, "body": marker.replace(self.head, "0" * 40)}], self.pr, self.run))
        self.assertIsNone(REPAIR.retest_request([comment], self.pr, {**self.run, "id": 101}))

    def test_dispatch_builds_candidate_workflow_and_checks_the_actual_sha(self):
        with patch.object(REPAIR, "current_head", return_value=True), patch.object(REPAIR, "request") as request:
            REPAIR.start_build(self.pr, [])
        payload = request.call_args_list[0].args[1]
        self.assertEqual(payload, {"ref": self.pr["head"]["ref"], "inputs": {"full_build": "true", "repair_pr": "2"}})
        self.assertFalse(REPAIR.candidate_run({**self.run, "head_sha": "0" * 40}, self.pr))
        body = request.call_args_list[1].args[1]["body"]
        with patch.object(REPAIR, "request") as request, self.assertRaises(ValueError):
            REPAIR.start_build(self.pr, [{"body": body, "user": {"login": "github-actions[bot]"}}])
        request.assert_not_called()

    def reconcile_fixture(self, run=None, active_agent=False, current=True, artifacts=None):
        run = self.run if run is None else run
        artifacts = self.artifacts if artifacts is None else artifacts

        def pages(path, key=None):
            if path.endswith("/comments"):
                return []
            if path.startswith("actions/runs?branch="):
                return [{"path": REPAIR.AGENT_PATH, "status": "in_progress", "name": "Addressing comment on PR #2"}] if active_agent else []
            if path.endswith("/artifacts"):
                return artifacts
            if "/jobs?" in path:
                return [{"name": "android / build", "conclusion": "failure"}]
            return [run]

        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(REPAIR, "managed_pr", return_value=(self.pr, self.context)))
        stack.enter_context(patch.object(REPAIR, "pages", side_effect=pages))
        stack.enter_context(patch.object(REPAIR, "preflight", return_value=None))
        stack.enter_context(patch.object(REPAIR, "current_head", return_value=current))
        stack.enter_context(patch.object(REPAIR, "source_file", return_value=json.dumps(self.pins)))
        stack.enter_context(patch.object(REPAIR, "read_provenance", side_effect=lambda artifact: self.records[artifact["name"]]))
        stack.enter_context(patch.object(REPAIR, "request", return_value=self.pr))
        stack.enter_context(patch.dict(os.environ, {"ANDROID_SIGNING_SHA256": self.signer}))
        draft = stack.enter_context(patch.object(REPAIR, "set_draft"))
        feedback = stack.enter_context(patch.object(REPAIR, "feedback", return_value="feedback sent"))
        return draft, feedback

    def test_active_agent_or_build_keeps_pr_draft_without_duplicate_feedback(self):
        draft, feedback = self.reconcile_fixture(active_agent=True)
        self.assertIn("active Copilot", REPAIR.reconcile(2))
        draft.assert_called_with(self.pr, True)
        feedback.assert_not_called()

    def test_ci_failure_is_returned_to_copilot(self):
        draft, feedback = self.reconcile_fixture(run={**self.run, "conclusion": "failure"})
        self.assertEqual(REPAIR.reconcile(2), "feedback sent")
        draft.assert_called_with(self.pr, True)
        self.assertIn("android / build", feedback.call_args.args[3])

    def test_running_build_is_reused(self):
        draft, feedback = self.reconcile_fixture(run={**self.run, "status": "in_progress", "conclusion": None})
        with patch.object(REPAIR, "start_build") as dispatch:
            self.assertIn("Waiting for candidate build", REPAIR.reconcile(2))
            dispatch.assert_not_called()
        draft.assert_called_with(self.pr, True)
        feedback.assert_not_called()

    def test_green_ci_without_required_artifact_is_not_ready(self):
        draft, feedback = self.reconcile_fixture(artifacts=[a for a in self.artifacts if a["name"] != "assets-android"])
        self.assertEqual(REPAIR.reconcile(2), "feedback sent")
        draft.assert_called_with(self.pr, True)

    def test_stale_artifacts_cannot_mark_a_new_head_ready(self):
        draft, feedback = self.reconcile_fixture(current=False)
        self.assertIn("obsolete", REPAIR.reconcile(2))
        draft.assert_not_called()
        feedback.assert_not_called()

    def test_only_complete_verified_artifacts_enable_review(self):
        draft, feedback = self.reconcile_fixture()
        self.assertIn("ready for maintainer review", REPAIR.reconcile(2))
        draft.assert_called_once_with(self.pr, False)
        feedback.assert_not_called()

    def test_verified_candidate_requests_only_the_maintainer_review(self):
        self.pr["requested_reviewers"] = []
        self.reconcile_fixture()
        with patch.object(REPAIR, "request", return_value=self.pr) as request:
            REPAIR.reconcile(2)
        self.assertEqual(request.call_args.args, (REPAIR.PREFIX + "pulls/2/requested_reviewers", {"reviewers": [REPAIR.OWNER]}))


if __name__ == "__main__":
    unittest.main()
