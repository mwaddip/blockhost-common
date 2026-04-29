"""Deprecated shim around the network-plugin dispatcher.

The mode-aware ``get_connection_endpoint(vm, ip, mode)`` /
``cleanup(vm, mode)`` API was replaced by the per-VM
``blockhost-network-hook`` CLI and the ``blockhost.network`` Python
module — see ``facts/NETWORK_INTERFACE.md`` and
``COMMON_INTERFACE.md §6a``.

This module remains so engines that haven't migrated yet keep working.
Each call emits a ``DeprecationWarning`` and forwards to the dispatcher,
which resolves the mode from vm-db (the ``mode`` argument is honoured
but no longer authoritative).
"""

import warnings

from .network import (
    DispatchError,
    dispatch_mode,
    dispatch_vm,
    get_connection_endpoint_via_dispatcher,
)


def _warn(name: str) -> None:
    warnings.warn(
        f"blockhost.network_hook.{name} is deprecated; call "
        f"blockhost-network-hook (CLI) or blockhost.network (Python) instead.",
        DeprecationWarning,
        stacklevel=3,
    )


def get_connection_endpoint(vm_name: str, bridge_ip: str, mode: str) -> str:
    """Return the subscriber-facing host for a VM (deprecated).

    ``bridge_ip`` and ``mode`` are accepted for signature compatibility but
    no longer used: dispatch resolves the mode from ``vm-db.network_mode``
    and the plugin owns the address-resolution logic. If a plugin can't
    determine an address it raises — there is no bridge_ip fallback.
    """
    _warn("get_connection_endpoint")
    return get_connection_endpoint_via_dispatcher(vm_name)


def cleanup(vm_name: str, mode: str) -> None:
    """Release per-VM network resources (deprecated).

    ``mode`` is accepted for signature compatibility but ignored — the
    dispatcher resolves the mode from vm-db. A plugin that doesn't
    implement ``cleanup`` is treated as a no-op so callers in modes
    without per-VM teardown (manual) don't crash.
    """
    _warn("cleanup")
    try:
        dispatch_vm("cleanup", vm_name)
    except DispatchError as e:
        # Plugins without a cleanup command (e.g. manual) used to be a
        # silent no-op in the old hard-coded shim. Preserve that.
        if "does not implement" in str(e):
            return
        raise


__all__ = ["get_connection_endpoint", "cleanup"]
