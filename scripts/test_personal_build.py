import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("personal_build", Path(__file__).with_name("prepare-personal-build.py"))
BUILD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILD)


class BuildSnapshotTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / "source"
        self.source.mkdir()
        self.git(self.source, "init", "--quiet")
        self.git(self.source, "config", "user.name", "Build test")
        self.git(self.source, "config", "user.email", "build-test@example.invalid")
        self.git(self.source, "config", "commit.gpgsign", "false")
        self.git(self.source, "config", "core.autocrlf", "false")
        (self.source / "app").mkdir()
        (self.source / "app/package.json").write_text(json.dumps({"version": "3.8.5", "packageManager": "pnpm@12.3.4"}))
        (self.source / "kernel/util").mkdir(parents=True)
        (self.source / "kernel/util/working.go").write_text('package util\nconst Ver = "3.8.5"\n')
        (self.source / "module").mkdir()
        (self.source / "module/old.txt").write_text("before\n")
        self.commit(self.source)

    def git(self, repo, *args):
        return subprocess.check_output(["git", "-C", str(repo), *args], stderr=subprocess.DEVNULL)

    def commit(self, repo):
        self.git(repo, "add", ".")
        self.git(repo, "commit", "--quiet", "-m", "Build fixture")

    def prepare(self, name="build", version="v3.8.5"):
        return BUILD.prepare(self.source, self.base / name, version)

    def test_clean_source_records_the_committed_snapshot(self):
        record = self.prepare()
        self.assertEqual(record, {"source_commit": self.git(self.source, "rev-parse", "HEAD").decode().strip(),
                                  "source_edits": {}, "version": "3.8.5", "package_manager": "pnpm@12.3.4"})
        self.assertEqual(json.loads((self.base / "build-build-inputs.json").read_text()), record)
        self.assertEqual((self.base / "build/module/old.txt").read_text(), "before\n")

    def test_dirty_source_is_copied_and_original_preserved(self):
        (self.source / "module/old.txt").write_text("edited\n")
        (self.source / "new file.txt").write_text("new\n")
        before = self.git(self.source, "diff", "HEAD")
        record = self.prepare()
        self.assertEqual(self.git(self.source, "diff", "HEAD"), before)
        self.assertEqual((self.base / "build/module/old.txt").read_text(), "edited\n")
        self.assertEqual((self.base / "build/new file.txt").read_text(), "new\n")
        self.assertEqual(len(record["source_edits"]), 2)

    def test_directory_replaced_with_file(self):
        shutil.rmtree(self.source / "module")
        (self.source / "module").write_text("replacement\n")
        self.prepare()
        self.assertEqual((self.base / "build/module").read_text(), "replacement\n")

    def test_rejects_wrong_version_and_existing_destination(self):
        with self.assertRaises(ValueError):
            self.prepare(version="v3.6.5")
        self.assertFalse((self.base / "build").exists())
        (self.base / "build").mkdir()
        with self.assertRaises(ValueError):
            self.prepare()

    def test_rejects_mixed_kernel_and_frontend_versions(self):
        (self.source / "kernel/util/working.go").write_text('package util\nconst Ver = "3.6.5"\n')
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertFalse((self.base / "build").exists())

if __name__ == "__main__":
    unittest.main()
