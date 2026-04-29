"""Network-plugin dispatcher.

Resolves a VM's ``network_mode`` from vm-db and forwards the requested
subcommand to the corresponding plugin under
``/usr/share/blockhost/network/<mode>/``. Common ships only this dispatcher
— mode-specific logic (onion, broker, manual, none, …) lives in plugins
manifested at ``/usr/share/blockhost/network/<mode>.json``.

See ``facts/NETWORK_INTERFACE.md`` for the full plugin contract.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

from .vm_db import get_database


NETWORK_PLUGINS_DIR = Path("/usr/share/blockhost/network")


class DispatchError(Exception):
    """Raised when the dispatcher cannot resolve a plugin command."""


def _resolve_plugins_dir(plugins_dir: Optional[Path]) -> Path:
    """Honour an explicit override; fall back to the (possibly monkeypatched)
    module-level constant. Resolved at call time so tests can patch it."""
    if plugins_dir is not None:
        return plugins_dir
    return NETWORK_PLUGINS_DIR


def _read_manifest(mode: str, plugins_dir: Optional[Path] = None) -> dict:
    """Load and parse a plugin manifest. Raises DispatchError if missing/invalid."""
    plugins_dir = _resolve_plugins_dir(plugins_dir)
    manifest_path = plugins_dir / f"{mode}.json"
    if not manifest_path.exists():
        raise DispatchError(
            f"network plugin manifest not found: {manifest_path}"
        )
    try:
        with open(manifest_path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise DispatchError(
            f"failed to read network plugin manifest {manifest_path}: {e}"
        )


def resolve_mode(vm_name: str) -> str:
    """Look up a VM's network_mode from vm-db. Raises DispatchError if absent."""
    vm = get_database().get_vm(vm_name)
    if vm is None:
        raise DispatchError(f"VM not found in vm-db: {vm_name}")
    mode = vm.get("network_mode")
    if not mode:
        raise DispatchError(
            f"VM '{vm_name}' has no network_mode field "
            f"(register_vm must populate it; see NETWORK_INTERFACE.md §3)"
        )
    return mode


def dispatch_vm(
    subcommand: str,
    vm_name: str,
    plugins_dir: Optional[Path] = None,
) -> int:
    """Resolve a VM's mode and exec the plugin's subcommand.

    Forwards stdout/stderr/exit code from the plugin process unchanged.
    Sets BH_VM_NAME=<vm_name> in the plugin's environment and passes
    <vm_name> as argv[1].

    Returns the plugin's exit code.
    """
    mode = resolve_mode(vm_name)
    return dispatch_mode(
        subcommand,
        mode,
        extra_argv=[vm_name],
        extra_env={"BH_VM_NAME": vm_name},
        plugins_dir=plugins_dir,
    )


def dispatch_mode(
    subcommand: str,
    mode: str,
    extra_argv: Optional[list] = None,
    extra_env: Optional[dict] = None,
    plugins_dir: Optional[Path] = None,
) -> int:
    """Exec a mode-keyed subcommand (host-setup / host-teardown / pre-provision).

    Returns the plugin's exit code. stdout/stderr are forwarded.
    """
    manifest = _read_manifest(mode, plugins_dir)
    commands = manifest.get("commands", {})
    cmd_path = commands.get(subcommand)
    if not cmd_path:
        raise DispatchError(
            f"network plugin '{mode}' does not implement '{subcommand}'"
        )

    argv = [cmd_path]
    if extra_argv:
        argv.extend(extra_argv)

    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)

    result = subprocess.run(argv, env=env)
    return result.returncode


def list_modes(plugins_dir: Optional[Path] = None) -> list:
    """Return a sorted list of installed plugin manifests.

    Each entry: {"name", "display_name", "description", "package", ...}.
    Empty list if the plugins directory is missing or empty.
    """
    plugins_dir = _resolve_plugins_dir(plugins_dir)
    if not plugins_dir.is_dir():
        return []

    modes = []
    for path in sorted(plugins_dir.glob("*.json")):
        try:
            with open(path) as f:
                manifest = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(manifest, dict) and manifest.get("name"):
            modes.append(manifest)
    return modes


# ---------------------------------------------------------------------------
# Backward-compat helpers
# ---------------------------------------------------------------------------

def get_connection_endpoint_via_dispatcher(
    vm_name: str,
    plugins_dir: Optional[Path] = None,
) -> str:
    """Resolve the public address by exec'ing the plugin's public-address command.

    Captures stdout (rather than streaming) so callers receive the address
    as a return value. Used by the deprecated ``blockhost.network_hook``
    shim and by anything that wants the address in-process.
    """
    mode = resolve_mode(vm_name)
    manifest = _read_manifest(mode, plugins_dir)
    cmd_path = manifest.get("commands", {}).get("public-address")
    if not cmd_path:
        raise DispatchError(
            f"network plugin '{mode}' does not implement 'public-address'"
        )

    env = os.environ.copy()
    env["BH_VM_NAME"] = vm_name
    result = subprocess.run(
        [cmd_path, vm_name],
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        raise DispatchError(
            f"plugin '{mode}' public-address exited {result.returncode}"
        )
    return result.stdout.strip()
