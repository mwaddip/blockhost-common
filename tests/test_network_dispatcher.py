"""Tests for the blockhost.network plugin dispatcher."""

import os
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# resolve_mode / dispatch resolution
# ---------------------------------------------------------------------------

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


def test_dispatch_vm_mode_not_enabled(db, net_dirs):
    """VM has a mode but no symlink in enabled/ → DispatchError."""
    db.register_vm(
        name="vm1",
        vmid=100,
        ip="192.168.122.10",
        network_mode="ghost",
    )
    from blockhost.network import dispatch_vm, DispatchError
    with pytest.raises(DispatchError, match="mode 'ghost' not enabled"):
        dispatch_vm("public-address", "vm1")


def test_dispatch_vm_dangling_symlink_rejected(db, net_dirs):
    """A symlink whose target is missing must be rejected as not-enabled."""
    db.register_vm(
        name="vm1",
        vmid=100,
        ip="192.168.122.10",
        network_mode="ghost",
    )
    target = Path("..") / net_dirs.available.name / "ghost.json"
    os.symlink(target, net_dirs.enabled / "ghost.json")

    from blockhost.network import dispatch_vm, DispatchError
    with pytest.raises(DispatchError, match="not enabled"):
        dispatch_vm("public-address", "vm1")


def test_dispatch_vm_subcommand_absent(db, make_plugin):
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
        dispatch_vm("cleanup", "vm1")


def test_dispatch_vm_passes_env_var(db, make_plugin, capfd):
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
    rc = dispatch_vm("public-address", "vm-xyz")
    assert rc == 0
    out = capfd.readouterr().out
    assert "name=vm-xyz" in out
    assert "arg1=vm-xyz" in out


def test_dispatch_vm_forwards_exit_code(db, make_plugin):
    db.register_vm(
        name="vm1",
        vmid=100,
        ip="192.168.122.10",
        network_mode="test",
    )
    make_plugin("test", commands={"public-address": "exit 42"})

    from blockhost.network import dispatch_vm
    rc = dispatch_vm("public-address", "vm1")
    assert rc == 42


def test_dispatch_mode_passes_plan_env(make_plugin, capfd):
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
    )
    assert rc == 0
    out = capfd.readouterr().out
    assert "plan=plan-42" in out
    assert "arg1=plan-42" in out


def test_dispatch_mode_rejects_disabled(make_plugin):
    """A mode that exists in available/ but isn't symlinked is undispatchable."""
    make_plugin("test", commands={"pre-provision": "echo ok"}, enabled=False)
    from blockhost.network import dispatch_mode, DispatchError
    with pytest.raises(DispatchError, match="not enabled"):
        dispatch_mode("pre-provision", "test")


def test_get_connection_endpoint_via_dispatcher_captures_stdout(
    db, make_plugin
):
    db.register_vm(
        name="vm1",
        vmid=100,
        ip="192.168.122.10",
        network_mode="test",
    )
    make_plugin("test", commands={"public-address": 'echo "xyz.onion"'})

    from blockhost.network import get_connection_endpoint_via_dispatcher
    addr = get_connection_endpoint_via_dispatcher("vm1")
    assert addr == "xyz.onion"


