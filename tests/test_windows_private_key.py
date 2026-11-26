import os

import pytest

from rde.infrastructure.adapters.privacy import _key


@pytest.mark.skipif(os.name != "nt", reason="NTFS native access control")
def test_rde_accepts_only_its_own_private_key(tmp_path, monkeypatch):
    key = tmp_path / "secure.key"
    monkeypatch.setenv("RDE_PRIVACY_KEY_FILE", str(key))
    assert len(_key()) == 32 and _key(create=False) == _key()
    broad = tmp_path / "inherited.key"
    broad.write_bytes(b"x" * 32)
    monkeypatch.setenv("RDE_PRIVACY_KEY_FILE", str(broad))
    with pytest.raises(ValueError, match="ACL"):
        _key()
    assert broad.read_bytes() == b"x" * 32
