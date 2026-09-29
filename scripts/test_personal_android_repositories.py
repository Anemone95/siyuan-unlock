from pathlib import Path
import runpy
import tempfile
import unittest

PREPARE = runpy.run_path(str(Path(__file__).with_name("prepare-personal-android.py")))["prepare_repositories"]


class AndroidRepositoriesTest(unittest.TestCase):
    def test_official_repositories_preserve_other_configuration_and_are_idempotent(self):
        content = """buildscript {
    repositories {
        maven { url 'https://maven.aliyun.com/repository/google' }
        maven { url 'https://maven.aliyun.com/repository/public' }
        maven { url 'https://maven.aliyun.com/repository/gradle-plugin' }
        google()
        mavenCentral()
        maven { url 'https://jitpack.io' }
    }
    dependencies { classpath 'com.android.tools.build:gradle:9.3.0' }
}
"""
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / "build.gradle"
            path.write_text(content, encoding="utf-8")
            PREPARE(root)
            result = path.read_text(encoding="utf-8")
            self.assertNotIn("maven.aliyun.com", result)
            for url in ["https://dl.google.com/dl/android/maven2/", "https://repo.maven.apache.org/maven2/", "https://plugins.gradle.org/m2/"]:
                self.assertIn(url, result)
            for line in content.splitlines():
                if "maven.aliyun.com" not in line:
                    self.assertIn(line, result)
            PREPARE(root)
            self.assertEqual(path.read_text(encoding="utf-8"), result)


if __name__ == "__main__":
    unittest.main()