def test_get_connection_endpoint_via_dispatcher_propagates_failure(
    db, make_plugin
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
        get_connection_endpoint_via_dispatcher("vm1")


def test_dispatch_vm_with_real_manifest_per_contract_example(
    db, make_plugin, capfd
):
    """Mirrors the verification step in the prompt: a 'test' plugin whose
    public-address echoes 'addr', dispatched via a vm-db record with
    network_mode=test, prints addr and exits 0."""
    make_plugin("test", commands={"public-address": 'echo "addr"'})
    db.register_vm(
        name="example-vm",
        vmid=100,
        ip="192.168.122.10",
        network_mode="test",
    )

    from blockhost.network import dispatch_vm
    rc = dispatch_vm("public-address", "example-vm")
    out = capfd.readouterr().out
    assert rc == 0
    assert out.strip() == "addr"


# ---------------------------------------------------------------------------
# list_available / list_enabled
# ---------------------------------------------------------------------------

def test_list_available_empty(net_dirs):
    from blockhost.network import list_available
    assert list_available() == []


def test_list_available_missing_dir(monkeypatch, tmp_path):
    """A nonexistent available/ dir returns []."""
    import blockhost.network as N
    monkeypatch.setattr(
        N, "NETWORK_MODES_AVAILABLE_DIR", tmp_path / "no-such-dir"
    )
    assert N.list_available() == []


def test_list_available_returns_basenames(net_dirs, make_plugin):
    make_plugin("a", commands={}, enabled=False)
    make_plugin("b", commands={}, enabled=False)
    from blockhost.network import list_available
    assert list_available() == ["a", "b"]


def test_list_enabled_empty(net_dirs):
    from blockhost.network import list_enabled
    assert list_enabled() == []


def test_list_enabled_returns_basenames(net_dirs, make_plugin):
    make_plugin("a", commands={}, enabled=True)
    make_plugin("b", commands={}, enabled=False)
    from blockhost.network import list_enabled
    assert list_enabled() == ["a"]


def test_list_enabled_missing_dir(monkeypatch, tmp_path):
    import blockhost.network as N
    monkeypatch.setattr(
        N, "NETWORK_MODES_ENABLED_DIR", tmp_path / "no-such-dir"
    )
    assert N.list_enabled() == []


# ---------------------------------------------------------------------------
# enable / disable
# ---------------------------------------------------------------------------

def test_enable_creates_symlink(net_dirs, make_plugin):
    make_plugin("test", commands={"public-address": "echo a"}, enabled=False)
    from blockhost.network import enable, list_enabled
    enable("test")
    link = net_dirs.enabled / "test.json"
    assert link.is_symlink()
    assert link.resolve() == (net_dirs.available / "test.json").resolve()
    assert list_enabled() == ["test"]


def test_enable_uses_relative_symlink(net_dirs, make_plugin):
    make_plugin("test", commands={}, enabled=False)
    from blockhost.network import enable
    enable("test")
    link = net_dirs.enabled / "test.json"
    target = os.readlink(link)
    assert target == str(Path("..") / net_dirs.available.name / "test.json")


def test_enable_idempotent(net_dirs, make_plugin):
    make_plugin("test", commands={}, enabled=True)
    from blockhost.network import enable, list_enabled
    enable("test")
    assert list_enabled() == ["test"]


def test_enable_missing_manifest_errors(net_dirs):
    from blockhost.network import enable, DispatchError
    with pytest.raises(DispatchError, match="not found"):
        enable("ghost")


def test_enable_creates_enabled_dir_if_missing(monkeypatch, tmp_path):
    """If enabled/ doesn't exist yet, enable should create it."""
    avail = tmp_path / "available"
    enabled = tmp_path / "enabled"
    avail.mkdir()
    (avail / "test.json").write_text(
        '{"name": "test", "exclusive_with": [], "commands": {}}'
    )
    import blockhost.network as N
    monkeypatch.setattr(N, "NETWORK_MODES_AVAILABLE_DIR", avail)
    monkeypatch.setattr(N, "NETWORK_MODES_ENABLED_DIR", enabled)
    N.enable("test")
    assert enabled.is_dir()
    assert (enabled / "test.json").is_symlink()


def test_enable_star_exclusive_blocks_second(net_dirs, make_plugin):
    make_plugin("a", commands={}, exclusive_with=["*"], enabled=False)
    make_plugin("b", commands={}, exclusive_with=["*"], enabled=False)

    from blockhost.network import enable, DispatchError, list_enabled
    enable("a")
    with pytest.raises(DispatchError, match="exclusive"):
        enable("b")
    # 'a' must remain enabled — the failed enable does not perturb state
    assert list_enabled() == ["a"]


def test_enable_named_exclusive_blocks(net_dirs, make_plugin):
    make_plugin("a", commands={}, exclusive_with=["b"], enabled=False)
    make_plugin("b", commands={}, exclusive_with=[], enabled=False)

    from blockhost.network import enable, DispatchError
    enable("a")
    with pytest.raises(DispatchError, match="exclusivity"):
        enable("b")


def test_enable_named_exclusive_symmetric(net_dirs, make_plugin):
    """Declaring exclusive_with on the OTHER side still blocks."""
    make_plugin("a", commands={}, exclusive_with=[], enabled=False)
    make_plugin("b", commands={}, exclusive_with=["a"], enabled=False)

    from blockhost.network import enable, DispatchError
    enable("a")
    with pytest.raises(DispatchError, match="exclusivity"):
        enable("b")


def test_enable_compatible_modes_coexist(net_dirs, make_plugin):
    make_plugin("a", commands={}, exclusive_with=[], enabled=False)
    make_plugin("b", commands={}, exclusive_with=[], enabled=False)
    from blockhost.network import enable, list_enabled
    enable("a")
    enable("b")
    assert list_enabled() == ["a", "b"]


def test_disable_removes_symlink(net_dirs, make_plugin):
    make_plugin("test", commands={}, enabled=True)
    from blockhost.network import disable, list_enabled
    disable("test")
    assert list_enabled() == []


def test_disable_idempotent(net_dirs):
    from blockhost.network import disable
    disable("never-was-there")
    disable("never-was-there")  # second call must also succeed
