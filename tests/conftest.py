"""Shared pytest fixtures for blockhost-common tests."""

import os
import sys
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


@pytest.fixture
def plugins_dir(tmp_path, monkeypatch):
    """An empty plugins manifest dir; tests add plugins as needed.

    Patched into ``blockhost.network.NETWORK_PLUGINS_DIR`` so the shim
    (which doesn't accept an explicit plugins_dir) hits this dir too.
    """
    d = tmp_path / "network-plugins"
    d.mkdir()
    import blockhost.network as N
    monkeypatch.setattr(N, "NETWORK_PLUGINS_DIR", d)
    return d


@pytest.fixture
def make_plugin(plugins_dir):
    """Factory for installing a fake plugin manifest + script.

    Usage:
        path = make_plugin("test", commands={"public-address": "echo abc"})
    """
    def _make(name: str, commands: dict, **manifest_extras) -> Path:
        cmds = {}
        for cmd_name, body in commands.items():
            script = plugins_dir / f"{name}-{cmd_name}.sh"
            script.write_text(f"#!/bin/sh\n{body}\n")
            os.chmod(script, 0o755)
            cmds[cmd_name] = str(script)
        manifest = {
            "name": name,
            "display_name": manifest_extras.get("display_name", name),
            "description": manifest_extras.get("description", ""),
            "commands": cmds,
        }
        for k, v in manifest_extras.items():
            manifest.setdefault(k, v)
        manifest_path = plugins_dir / f"{name}.json"
        import json
        manifest_path.write_text(json.dumps(manifest))
        return manifest_path

    return _make
