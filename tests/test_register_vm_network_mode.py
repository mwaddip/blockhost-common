"""Tests for register_vm's network_mode handling."""

import warnings

import pytest


def test_register_vm_with_network_mode_persists_field(db):
    vm = db.register_vm(
        name="vm1",
        vmid=100,
        ip="192.168.122.10",
        network_mode="onion",
    )
    assert vm["network_mode"] == "onion"
    assert db.get_vm("vm1")["network_mode"] == "onion"


def test_register_vm_empty_string_network_mode_rejected(db):
    with pytest.raises(ValueError, match="non-empty string"):
        db.register_vm(
            name="vm1",
            vmid=100,
            ip="192.168.122.10",
            network_mode="",
        )


def test_register_vm_whitespace_network_mode_rejected(db):
    with pytest.raises(ValueError, match="non-empty string"):
        db.register_vm(
            name="vm1",
            vmid=100,
            ip="192.168.122.10",
            network_mode="   ",
        )


def test_register_vm_none_network_mode_falls_back_to_global_file(db, tmp_path, monkeypatch):
    """During the rollout window, missing network_mode= reads
    /etc/blockhost/network-mode and emits DeprecationWarning."""
    fake_file = tmp_path / "network-mode"
    fake_file.write_text("broker\n")
    import blockhost.vm_db as vm_db_mod
    monkeypatch.setattr(vm_db_mod, "NETWORK_MODE_FILE", fake_file)

    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        vm = db.register_vm(
            name="vm1",
            vmid=100,
            ip="192.168.122.10",
        )
    assert vm["network_mode"] == "broker"
    deprecations = [w for w in captured if issubclass(w.category, DeprecationWarning)]
    assert deprecations, "expected DeprecationWarning"
    assert "network_mode" in str(deprecations[0].message)


def test_register_vm_none_network_mode_no_fallback_raises(db, tmp_path, monkeypatch):
    """If neither argument nor fallback file is set, registration fails."""
    nonexistent = tmp_path / "missing-network-mode"
    import blockhost.vm_db as vm_db_mod
    monkeypatch.setattr(vm_db_mod, "NETWORK_MODE_FILE", nonexistent)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        with pytest.raises(ValueError, match="requires network_mode"):
            db.register_vm(
                name="vm1",
                vmid=100,
                ip="192.168.122.10",
            )


def test_register_vm_none_network_mode_empty_fallback_raises(db, tmp_path, monkeypatch):
    """A whitespace-only fallback file is treated as missing."""
    fake_file = tmp_path / "network-mode"
    fake_file.write_text("   \n")
    import blockhost.vm_db as vm_db_mod
    monkeypatch.setattr(vm_db_mod, "NETWORK_MODE_FILE", fake_file)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        with pytest.raises(ValueError, match="requires network_mode"):
            db.register_vm(
                name="vm1",
                vmid=100,
                ip="192.168.122.10",
            )


def test_network_mode_is_reserved_field(db):
    """update_fields must reject attempts to overwrite network_mode."""
    db.register_vm(
        name="vm1",
        vmid=100,
        ip="192.168.122.10",
        network_mode="onion",
    )
    with pytest.raises(ValueError, match="reserved key.*network_mode"):
        db.update_fields("vm1", {"network_mode": "broker"})


def test_register_vm_records_all_required_schema_keys(db):
    vm = db.register_vm(
        name="vm1",
        vmid=100,
        ip="192.168.122.10",
        ipv6="2a11:6c7:f04:276::5",
        owner="alice",
        network_mode="onion",
        wallet_address="0x" + "a" * 40,
        username="alice",
    )
    for key in (
        "vm_name", "vmid", "ip_address", "ipv6_address",
        "status", "owner", "wallet_address", "username",
        "network_mode", "created_at", "expires_at",
    ):
        assert key in vm, f"missing key: {key}"
    assert vm["network_mode"] == "onion"
