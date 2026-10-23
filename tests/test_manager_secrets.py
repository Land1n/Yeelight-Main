from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from yeelight_manager.secrets import (
    SecretError,
    clear_token,
    load_token,
    save_token,
    token_fingerprint,
)


class SecretsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = Path(tempfile.mkdtemp())

    def _path(self, name: str = "token.bin") -> Path:
        return self.directory / name

    def test_roundtrip_on_windows_and_posix(self) -> None:
        token = "ylm_test_manager_token_1234567890"
        path = self._path()
        save_token(path, token)
        self.assertTrue(path.is_file())
        loaded = load_token(path)
        self.assertEqual(loaded, token)
        self.assertEqual(token_fingerprint(loaded), token_fingerprint(token))
        clear_token(path)
        self.assertFalse(path.is_file())
        self.assertIsNone(load_token(path))

    def test_load_missing_returns_none(self) -> None:
        self.assertIsNone(load_token(self._path("missing.bin")))

    def test_invalid_token_is_rejected(self) -> None:
        path = self._path()
        path.write_bytes(b"not-a-valid-token")
        with self.assertRaises(SecretError):
            load_token(path)

    def test_unknown_format_is_rejected(self) -> None:
        path = self._path()
        path.write_bytes(b"YELM-FOO-1\npayload")
        with self.assertRaises(SecretError):
            load_token(path)

    def test_refusing_invalid_prefix_on_save(self) -> None:
        path = self._path()
        with self.assertRaises(SecretError):
            save_token(path, "not-a-manager-token")

    def test_token_fingerprint(self) -> None:
        self.assertEqual(token_fingerprint(None), "")
        self.assertEqual(token_fingerprint(""), "")
        self.assertEqual(
            token_fingerprint("ylm_abcdef0123456789"),
            token_fingerprint("ylm_abcdef0123456789"),
        )

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI test")
    def test_dpapi_roundtrip_produces_header(self) -> None:
        path = self._path()
        save_token(path, "ylm_dpapi_token")
        payload = path.read_bytes()
        self.assertTrue(payload.startswith(b"YELM-DPAPI-1\n"))
        self.assertNotEqual(payload[len(b"YELM-DPAPI-1\n"):], b"ylm_dpapi_token")


if __name__ == "__main__":
    unittest.main()
