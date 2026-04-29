"""Tests for the blockhost.network plugin dispatcher."""

import json
import os
import subprocess
from pathlib import Path

import pytest


def test_list_modes_empty(plugins_dir):
    from blockhost.network import list_modes
    assert list_modes(plugins_dir) == []


def test_list_modes_missing_dir(tmp_path):
    from blockhost.network import list_modes
    assert list_modes(tmp_path / "does-not-exist") == []


def test_list_modes_returns_manifests(plugins_dir, make_plugin):
    make_plugin("test", commands={"public-address": "echo abc"},
                display_name="Test", description="A test plugin")
    make_plugin("other", commands={})

    from blockhost.network import list_modes
    modes = list_modes(plugins_dir)
    names = [m["name"] for m in modes]
    assert sorted(names) == ["other", "test"]


def test_list_modes_skips_invalid_json(plugins_dir):
    (plugins_dir / "broken.json").write_text("{not json")
    from blockhost.network import list_modes
    assert list_modes(plugins_dir) == []


def test_resolve_mode_missing_vm(db):
    from blockhost.network import resolve_mode, DispatchError
    with pytest.raises(DispatchError, match="VM not found"):
        resolve_mode("nonexistent")


def test_resolve_mode_missing_field_rejected(db):
    """A VM record with no network_mode (legacy) must be rejected."""
    db.register_vm(
        name="legacy",
        vmid=100,
        ip="192.168.122.10",
        network_mode="onion",
    )
    # Manually clobber the field to simulate a pre-migration record
    db._atomic_update(
        lambda d: d["vms"]["legacy"].__delitem__("network_mode")
    )

    from blockhost.network import resolve_mode, DispatchError
    with pytest.raises(DispatchError, match="no network_mode field"):
        resolve_mode("legacy")


def test_resolve_mode_returns_field(db):
    db.register_vm(
        name="vm1",
        vmid=100,
        ip="192.168.122.10",
        network_mode="onion",
    )
    from blockhost.network import resolve_mode
    assert resolve_mode("vm1") == "onion"


def test_dispatch_vm_missing_manifest(db, plugins_dir):
    """Resolved mode with no manifest under plugins_dir → DispatchError."""
    db.register_vm(
        name="vm1",
        vmid=100,
        ip="192.168.122.10",
        network_mode="ghost",
    )
    from blockhost.network import dispatch_vm, DispatchError
    with pytest.raises(DispatchError, match="manifest not found"):
        dispatch_vm("public-address", "vm1", plugins_dir=plugins_dir)


def test_dispatch_vm_subcommand_absent(db, plugins_dir, make_plugin):
    """Manifest present but lacks the subcommand → DispatchError."""
    db.register_vm(
        name="vm1",
        vmid=100,
        ip="192.168.122.10",
        network_mode="test",
    )
    make_plugin("test", commands={"public-address": "echo addr"})
    from blockhost.network import dispatch_vm, DispatchError
    with pytest.raises(DispatchError, match="does not implement 'cleanup'"):
        dispatch_vm("cleanup", "vm1", plugins_dir=plugins_dir)


def test_dispatch_vm_passes_env_var(db, plugins_dir, make_plugin, capfd):
    """BH_VM_NAME must be set in the plugin process's environment."""
    db.register_vm(
        name="vm-xyz",
        vmid=100,
        ip="192.168.122.10",
        network_mode="test",
    )
    make_plugin(
        "test",
        commands={"public-address": 'echo "name=$BH_VM_NAME arg1=$1"'},
    )

    from blockhost.network import dispatch_vm
    rc = dispatch_vm("public-address", "vm-xyz", plugins_dir=plugins_dir)
    assert rc == 0
    out = capfd.readouterr().out
    assert "name=vm-xyz" in out
    assert "arg1=vm-xyz" in out


def test_dispatch_vm_forwards_exit_code(db, plugins_dir, make_plugin):
    db.register_vm(
        name="vm1",
        vmid=100,
        ip="192.168.122.10",
        network_mode="test",
    )
    make_plugin("test", commands={"public-address": "exit 42"})

    from blockhost.network import dispatch_vm
    rc = dispatch_vm("public-address", "vm1", plugins_dir=plugins_dir)
    assert rc == 42


def test_dispatch_mode_passes_plan_env(plugins_dir, make_plugin, capfd):
    """pre-provision must receive BH_PLAN_ID + plan-id on argv."""
    make_plugin(
        "test",
        commands={"pre-provision": 'echo "plan=$BH_PLAN_ID arg1=$1"'},
    )
    from blockhost.network import dispatch_mode
    rc = dispatch_mode(
        "pre-provision",
        "test",
        extra_argv=["plan-42"],
        extra_env={"BH_PLAN_ID": "plan-42"},
        plugins_dir=plugins_dir,
    )
    assert rc == 0
    out = capfd.readouterr().out
    assert "plan=plan-42" in out
    assert "arg1=plan-42" in out


def test_get_connection_endpoint_via_dispatcher_captures_stdout(
    db, plugins_dir, make_plugin
):
    db.register_vm(
        name="vm1",
        vmid=100,
        ip="192.168.122.10",
        network_mode="test",
    )
    make_plugin("test", commands={"public-address": 'echo "xyz.onion"'})

    from blockhost.network import get_connection_endpoint_via_dispatcher
    addr = get_connection_endpoint_via_dispatcher("vm1", plugins_dir=plugins_dir)
    assert addr == "xyz.onion"


def test_get_connection_endpoint_via_dispatcher_propagates_failure(
    db, plugins_dir, make_plugin
):
    db.register_vm(
        name="vm1",
        vmid=100,
        ip="192.168.122.10",
        network_mode="test",
    )
    make_plugin("test", commands={"public-address": "exit 1"})

    from blockhost.network import (
        get_connection_endpoint_via_dispatcher,
        DispatchError,
    )
    with pytest.raises(DispatchError, match="public-address exited 1"):
        get_connection_endpoint_via_dispatcher("vm1", plugins_dir=plugins_dir)


def test_dispatch_vm_with_real_manifest_per_contract_example(
    db, plugins_dir, make_plugin, capfd
):
    """Mirrors the verification step in the prompt: a 'test' plugin whose
    public-address echoes 'test-addr', dispatched via a vm-db record with
    network_mode=test, prints test-addr and exits 0."""
    make_plugin("test", commands={"public-address": 'echo "test-addr"'})
    db.register_vm(
        name="example-vm",
        vmid=100,
        ip="192.168.122.10",
        network_mode="test",
    )

    from blockhost.network import dispatch_vm
    rc = dispatch_vm("public-address", "example-vm", plugins_dir=plugins_dir)
    out = capfd.readouterr().out
    assert rc == 0
    assert out.strip() == "test-addr"
