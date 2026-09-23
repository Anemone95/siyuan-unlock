import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("android_artifacts", Path(__file__).with_name("verify-android-artifacts.py"))
ANDROID = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ANDROID)


class AndroidArtifactsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / "android"
        self.fingerprint = "a" * 64
        for flavor, package in [("googleplay", "org.b3log.siyuan"), ("appdev", "com.appdev.siyuan")]:
            folder = self.source / "app/build/outputs/apk" / flavor / "release"
            folder.mkdir(parents=True)
            (folder / "renamed-by-gradle.apk").write_bytes(b"APK fixture")
            (folder / "output-metadata.json").write_text(json.dumps({"applicationId": package, "elements": [{"outputFile": "renamed-by-gradle.apk"}]}))
        (self.base / "siyuan-build-inputs.json").write_text("{}")

    def output(self, tool, *args):
        if tool.name == "aapt":
            package = "com.appdev.siyuan" if "appdev" in str(args[-1]) else "org.b3log.siyuan"
            return f"package: name='{package}' versionCode='398' versionName='3.8.5'\n"
        return "Signer #1 certificate SHA-256 digest: " + self.fingerprint + "\n"

    def test_uses_metadata_filenames_and_checks_both_variants(self):
        with patch.object(ANDROID, "command", side_effect=self.output):
            ANDROID.verify(self.source, self.base / "sdk", "v3.8.5", self.fingerprint)
        self.assertEqual(len(list((self.base / "release-assets").glob("*.apk"))), 2)
        self.assertEqual(json.loads((self.base / "siyuan-build-inputs.json").read_text())["android_signer_sha256"], self.fingerprint)

    def test_wrong_certificate_is_rejected_before_staging(self):
        with patch.object(ANDROID, "command", side_effect=self.output):
            with self.assertRaises(ValueError):
                ANDROID.verify(self.source, self.base / "sdk", "v3.8.5", "b" * 64)
        self.assertFalse((self.base / "release-assets").exists())

    def test_wrong_application_id_is_rejected(self):
        file = self.source / "app/build/outputs/apk/appdev/release/output-metadata.json"
        metadata = json.loads(file.read_text()); metadata["applicationId"] = "incorrect.package"
        file.write_text(json.dumps(metadata))
        with patch.object(ANDROID, "command", side_effect=self.output):
            with self.assertRaises(ValueError):
                ANDROID.verify(self.source, self.base / "sdk", "v3.8.5", self.fingerprint)
        self.assertFalse((self.base / "release-assets").exists())


if __name__ == "__main__":
    unittest.main()
