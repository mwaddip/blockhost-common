"""Shared pytest fixtures for blockhost-common tests."""

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

# Make the in-tree blockhost package importable without installing the .deb.
PKG_PATH = Path(__file__).resolve().parent.parent / "usr" / "lib" / "python3" / "dist-packages"
if str(PKG_PATH) not in sys.path:
    sys.path.insert(0, str(PKG_PATH))

import pytest


@pytest.fixture
def fallback_dir(tmp_path):
    """A temp directory holding a minimal db.yaml + broker-allocation.json.

    Returned path is suitable for passing as ``fallback_dir=`` to the
    config / vm-db loaders, so tests don't depend on /etc/blockhost.
    """
    (tmp_path / "db.yaml").write_text(
        "db_file: " + str(tmp_path / "vms.json") + "\n"
        "ip_pool:\n"
        "  network: \"192.168.122.0/24\"\n"
        "  start: 200\n"
        "  end: 250\n"
        "  gateway: \"192.168.122.1\"\n"
        "ipv6_pool:\n"
        "  start: 2\n"
        "  end: 254\n"
        "default_expiry_days: 30\n"
        "gc_grace_days: 7\n"
    )
    return tmp_path


@pytest.fixture
def db(fallback_dir, monkeypatch):
    """A real VMDatabase pointing at a tmp_path-backed vms.json + lockfile.

    Also monkeypatches ``blockhost.network.get_database`` so the
    dispatcher's ``resolve_mode`` reads from the same instance instead
    of trying to load ``/etc/blockhost/db.yaml``.
    """
    from blockhost.vm_db import VMDatabase
    instance = VMDatabase(fallback_dir=fallback_dir)
    import blockhost.network as N
    monkeypatch.setattr(N, "get_database", lambda: instance)
    return instance


@dataclass
class NetDirs:
    available: Path
    enabled: Path


@pytest.fixture
def net_dirs(tmp_path, monkeypatch):
    """Empty network-modes.available/ and network-modes.enabled/ dirs.

    Patched into ``blockhost.network`` module-level constants so both
    in-process calls and tests that don't pass dirs explicitly hit
    these paths.
    """
    avail = tmp_path / "network-modes.available"
    enabled = tmp_path / "network-modes.enabled"
    avail.mkdir()
    enabled.mkdir()
    import blockhost.network as N
    monkeypatch.setattr(N, "NETWORK_MODES_AVAILABLE_DIR", avail)
    monkeypatch.setattr(N, "NETWORK_MODES_ENABLED_DIR", enabled)
    return NetDirs(available=avail, enabled=enabled)


@pytest.fixture
def make_plugin(net_dirs):
    """Factory for installing a fake plugin manifest + script.

    Writes the manifest to ``available/<name>.json``. By default also
    creates a symlink in ``enabled/`` so the plugin is dispatchable.
    Pass ``enabled=False`` for tests that exercise the enable/disable
    flow itself.

    Usage:
        path = make_plugin("test", commands={"public-address": "echo abc"})
        path = make_plugin("a", commands={}, exclusive_with=["*"], enabled=False)
    """
    def _make(
        name: str,
        commands: dict,
        enabled: bool = True,
        **manifest_extras,
    ) -> Path:
        cmds = {}
        for cmd_name, body in commands.items():
            script = net_dirs.available / f"{name}-{cmd_name}.sh"
            script.write_text(f"#!/bin/sh\n{body}\n")
            os.chmod(script, 0o755)
            cmds[cmd_name] = str(script)
        manifest = {
            "name": name,
            "display_name": manifest_extras.pop("display_name", name),
            "description": manifest_extras.pop("description", ""),
            "exclusive_with": manifest_extras.pop("exclusive_with", []),
            "commands": cmds,
        }
        for k, v in manifest_extras.items():
            manifest[k] = v
        manifest_path = net_dirs.available / f"{name}.json"
        manifest_path.write_text(json.dumps(manifest))
        if enabled:
            link_path = net_dirs.enabled / f"{name}.json"
            target = Path("..") / net_dirs.available.name / f"{name}.json"
            os.symlink(target, link_path)
        return manifest_path

    return _make
