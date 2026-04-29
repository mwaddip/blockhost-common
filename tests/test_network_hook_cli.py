"""End-to-end tests for the blockhost-network-hook CLI."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
CLI_PATH = REPO_ROOT / "usr" / "bin" / "blockhost-network-hook"
PKG_PATH = REPO_ROOT / "usr" / "lib" / "python3" / "dist-packages"


def _run_cli(*args, fallback_dir=None, plugins_dir=None, env_extra=None):
    """Run the CLI in a subprocess.

    Sets PYTHONPATH so the in-tree blockhost package is importable, plus
    BLOCKHOST_FALLBACK_DIR / BLOCKHOST_NETWORK_PLUGINS_DIR which the test
    overrides below honor (we monkeypatch via env-driven imports).
    """
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PKG_PATH) + os.pathsep + env.get("PYTHONPATH", "")
    if fallback_dir is not None:
        env["BLOCKHOST_TEST_FALLBACK_DIR"] = str(fallback_dir)
    if plugins_dir is not None:
        env["BLOCKHOST_TEST_PLUGINS_DIR"] = str(plugins_dir)
    if env_extra:
        env.update(env_extra)

    return subprocess.run(
        [sys.executable, str(CLI_PATH), *args],
        env=env,
        capture_output=True,
        text=True,
    )


# The CLI imports blockhost.network with the production /usr/share path.
# To run end-to-end without root, we exec the same logic via python -c
# below. The dispatcher Python tests already exercise the in-process
# resolver — these tests just confirm argparse wiring and exit-code
# propagation through the CLI's exception handling.


def _exec_cli(args, fallback_dir, plugins_dir, vm_register=None):
    """Invoke the CLI's main() in a subprocess.

    Patches:
      - blockhost.network.NETWORK_PLUGINS_DIR → tmp dir
      - blockhost.network.get_database → returns a tmp-backed instance
        (patching the reference *as imported by network.py* — patching
        blockhost.vm_db.get_database doesn't reach the bound name)
    """
    register_block = ""
    if vm_register:
        kwargs = ", ".join(
            f"{k}={v!r}" if isinstance(v, str) else f"{k}={v}"
            for k, v in vm_register.items()
        )
        register_block = f"_db.register_vm({kwargs})\n"

    cli_argv = [str(CLI_PATH), *args]
    code = (
        "import sys, runpy\n"
        "from pathlib import Path\n"
        f"sys.path.insert(0, {str(PKG_PATH)!r})\n"
        "import blockhost.network as N\n"
        "import blockhost.vm_db as VDB\n"
        f"N.NETWORK_PLUGINS_DIR = Path({str(plugins_dir)!r})\n"
        f"_db = VDB.VMDatabase(fallback_dir=Path({str(fallback_dir)!r}))\n"
        "N.get_database = lambda: _db\n"
        f"{register_block}"
        f"sys.argv = {cli_argv!r}\n"
        f"runpy.run_path({str(CLI_PATH)!r}, run_name='__main__')\n"
    )
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
    )


def test_cli_help_lists_all_subcommands(fallback_dir, plugins_dir):
    result = _exec_cli(["--help"], fallback_dir, plugins_dir)
    assert result.returncode == 0
    out = result.stdout
    for sub in (
        "public-address", "push-vm-config", "cleanup",
        "host-setup", "host-teardown", "pre-provision",
        "mode", "list-modes",
    ):
        assert sub in out, f"missing subcommand in help: {sub}"


def test_cli_list_modes_empty(fallback_dir, plugins_dir):
    result = _exec_cli(["list-modes"], fallback_dir, plugins_dir)
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_cli_list_modes_emits_one_json_per_line(
    fallback_dir, plugins_dir, make_plugin
):
    make_plugin("test", commands={"public-address": "echo a"})
    make_plugin("other", commands={})
    result = _exec_cli(["list-modes"], fallback_dir, plugins_dir)
    assert result.returncode == 0
    lines = [line for line in result.stdout.strip().split("\n") if line]
    assert len(lines) == 2
    parsed = [json.loads(line) for line in lines]
    names = sorted(p["name"] for p in parsed)
    assert names == ["other", "test"]


def test_cli_public_address_dispatches(
    fallback_dir, plugins_dir, make_plugin
):
    make_plugin("test", commands={"public-address": 'echo "test-addr"'})
    result = _exec_cli(
        ["public-address", "vm1"],
        fallback_dir,
        plugins_dir,
        vm_register={
            "name": "vm1",
            "vmid": 100,
            "ip": "192.168.122.10",
            "network_mode": "test",
        },
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "test-addr"


def test_cli_missing_network_mode_exits_nonzero(
    fallback_dir, plugins_dir, make_plugin
):
    make_plugin("test", commands={"public-address": "echo foo"})
    # Don't register the VM at all → resolve_mode raises VM-not-found
    result = _exec_cli(
        ["public-address", "ghost-vm"], fallback_dir, plugins_dir
    )
    assert result.returncode == 1
    assert "VM not found" in result.stderr or "ghost-vm" in result.stderr


def test_cli_mode_subcommand(fallback_dir, plugins_dir):
    result = _exec_cli(
        ["mode", "vm1"],
        fallback_dir,
        plugins_dir,
        vm_register={
            "name": "vm1",
            "vmid": 100,
            "ip": "192.168.122.10",
            "network_mode": "broker",
        },
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "broker"


def test_cli_host_setup_dispatches_without_vm_lookup(
    fallback_dir, plugins_dir, make_plugin
):
    make_plugin("test", commands={"host-setup": "echo HOST_SETUP_OK"})
    result = _exec_cli(
        ["host-setup", "test"], fallback_dir, plugins_dir
    )
    assert result.returncode == 0, result.stderr
    assert "HOST_SETUP_OK" in result.stdout


def test_cli_pre_provision_passes_plan_id(
    fallback_dir, plugins_dir, make_plugin
):
    make_plugin(
        "test",
        commands={"pre-provision": 'echo "{\\"prefix\\":\\"plan=$BH_PLAN_ID\\"}"'},
    )
    result = _exec_cli(
        ["pre-provision", "test", "plan-99"], fallback_dir, plugins_dir
    )
    assert result.returncode == 0, result.stderr
    assert "plan=plan-99" in result.stdout


def test_cli_forwards_plugin_exit_code(
    fallback_dir, plugins_dir, make_plugin
):
    make_plugin("test", commands={"public-address": "exit 7"})
    result = _exec_cli(
        ["public-address", "vm1"],
        fallback_dir,
        plugins_dir,
        vm_register={
            "name": "vm1",
            "vmid": 100,
            "ip": "192.168.122.10",
            "network_mode": "test",
        },
    )
    assert result.returncode == 7


def test_cli_missing_manifest_exits_one(
    fallback_dir, plugins_dir
):
    """VM has network_mode=ghost but no plugin file installed."""
    result = _exec_cli(
        ["public-address", "vm1"],
        fallback_dir,
        plugins_dir,
        vm_register={
            "name": "vm1",
            "vmid": 100,
            "ip": "192.168.122.10",
            "network_mode": "ghost",
        },
    )
    assert result.returncode == 1
    assert "manifest not found" in result.stderr
