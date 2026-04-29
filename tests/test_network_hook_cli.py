"""End-to-end tests for the blockhost-network-hook CLI."""

import os
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
CLI_PATH = REPO_ROOT / "usr" / "bin" / "blockhost-network-hook"
PKG_PATH = REPO_ROOT / "usr" / "lib" / "python3" / "dist-packages"


def _exec_cli(args, fallback_dir, net_dirs, vm_register=None):
    """Invoke the CLI's main() in a subprocess.

    Patches the in-process module-level constants so the CLI hits the
    test directories instead of /etc/blockhost. Also rebinds
    blockhost.network.get_database to a tmp-backed VMDatabase so the
    dispatcher's resolve_mode reads from the test instance.
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
        f"N.NETWORK_MODES_AVAILABLE_DIR = Path({str(net_dirs.available)!r})\n"
        f"N.NETWORK_MODES_ENABLED_DIR = Path({str(net_dirs.enabled)!r})\n"
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


def test_cli_help_lists_all_subcommands(fallback_dir, net_dirs):
    result = _exec_cli(["--help"], fallback_dir, net_dirs)
    assert result.returncode == 0
    out = result.stdout
    for sub in (
        "public-address", "push-vm-config", "cleanup",
        "pre-provision", "mode",
        "list-available", "list-enabled", "enable", "disable",
    ):
        assert sub in out, f"missing subcommand in help: {sub}"


def test_cli_help_no_removed_subcommands(fallback_dir, net_dirs):
    result = _exec_cli(["--help"], fallback_dir, net_dirs)
    assert result.returncode == 0
    for removed in ("host-setup", "host-teardown", "list-modes"):
        assert removed not in result.stdout, (
            f"removed subcommand still in CLI help: {removed}"
        )


def test_cli_list_available_empty(fallback_dir, net_dirs):
    result = _exec_cli(["list-available"], fallback_dir, net_dirs)
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_cli_list_available_emits_one_per_line(
    fallback_dir, net_dirs, make_plugin
):
    make_plugin("a", commands={}, enabled=False)
    make_plugin("b", commands={}, enabled=False)
    result = _exec_cli(["list-available"], fallback_dir, net_dirs)
    assert result.returncode == 0
    lines = [ln for ln in result.stdout.splitlines() if ln]
    assert lines == ["a", "b"]


def test_cli_list_enabled_empty(fallback_dir, net_dirs):
    result = _exec_cli(["list-enabled"], fallback_dir, net_dirs)
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_cli_list_enabled_after_enable(
    fallback_dir, net_dirs, make_plugin
):
    make_plugin("a", commands={}, enabled=True)
    make_plugin("b", commands={}, enabled=False)
    result = _exec_cli(["list-enabled"], fallback_dir, net_dirs)
    assert result.returncode == 0
    lines = [ln for ln in result.stdout.splitlines() if ln]
    assert lines == ["a"]


def test_cli_enable_creates_symlink(
    fallback_dir, net_dirs, make_plugin
):
    make_plugin("test", commands={}, enabled=False)
    result = _exec_cli(["enable", "test"], fallback_dir, net_dirs)
    assert result.returncode == 0, result.stderr
    assert (net_dirs.enabled / "test.json").is_symlink()


def test_cli_enable_idempotent(
    fallback_dir, net_dirs, make_plugin
):
    make_plugin("test", commands={}, enabled=True)
    result = _exec_cli(["enable", "test"], fallback_dir, net_dirs)
    assert result.returncode == 0, result.stderr


def test_cli_enable_conflict_preserves_existing(
    fallback_dir, net_dirs, make_plugin
):
    make_plugin("a", commands={}, exclusive_with=["*"], enabled=True)
    make_plugin("b", commands={}, exclusive_with=["*"], enabled=False)
    result = _exec_cli(["enable", "b"], fallback_dir, net_dirs)
    assert result.returncode == 1
    assert "exclusive" in result.stderr.lower()
    # 'a' is still enabled, 'b' did NOT get enabled
    assert (net_dirs.enabled / "a.json").is_symlink()
    assert not (net_dirs.enabled / "b.json").exists()


def test_cli_disable_removes_symlink(
    fallback_dir, net_dirs, make_plugin
):
    make_plugin("test", commands={}, enabled=True)
    result = _exec_cli(["disable", "test"], fallback_dir, net_dirs)
    assert result.returncode == 0, result.stderr
    assert not (net_dirs.enabled / "test.json").exists()


def test_cli_disable_idempotent(
    fallback_dir, net_dirs
):
    result = _exec_cli(["disable", "ghost"], fallback_dir, net_dirs)
    assert result.returncode == 0, result.stderr


def test_cli_public_address_dispatches(
    fallback_dir, net_dirs, make_plugin
):
    make_plugin("test", commands={"public-address": 'echo "test-addr"'})
    result = _exec_cli(
        ["public-address", "vm1"],
        fallback_dir,
        net_dirs,
        vm_register={
            "name": "vm1",
            "vmid": 100,
            "ip": "192.168.122.10",
            "network_mode": "test",
        },
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "test-addr"


def test_cli_missing_vm_record_exits_one(
    fallback_dir, net_dirs, make_plugin
):
    make_plugin("test", commands={"public-address": "echo foo"})
    result = _exec_cli(
        ["public-address", "ghost-vm"], fallback_dir, net_dirs
    )
    assert result.returncode == 1
    assert "VM not found" in result.stderr or "ghost-vm" in result.stderr


def test_cli_mode_subcommand(fallback_dir, net_dirs):
    result = _exec_cli(
        ["mode", "vm1"],
        fallback_dir,
        net_dirs,
        vm_register={
            "name": "vm1",
            "vmid": 100,
            "ip": "192.168.122.10",
            "network_mode": "broker",
        },
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "broker"


def test_cli_pre_provision_passes_plan_id(
    fallback_dir, net_dirs, make_plugin
):
    make_plugin(
        "test",
        commands={"pre-provision": 'echo "{\\"prefix\\":\\"plan=$BH_PLAN_ID\\"}"'},
    )
    result = _exec_cli(
        ["pre-provision", "test", "plan-99"], fallback_dir, net_dirs
    )
    assert result.returncode == 0, result.stderr
    assert "plan=plan-99" in result.stdout


def test_cli_forwards_plugin_exit_code(
    fallback_dir, net_dirs, make_plugin
):
    make_plugin("test", commands={"public-address": "exit 7"})
    result = _exec_cli(
        ["public-address", "vm1"],
        fallback_dir,
        net_dirs,
        vm_register={
            "name": "vm1",
            "vmid": 100,
            "ip": "192.168.122.10",
            "network_mode": "test",
        },
    )
    assert result.returncode == 7


def test_cli_mode_not_enabled_exits_one(
    fallback_dir, net_dirs
):
    """VM has network_mode=ghost but no symlink in enabled/."""
    result = _exec_cli(
        ["public-address", "vm1"],
        fallback_dir,
        net_dirs,
        vm_register={
            "name": "vm1",
            "vmid": 100,
            "ip": "192.168.122.10",
            "network_mode": "ghost",
        },
    )
    assert result.returncode == 1
    assert "not enabled" in result.stderr
