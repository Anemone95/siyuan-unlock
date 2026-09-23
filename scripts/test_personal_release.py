import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("personal_release", Path(__file__).with_name("personal-release.py"))
RELEASE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RELEASE)


class ReleaseInputsTest(unittest.TestCase):
    def setUp(self):
        self.record = RELEASE.inputs("v3.8.5", "v3.8.5-unlock.1", "a" * 40, "b" * 40, "c" * 40, "d" * 40, "3.8.5", "e" * 64)
        self.draft = {"id": 1, "draft": True, "tag_name": self.record["release_tag"],
                      "target_commitish": self.record["source_commit"], "body": RELEASE.release_body(self.record)}

    def test_matching_draft_is_reused_without_writes(self):
        with patch.object(RELEASE, "api", side_effect=[None, [self.draft]]) as api:
            self.assertEqual(RELEASE.ensure_draft("owner/repo", self.record), self.draft)
            self.assertEqual(api.call_count, 2)
            self.assertIn("releases?per_page=100", api.call_args.args[0])

    def test_all_source_inputs_must_match(self):
        for key in ["source_commit", "unlock_commit", "ios_commit", "android_commit", "version", "release_tag", "android_signer_sha256"]:
            with self.subTest(key=key):
                changed = {**self.record, key: "different"}
                with self.assertRaises(ValueError):
                    RELEASE.verify_draft(self.draft, changed)

    def test_published_release_and_unowned_draft_are_preserved(self):
        for draft in [{**self.draft, "draft": False}, {**self.draft, "body": "unrelated release"}]:
            with patch.object(RELEASE, "api", side_effect=[None, [draft]]) as api:
                with self.assertRaises(ValueError):
                    RELEASE.ensure_draft("owner/repo", self.record)
                self.assertEqual(api.call_count, 2)

    def test_existing_annotated_tag_must_resolve_to_source(self):
        tag = {"object": {"type": "tag", "sha": "d" * 40}}
        target = {"object": {"type": "commit", "sha": "e" * 40}}
        with patch.object(RELEASE, "api", side_effect=[tag, target]) as api:
            with self.assertRaises(ValueError):
                RELEASE.ensure_draft("owner/repo", self.record)
            self.assertEqual(api.call_count, 2)

    def test_new_draft_carries_all_inputs(self):
        with patch.object(RELEASE, "api", side_effect=[None, [], self.draft]) as api:
            RELEASE.ensure_draft("owner/repo", self.record)
            payload = api.call_args.args[1]
            self.assertTrue(payload["draft"])
            self.assertEqual(payload["target_commitish"], self.record["source_commit"])
            self.assertIn(json.dumps(self.record, sort_keys=True), payload["body"])

    def test_publish_verification_does_not_create_missing_draft(self):
        with patch.object(RELEASE, "api", side_effect=[None, []]) as api:
            with self.assertRaises(ValueError):
                RELEASE.ensure_draft("owner/repo", self.record, create=False)
            self.assertEqual(api.call_count, 2)

    def test_draft_lookup_paginates_and_rejects_duplicates(self):
        page = [{"tag_name": f"other-{index}"} for index in range(100)]
        with patch.object(RELEASE, "api", side_effect=[page, [self.draft]]):
            self.assertEqual(RELEASE.find_release("repos/owner/repo/", self.record["release_tag"]), self.draft)
        with patch.object(RELEASE, "api", return_value=[self.draft, self.draft]):
            with self.assertRaises(ValueError):
                RELEASE.find_release("repos/owner/repo/", self.record["release_tag"])

    def test_invalid_versions_and_unpinned_references(self):
        for version, tag, ref in [("v3.6.5", "v3.6.5-unlock.1", "b" * 40),
                                  ("v3.8.5", "v3.8.5", "b" * 40),
                                  ("v3.8.5", "v3.8.5-unlock/a", "b" * 40),
                                  ("v3.8.5", "v3.8.5-unlock.1", "master")]:
            with self.assertRaises(ValueError):
                RELEASE.inputs(version, tag, "a" * 40, ref, "c" * 40, "d" * 40, "3.8.5", "e" * 64)


if __name__ == "__main__":
    unittest.main()
