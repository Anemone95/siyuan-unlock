import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("personal_upstream", Path(__file__).with_name("personal-upstream.py"))
SYNC = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SYNC)


class ReleaseSelectionTest(unittest.TestCase):
    def setUp(self):
        self.release = {"tag_name": "v3.8.6", "draft": False, "prerelease": False}

    def test_selects_stable_version_and_ignores_prereleases(self):
        self.assertEqual(SYNC.next_release(self.release, [], [], "3.8.5"), ("v3.8.6", "v3.8.6-unlock.1"))
        self.assertIsNone(SYNC.next_release({**self.release, "prerelease": True}, [], [], "3.8.5"))
        self.assertIsNone(SYNC.next_release({**self.release, "draft": True}, [], [], "3.8.5"))
        with self.assertRaises(ValueError):
            SYNC.next_release({**self.release, "tag_name": "master"}, [], [], "3.8.5")

    def test_existing_release_draft_or_dispatched_tag_is_not_repeated(self):
        for draft in [False, True]:
            with self.subTest(draft=draft):
                self.assertIsNone(SYNC.next_release(self.release, [{"tag_name": "v3.8.6-unlock.1", "draft": draft}], [], "3.8.6"))
        self.assertIsNone(SYNC.next_release(self.release, [], [{"ref": "refs/tags/v3.8.6-unlock.1"}], "3.8.6"))

    def test_older_release_is_rejected(self):
        with self.assertRaises(ValueError):
            SYNC.next_release(self.release, [], [], "3.8.7")

    def test_annotated_tag_is_resolved_to_commit(self):
        with patch.object(SYNC, "api", side_effect=[{"object": {"type": "tag", "sha": "a" * 40}},
                                                   {"object": {"type": "commit", "sha": "b" * 40}}]) as api:
            self.assertEqual(SYNC.tag_commit("official/repo", "v3.8.6"), "b" * 40)
            self.assertEqual(api.call_args.args[0], "repos/official/repo/git/tags/" + "a" * 40)


class UpstreamMergeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.upstream = self.base / "upstream"
        self.source = self.base / "source"
        self.origin = self.base / "origin.git"
        self.upstream.mkdir()
        self.git(self.upstream, "init", "--quiet", "-b", "master")
        self.configure(self.upstream)
        (self.upstream / "app").mkdir()
        (self.upstream / "app/package.json").write_text(json.dumps({"version": "3.8.5"}))
        (self.upstream / "common.txt").write_text("base\n")
        self.commit(self.upstream, "Initial official release")
        self.git(self.base, "clone", "--quiet", str(self.upstream), str(self.source))
        self.configure(self.source)
        (self.source / "recovery.txt").write_text("personal recovery\n")
        (self.source / "scripts").mkdir()
        self.pins = {"unlock_commit": "a" * 40, "ios_commit": "b" * 40, "android_commit": "c" * 40}
        (self.source / "scripts/personal-build-inputs.json").write_text(json.dumps(self.pins))
        self.commit(self.source, "Personal changes")
        self.start = self.git(self.source, "rev-parse", "HEAD")
        self.git(self.base, "clone", "--quiet", "--bare", str(self.source), str(self.origin))
        self.git(self.source, "remote", "set-url", "origin", str(self.origin))
        (self.upstream / "app/package.json").write_text(json.dumps({"version": "3.8.6"}))
        (self.upstream / "common.txt").write_text("stable release\n")
        self.commit(self.upstream, "Stable release")
        self.git(self.upstream, "tag", "-a", "v3.8.6", "-m", "Stable")
        self.stable = self.git(self.upstream, "rev-parse", "v3.8.6^{commit}")
        (self.upstream / "development-only.txt").write_text("after the tag\n")
        (self.upstream / "common.txt").write_text("unreleased development\n")
        self.commit(self.upstream, "Post-release development")

    def git(self, root, *args):
        return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.DEVNULL, text=True).strip()

    def configure(self, root):
        for name, value in [("user.name", "Sync test"), ("user.email", "sync-test@example.invalid"),
                            ("commit.gpgsign", "false"), ("tag.gpgsign", "false"), ("core.autocrlf", "false")]:
            self.git(root, "config", name, value)

    def commit(self, root, message):
        self.git(root, "add", ".")
        self.git(root, "commit", "--quiet", "-m", message)

    def merge(self, expected=None):
        return SYNC.merge_tag(self.source, str(self.upstream), "v3.8.6", expected or self.stable, "d" * 40)

    def test_merges_exact_tag_preserving_our_changes_and_excluding_later_master(self):
        self.merge()
        self.assertEqual((self.source / "common.txt").read_text(), "stable release\n")
        self.assertEqual((self.source / "recovery.txt").read_text(), "personal recovery\n")
        self.assertFalse((self.source / "development-only.txt").exists())
        self.git(self.source, "merge-base", "--is-ancestor", self.stable, "HEAD")
        pins = json.loads((self.source / "scripts/personal-build-inputs.json").read_text())
        self.assertEqual(pins, {**self.pins, "android_commit": "d" * 40})
        self.assertEqual(self.git(self.source, "status", "--porcelain"), "")

    def test_dirty_checkout_and_moved_tag_leave_head_unchanged(self):
        (self.source / "unsaved.txt").write_text("user edit\n")
        with self.assertRaises(ValueError):
            self.merge()
        self.assertEqual((self.source / "unsaved.txt").read_text(), "user edit\n")
        (self.source / "unsaved.txt").unlink()
        with self.assertRaises(ValueError):
            self.merge(expected=self.start)
        self.assertEqual(self.git(self.source, "rev-parse", "HEAD"), self.start)

    def test_merge_conflict_leaves_remote_master_unchanged(self):
        (self.source / "common.txt").write_text("personal conflicting change\n")
        self.commit(self.source, "Conflict fixture")
        with self.assertRaises(subprocess.CalledProcessError):
            self.merge()
        self.assertEqual(self.git(self.origin, "rev-parse", "master"), self.start)

    def test_successful_push_dispatches_the_immutable_release_tag(self):
        commit = self.merge()
        with patch.object(SYNC, "gh", return_value="Dispatched") as gh:
            SYNC.publish(self.source, "v3.8.6", "v3.8.6-unlock.1")
        self.assertEqual(self.git(self.origin, "rev-parse", "master"), commit)
        self.assertEqual(self.git(self.origin, "rev-parse", "refs/tags/v3.8.6-unlock.1"), commit)
        args = gh.call_args.args
        self.assertEqual(args[args.index("--ref") + 1], "v3.8.6-unlock.1")

    def test_patch_failure_prevents_push_and_release(self):
        merge = SYNC.merge_tag
        responses = [{"tag_name": "v3.8.6", "draft": False, "prerelease": False}, [],
                     {"object": {"type": "commit", "sha": self.stable}},
                     {"object": {"type": "commit", "sha": "d" * 40}}]
        with patch.object(SYNC, "api", side_effect=responses), patch.object(SYNC, "gh", return_value="[[]]"), \
                patch.object(SYNC, "merge_tag", side_effect=lambda root, url, *args: merge(root, str(self.upstream), *args)), \
                patch.object(SYNC, "check_patches", side_effect=ValueError("Patch conflict")), \
                patch.object(SYNC, "publish") as publish:
            with self.assertRaisesRegex(ValueError, "Patch conflict"):
                SYNC.synchronize(self.source)
            publish.assert_not_called()
        self.assertEqual(self.git(self.origin, "rev-parse", "master"), self.start)

    def test_merge_conflict_is_delegated_with_exact_context_before_any_push(self):
        (self.source / "common.txt").write_text("personal conflict\n")
        self.commit(self.source, "Conflict fixture")
        base = self.git(self.source, "rev-parse", "HEAD")
        merge, command = SYNC.merge_tag, subprocess.check_output
        contexts = []

        def output(args, **kwargs):
            if args[0] == sys.executable:
                contexts.append(json.loads(kwargs["input"]))
                return "Copilot PR requested"
            return command(args, **kwargs)

        responses = [{"tag_name": "v3.8.6", "draft": False, "prerelease": False}, [],
                     {"object": {"type": "commit", "sha": self.stable}},
                     {"object": {"type": "commit", "sha": "d" * 40}}]
        with patch.object(SYNC, "api", side_effect=responses), patch.object(SYNC, "gh", return_value="[[]]"), \
                patch.object(SYNC, "merge_tag", side_effect=lambda root, url, *args: merge(root, str(self.upstream), *args)), \
                patch.object(subprocess, "check_output", side_effect=output), patch.object(SYNC, "publish") as publish:
            self.assertEqual(SYNC.synchronize(self.source), "Copilot PR requested")
            publish.assert_not_called()
        self.assertEqual(contexts, [{"version": "v3.8.6", "upstream_commit": self.stable, "base_commit": base,
                                     "android_commit": "d" * 40, "files": ["common.txt"]}])
        self.assertEqual(self.git(self.origin, "rev-parse", "master"), self.start)

    def test_other_git_errors_are_not_classified_as_merge_conflicts(self):
        responses = [{"tag_name": "v3.8.6", "draft": False, "prerelease": False}, [],
                     {"object": {"type": "commit", "sha": self.stable}},
                     {"object": {"type": "commit", "sha": "d" * 40}}]
        error = subprocess.CalledProcessError(1, ["git", "fetch"])
        with patch.object(SYNC, "api", side_effect=responses), patch.object(SYNC, "gh", return_value="[[]]"), \
                patch.object(SYNC, "merge_tag", side_effect=error), patch.object(SYNC, "publish") as publish:
            with self.assertRaises(subprocess.CalledProcessError):
                SYNC.synchronize(self.source)
            publish.assert_not_called()

    def test_concurrent_master_update_rejects_both_push_refs_and_dispatch(self):
        self.merge()
        other = self.base / "other"
        self.git(self.base, "clone", "--quiet", str(self.origin), str(other))
        self.configure(other)
        (other / "concurrent.txt").write_text("concurrent user commit\n")
        self.commit(other, "Concurrent update")
        self.git(other, "push", "origin", "master")
        remote_head = self.git(other, "rev-parse", "HEAD")
        with patch.object(SYNC, "gh") as gh:
            with self.assertRaises(subprocess.CalledProcessError):
                SYNC.publish(self.source, "v3.8.6", "v3.8.6-unlock.1")
            gh.assert_not_called()
        self.assertEqual(self.git(self.origin, "rev-parse", "master"), remote_head)
        self.assertEqual(self.git(self.origin, "tag", "--list", "v3.8.6-unlock.1"), "")


if __name__ == "__main__":
    unittest.main()
