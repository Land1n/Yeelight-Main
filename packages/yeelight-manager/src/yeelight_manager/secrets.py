"""Protected local storage for the manager token.

Windows uses DPAPI (per-user encryption).  POSIX systems use a file with mode
``0600`` inside a ``0700`` directory.  The token is never written to logs, the
state file or command output.
"""

from __future__ import annotations

import base64
import ctypes
import os
import stat
import tempfile
from ctypes import wintypes
from pathlib import Path

DPAPI_HEADER = b"YELM-DPAPI-1\n"
PLAIN_HEADER = b"YELM-PLAIN-1\n"
CRYPTPROTECT_UI_FORBIDDEN = 0x01


class SecretError(RuntimeError):
    pass


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


def _blob(data: bytes) -> tuple[_DataBlob, ctypes.Array]:
    buffer = ctypes.create_string_buffer(data, max(1, len(data)))
    return _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer


def _dpapi_protect(data: bytes) -> bytes:
    crypt32 = ctypes.windll.crypt32  # type: ignore[attr-defined]
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        wintypes.LPCWSTR,
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    blob_in, _buffer = _blob(data)
    blob_out = _DataBlob()
    if not crypt32.CryptProtectData(
        ctypes.byref(blob_in),
        "Yeelight Manager token",
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(blob_out),
    ):
        raise SecretError(f"DPAPI encryption failed (error {ctypes.GetLastError()})")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def _dpapi_unprotect(data: bytes) -> bytes:
    crypt32 = ctypes.windll.crypt32  # type: ignore[attr-defined]
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    blob_in, _buffer = _blob(data)
    blob_out = _DataBlob()
    description = wintypes.LPWSTR()
    if not crypt32.CryptUnprotectData(
        ctypes.byref(blob_in),
        ctypes.byref(description),
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(blob_out),
    ):
        raise SecretError(
            f"DPAPI decryption failed (error {ctypes.GetLastError()})"
        )
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)
        if description:
            kernel32.LocalFree(description)


def _ensure_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        try:
            os.chmod(path, 0o700)
        except OSError:
            pass


def _atomic_write(path: Path, data: bytes) -> None:
    _ensure_private_dir(path.parent)
    descriptor, temporary = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if os.name != "nt":
            os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        if os.name != "nt":
            os.chmod(path, 0o600)
    finally:
        try:
            if os.path.exists(temporary):
                os.unlink(temporary)
        except OSError:
            pass


def save_token(path: Path, token: str) -> None:
    if not token.startswith("ylm_"):
        raise SecretError("Refusing to store an invalid manager token")
    raw = token.encode("utf-8")
    if os.name == "nt":
        payload = DPAPI_HEADER + base64.b64encode(_dpapi_protect(raw))
    else:
        payload = PLAIN_HEADER + raw
    _atomic_write(path, payload)


def load_token(path: Path) -> str | None:
    try:
        payload = path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise SecretError(f"Could not read the manager token: {exc}") from exc
    if payload.startswith(DPAPI_HEADER):
        if os.name != "nt":
            raise SecretError("This token was encrypted with Windows DPAPI")
        try:
            raw = _dpapi_unprotect(base64.b64decode(payload[len(DPAPI_HEADER) :]))
        except (ValueError, SecretError) as exc:
            raise SecretError("Could not decrypt the manager token with DPAPI") from exc
    elif payload.startswith(PLAIN_HEADER):
        raw = payload[len(PLAIN_HEADER) :]
        if os.name == "nt":
            raise SecretError("Refusing to use a plaintext token on Windows")
    else:
        raise SecretError("Unknown manager token format")
    try:
        token = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SecretError("Manager token is corrupted") from exc
    if not token.startswith("ylm_"):
        raise SecretError("Manager token is corrupted")
    if os.name != "nt":
        try:
            mode = stat.S_IMODE(path.stat().st_mode)
            if mode & 0o077:
                os.chmod(path, 0o600)
        except OSError:
            pass
    return token


def clear_token(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def token_fingerprint(token: str | None) -> str:
    if not token:
        return ""
    import hashlib

    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]


__all__ = [
    "SecretError",
    "clear_token",
    "load_token",
    "save_token",
    "token_fingerprint",
]
