"""Search-path semantics for blockhost.config loaders.

Specifically: when cwd is non-traversable, the relative-path dev fallback
(``Path("config")/...``) must not leak ``PermissionError`` out of common.
"""

import os
from pathlib import Path

import pytest

from blockhost.config import (
    BROKER_ALLOCATION_FILE,
    get_config_path,
    load_broker_allocation,
)


pytestmark = pytest.mark.skipif(
    os.geteuid() == 0,
    reason="root bypasses chmod permissions; can't reproduce EACCES on cwd",
)


def _isolate_config_dir(monkeypatch, missing_dir: Path) -> None:
    """Point CONFIG_DIR at a non-existent location so the /etc/blockhost
    search step doesn't accidentally match a real file on the dev machine.
    """
    import blockhost.config as cfg
    monkeypatch.setattr(cfg, "CONFIG_DIR", missing_dir)


def _enter_unreadable_cwd(tmp_path: Path, monkeypatch) -> Path:
    """chdir into a fresh dir, then strip all permissions on it so any
    cwd-relative path resolution raises EACCES. Returns the dir so the
    test can restore permissions in its finally block.
    """
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    monkeypatch.chdir(sandbox)
    os.chmod(sandbox, 0)
    return sandbox


def test_load_broker_allocation_returns_none_when_cwd_unreadable(
    tmp_path, monkeypatch,
):
    _isolate_config_dir(monkeypatch, tmp_path / "nonexistent-etc")
    sandbox = _enter_unreadable_cwd(tmp_path, monkeypatch)
    try:
        assert load_broker_allocation() is None
    finally:
        os.chmod(sandbox, 0o755)


def test_get_config_path_raises_filenotfound_when_cwd_unreadable(
    tmp_path, monkeypatch,
):
    _isolate_config_dir(monkeypatch, tmp_path / "nonexistent-etc")
    sandbox = _enter_unreadable_cwd(tmp_path, monkeypatch)
    try:
        with pytest.raises(FileNotFoundError):
            get_config_path("does-not-exist.yaml")
    finally:
        os.chmod(sandbox, 0o755)


def test_load_broker_allocation_returns_none_with_empty_fallback_and_unreadable_cwd(
    tmp_path, monkeypatch,
):
    """Empty fallback_dir + unreadable cwd: every search path either misses
    or raises PermissionError. The function must return None, not propagate.
    """
    _isolate_config_dir(monkeypatch, tmp_path / "nonexistent-etc")
    fallback = tmp_path / "fallback"
    fallback.mkdir()  # exists but contains no broker-allocation.json
    sandbox = _enter_unreadable_cwd(tmp_path, monkeypatch)
    try:
        assert load_broker_allocation(fallback_dir=fallback) is None
    finally:
        os.chmod(sandbox, 0o755)
