import os
import tempfile
import unittest
from pathlib import Path
from spectral_monitor.server import load_token


class ExternalMonitorServerSecurityTests(unittest.TestCase):
    def test_accepts_owner_only_token_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "token"
            path.write_text("x" * 48, encoding="utf-8")
            path.chmod(0o600)
            self.assertEqual(load_token(path), "x" * 48)

    def test_rejects_group_or_world_readable_token_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "token"
            path.write_text("x" * 48, encoding="utf-8")
            path.chmod(0o644)
            with self.assertRaises(PermissionError):
                load_token(path)

    def test_rejects_short_token(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "token"
            path.write_text("short", encoding="utf-8")
            path.chmod(0o600)
            with self.assertRaises(ValueError):
                load_token(path)


if __name__ == "__main__":
    unittest.main()
