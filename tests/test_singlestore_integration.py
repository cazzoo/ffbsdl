import os
import subprocess
import sys
import unittest


class SingleStoreOptionalIntegrationTests(unittest.TestCase):
    """Basic smoke tests around the optional SingleStore integration.

    These tests are intentionally lightweight:
    - They do not require a running SingleStore instance.
    - They do not require the `singlestoredb` client library to be installed.
    The goal is simply to ensure that optional imports and CLI wiring behave
    sensibly in environments where the remote DB is not configured.
    """

    def test_require_client_raises_when_client_missing(self) -> None:
        """_require_client should raise when the underlying driver is missing.

        We simulate this by temporarily forcing `s2` to None, independent of
        whether the driver is actually installed in the test environment.
        """

        import scripts.singlestore_client as sc  # local import to avoid side effects at module import time

        original_s2 = getattr(sc, "s2", None)
        sc.s2 = None
        try:
            with self.assertRaises(sc.SingleStoreNotConfigured):
                sc._require_client()
        finally:
            sc.s2 = original_s2

    def test_run_usb_tests_help_succeeds(self) -> None:
        """The capture runner should print --help successfully.

        This exercises the optional import of `singlestore_client` and the
        argument parser wiring without needing any external tools.
        """

        proc = subprocess.run(
            [sys.executable, os.path.join("scripts", "run_usb_tests.py"), "--help"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertIn("--tests-file", proc.stdout)

    def test_analyze_usb_pcaps_help_succeeds(self) -> None:
        """The analysis script should print --help successfully.

        This ensures that the new SingleStore-related flags and imports do not
        break the basic CLI entry point.
        """

        proc = subprocess.run(
            [sys.executable, os.path.join("scripts", "analyze_usb_pcaps.py"), "--help"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertIn("--manifest", proc.stdout)


if __name__ == "__main__":
    unittest.main()

