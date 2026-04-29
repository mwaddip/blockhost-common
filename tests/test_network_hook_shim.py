"""Tests for the deprecated blockhost.network_hook shim."""

import warnings


def test_shim_get_connection_endpoint_emits_deprecation(
    db, make_plugin
):
    db.register_vm(
        name="vm1",
        vmid=100,
        ip="192.168.122.10",
        network_mode="test",
    )
    make_plugin("test", commands={"public-address": 'echo "addr.onion"'})

    from blockhost.network_hook import get_connection_endpoint
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        addr = get_connection_endpoint("vm1", "192.168.122.10", "onion")

    assert addr == "addr.onion"
    deprecations = [w for w in captured if issubclass(w.category, DeprecationWarning)]
    assert deprecations
    assert "get_connection_endpoint" in str(deprecations[0].message)


def test_shim_cleanup_silent_when_plugin_lacks_command(
    db, make_plugin
):
    """Old shim was a no-op for modes without per-VM teardown (manual);
    preserve that so engines that haven't migrated don't crash."""
    db.register_vm(
        name="vm1",
        vmid=100,
        ip="192.168.122.10",
        network_mode="manual",
    )
    make_plugin("manual", commands={"public-address": "echo a"})

    from blockhost.network_hook import cleanup
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        cleanup("vm1", "manual")  # Must not raise


def test_shim_cleanup_invokes_plugin_command(
    db, make_plugin, capfd
):
    db.register_vm(
        name="vm1",
        vmid=100,
        ip="192.168.122.10",
        network_mode="onion",
    )
    make_plugin("onion", commands={"cleanup": "echo CLEAN_RAN"})

    from blockhost.network_hook import cleanup
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        cleanup("vm1", "onion")
    out = capfd.readouterr().out
    assert "CLEAN_RAN" in out
