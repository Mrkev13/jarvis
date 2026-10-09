"""Offline bootstrap regression checks; exercise the real shell, venv and pip."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "setup-dev.sh"
BASH = shutil.which("bash")
MARKER = ".standa-hub-setup-ok"


@unittest.skipIf(os.name == "nt" or not BASH, "POSIX offline bootstrap fixtures; real Git Bash verification is separate")
class SetupDevTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="hub bootstrap with spaces ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for directory in ("scripts", "backend"):
            (self.root / directory).mkdir()
        shutil.copy2(SCRIPT, self.root / "scripts" / "setup-dev.sh")
        (self.root / "backend" / "requirements.txt").write_text("")
        self.wheel = self.root / "bootstrap_dummy-1.0-py3-none-any.whl"
        self.write_wheel()
        (self.root / "backend" / "requirements-dev.txt").write_text(
            "-r requirements.txt\n" + self.wheel.as_uri() + "\n"
        )
        self.env_file = self.root / "backend" / ".env"
        self.env_file.write_text("BOOTSTRAP_SENTINEL=unchanged\n")
        self.venv = self.root / ".venv"
        self.env = os.environ.copy()
        for name in ("SETUP_VENV", "PYTHONHOME", "PYTHONPATH"):
            self.env.pop(name, None)
        self.env.update(SETUP_PYTHON=sys.executable, PIP_NO_INDEX="1", PIP_DISABLE_PIP_VERSION_CHECK="1")

    def write_wheel(self):
        with zipfile.ZipFile(self.wheel, "w") as archive:
            archive.writestr("bootstrap_dummy.py", "VALUE = 1\n")
            archive.writestr("bootstrap_dummy-1.0.dist-info/METADATA", "Metadata-Version: 2.1\nName: bootstrap-dummy\nVersion: 1.0\n")
            archive.writestr("bootstrap_dummy-1.0.dist-info/WHEEL", "Wheel-Version: 1.0\nGenerator: bootstrap-test\nRoot-Is-Purelib: true\nTag: py3-none-any\n")
            archive.writestr("bootstrap_dummy-1.0.dist-info/RECORD", "")

    def run_setup(self, *options, expected=0):
        result = subprocess.run(
            [BASH, str(self.root / "scripts" / "setup-dev.sh"), "--backend", *options],
            cwd=self.root, env=self.env, capture_output=True, text=True, timeout=45,
        )
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        self.assertEqual(self.env_file.read_text(), "BOOTSTRAP_SENTINEL=unchanged\n")
        return result.stdout

    def package_available(self, interpreter):
        return subprocess.run(
            [str(interpreter), "-c", "import bootstrap_dummy"],
            capture_output=True, timeout=10,
        ).returncode == 0

    def test_fresh_install_marker_and_second_run_skip(self):
        self.run_setup("--check", expected=2)
        self.assertFalse(self.venv.exists())
        self.run_setup()
        self.assertTrue(self.package_available(self.venv / "bin" / "python"))
        marker = self.venv / MARKER
        self.assertTrue(marker.is_file())
        stamp = self.root / ".dev-setup" / "backend-venv"
        timestamps = (marker.stat().st_mtime_ns, stamp.stat().st_mtime_ns)
        self.assertIn("up to date", self.run_setup())
        self.run_setup("--check", "--force")
        self.assertEqual(timestamps, (marker.stat().st_mtime_ns, stamp.stat().st_mtime_ns))
        marker.unlink()
        self.run_setup("--check", expected=2)

    def test_same_path_recreated_venv_is_stale_and_reinstalls(self):
        self.run_setup()
        interpreter = self.venv / "bin" / "python"
        self.assertTrue(self.package_available(interpreter))
        shutil.rmtree(self.venv)
        subprocess.run([sys.executable, "-m", "venv", str(self.venv)], check=True, capture_output=True, timeout=30)
        self.assertFalse(self.package_available(interpreter))
        self.assertIn("STALE", self.run_setup("--check", expected=2))
        self.assertFalse((self.venv / MARKER).exists())
        self.assertIn("installing", self.run_setup())
        self.assertTrue(self.package_available(interpreter))
        self.assertTrue((self.venv / MARKER).is_file())
        self.assertIn("up to date", self.run_setup())

    def test_failed_forced_install_cannot_leave_success_marker(self):
        self.run_setup()
        self.wheel.write_text("invalid wheel")
        self.run_setup("--force", expected=1)
        self.assertFalse((self.venv / MARKER).exists())
        self.run_setup("--check", expected=2)
        self.write_wheel()
        self.run_setup()
        self.assertTrue((self.venv / MARKER).is_file())

    def test_system_python_uses_stamp_without_environment_marker(self):
        target = self.root / "managed python with spaces"
        subprocess.run([sys.executable, "-m", "venv", str(target)], check=True, capture_output=True, timeout=30)
        self.env["SETUP_PYTHON"] = str(target / "bin" / "python")
        self.run_setup("--system-python")
        self.assertTrue(self.package_available(target / "bin" / "python"))
        self.assertTrue((self.root / ".dev-setup" / "backend-system").is_file())
        self.assertFalse((target / MARKER).exists())
        self.assertFalse(self.venv.exists())
        self.assertIn("up to date", self.run_setup("--system-python", "--check"))
