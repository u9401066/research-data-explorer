import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from rde.infrastructure.persistence import durability
from rde.interface.mcp.research_execution import _bytes_once
from rde.interface.mcp.research_plans import read_sealed, write_once


def test_windows_receipts_preserve_unicode_bytes_and_immutable_replay(tmp_path, monkeypatch):
    monkeypatch.setattr(durability, "sys", SimpleNamespace(platform="win32"))
    real_open = os.open

    def deny_directory(path, *args, **kwargs):
        if os.path.isdir(path):
            raise PermissionError("Windows does not expose directory handles this way")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", deny_directory)
    path = tmp_path / "計畫" / "receipt.json"
    original = write_once(path, {"question": "研究定義", "n": 12})
    assert read_sealed(path) == original
    assert write_once(path, original["payload"]) == original
    with pytest.raises(ValueError, match="IMMUTABLE_RECORD"):
        write_once(path, {"n": 13})
    evidence = tmp_path / "protocol.json"
    content = "原始 UTF-8\r\n".encode()
    _bytes_once(evidence, content)
    durability.sync_existing_file(evidence)
    assert evidence.read_bytes() == content
    with pytest.raises(ValueError, match="IMMUTABLE_RECORD"):
        _bytes_once(evidence, content + b"modified")
    assert not list(tmp_path.rglob("*.tmp"))


def test_windows_existing_file_flush_opens_writable_without_truncation(tmp_path, monkeypatch):
    monkeypatch.setattr(durability, "sys", SimpleNamespace(platform="win32"))
    path = tmp_path / "receipt"
    content = b"\x00evidence\xff"
    path.write_bytes(content)
    real_open = type(path).open
    observed = []

    def checked_open(self, mode="r", *args, **kwargs):
        observed.append(mode)
        if mode == "rb":
            raise OSError("read-only Windows flush handle")
        return real_open(self, mode, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(type(path), "open", checked_open)
        durability.sync_existing_file(path)
    assert observed == ["r+b"]
    assert path.read_bytes() == content


def test_posix_directory_sync_errors_propagate_and_handle_closes(monkeypatch, tmp_path):
    monkeypatch.setattr(durability, "sys", SimpleNamespace(platform="linux"))
    fake = SimpleNamespace(
        O_RDONLY=0,
        open=Mock(return_value=123),
        fsync=Mock(side_effect=OSError("disk failure")),
        close=Mock(),
    )
    monkeypatch.setattr(durability, "os", fake)
    with pytest.raises(OSError, match="disk failure"):
        durability.sync_directory(tmp_path)
    fake.close.assert_called_once_with(123)
