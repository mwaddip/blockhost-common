"""Network-plugin dispatcher.

Resolves a VM's ``network_mode`` from vm-db and forwards the requested
subcommand to the corresponding plugin. Common ships only this dispatcher
— mode-specific logic (onion, broker, manual, none, …) lives in plugins
manifested at ``/etc/blockhost/network-modes.available/<mode>.json``.

Plugins follow the apache ``sites-available``/``sites-enabled`` pattern:

- ``/etc/blockhost/network-modes.available/`` holds every installed
  plugin manifest (one ``<mode>.json`` per plugin).
- ``/etc/blockhost/network-modes.enabled/`` holds symlinks pointing into
  ``available/``. Only enabled modes are dispatchable.

See ``facts/NETWORK_INTERFACE.md`` for the full plugin contract.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

from .vm_db import get_database


NETWORK_MODES_AVAILABLE_DIR = Path("/etc/blockhost/network-modes.available")
NETWORK_MODES_ENABLED_DIR = Path("/etc/blockhost/network-modes.enabled")


class DispatchError(Exception):
    """Raised when the dispatcher cannot resolve a plugin command."""


def _resolve_available_dir(available_dir: Optional[Path]) -> Path:
    if available_dir is not None:
        return available_dir
    return NETWORK_MODES_AVAILABLE_DIR


def _resolve_enabled_dir(enabled_dir: Optional[Path]) -> Path:
    if enabled_dir is not None:
        return enabled_dir
    return NETWORK_MODES_ENABLED_DIR


def _read_manifest_file(path: Path) -> dict:
    """Load and parse a manifest at ``path``. Raises DispatchError on failure."""
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise DispatchError(
            f"failed to read network plugin manifest {path}: {e}"
        )


def _enabled_manifest(mode: str, enabled_dir: Optional[Path] = None) -> dict:
    """Resolve a manifest via the enabled symlink.

    Raises DispatchError if the symlink is missing or dangling.
    """
    enabled_dir = _resolve_enabled_dir(enabled_dir)
    path = enabled_dir / f"{mode}.json"
    if not path.exists():
        raise DispatchError(f"mode '{mode}' not enabled")
    return _read_manifest_file(path)


def _available_manifest(mode: str, available_dir: Optional[Path] = None) -> dict:
    """Read a manifest directly from ``available/``.

    Raises DispatchError if the manifest is missing or unreadable. Used by
    ``enable`` to validate the new mode and read currently-enabled modes
    for exclusivity checks.
    """
    available_dir = _resolve_available_dir(available_dir)
    path = available_dir / f"{mode}.json"
    if not path.exists():
        raise DispatchError(
            f"mode '{mode}' not found in {available_dir}"
        )
    return _read_manifest_file(path)


def resolve_mode(vm_name: str) -> str:
    """Look up a VM's network_mode from vm-db. Raises DispatchError if absent."""
    vm = get_database().get_vm(vm_name)
    if vm is None:
        raise DispatchError(f"VM not found in vm-db: {vm_name}")
    mode = vm.get("network_mode")
    if not mode:
        raise DispatchError(
            f"VM '{vm_name}' has no network_mode field "
            f"(register_vm must populate it; see NETWORK_INTERFACE.md §6)"
        )
    return mode


def dispatch_vm(
    subcommand: str,
    vm_name: str,
    enabled_dir: Optional[Path] = None,
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
        enabled_dir=enabled_dir,
    )


def dispatch_mode(
    subcommand: str,
    mode: str,
    extra_argv: Optional[list] = None,
    extra_env: Optional[dict] = None,
    enabled_dir: Optional[Path] = None,
) -> int:
    """Exec a mode-keyed subcommand (e.g. pre-provision).

    Returns the plugin's exit code. stdout/stderr are forwarded.
    """
    manifest = _enabled_manifest(mode, enabled_dir)
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


def list_available(available_dir: Optional[Path] = None) -> list:
    """Return a sorted list of installed mode names.

    Reads ``available/<mode>.json`` filenames; returns ``[]`` if the
    directory is missing.
    """
    available_dir = _resolve_available_dir(available_dir)
    if not available_dir.is_dir():
        return []
    return sorted(p.stem for p in available_dir.glob("*.json"))


def list_enabled(enabled_dir: Optional[Path] = None) -> list:
    """Return a sorted list of enabled mode names.

    Reads ``enabled/<mode>.json`` entries; returns ``[]`` if the
    directory is missing. Includes dangling symlinks (the names are
    real even if the targets are not).
    """
    enabled_dir = _resolve_enabled_dir(enabled_dir)
    if not enabled_dir.is_dir():
        return []
    names = []
    for entry in enabled_dir.iterdir():
        if entry.suffix == ".json":
            names.append(entry.stem)
    return sorted(names)


def _check_exclusivity(new_manifest: dict, current_manifests: list) -> None:
    """Raise DispatchError if enabling ``new_manifest`` conflicts with any
    of ``current_manifests``.

    Pairwise rules from NETWORK_INTERFACE.md §4. Re-enabling the same
    mode is a no-op (the same name is filtered out).
    """
    new_name = new_manifest.get("name")
    new_excl = new_manifest.get("exclusive_with", [])
    if not isinstance(new_excl, list):
        raise DispatchError(
            f"manifest for '{new_name}' has invalid exclusive_with "
            f"(expected list, got {type(new_excl).__name__})"
        )

    for other in current_manifests:
        other_name = other.get("name")
        if other_name == new_name:
            continue
        other_excl = other.get("exclusive_with", [])
        if not isinstance(other_excl, list):
            continue

        if "*" in new_excl:
            raise DispatchError(
                f"cannot enable '{new_name}': it is exclusive with all "
                f"other modes (exclusive_with: '*'); '{other_name}' is "
                f"already enabled"
            )
        if "*" in other_excl:
            raise DispatchError(
                f"cannot enable '{new_name}': '{other_name}' is exclusive "
                f"with all other modes (exclusive_with: '*')"
            )
        if other_name in new_excl:
            raise DispatchError(
                f"cannot enable '{new_name}': it declares exclusivity "
                f"with '{other_name}', which is already enabled"
            )
        if new_name in other_excl:
            raise DispatchError(
                f"cannot enable '{new_name}': already-enabled "
                f"'{other_name}' declares exclusivity with it"
            )


def enable(
    mode: str,
    available_dir: Optional[Path] = None,
    enabled_dir: Optional[Path] = None,
) -> None:
    """Enable a mode by symlinking ``enabled/<mode>.json`` →
    ``../network-modes.available/<mode>.json``.

    Validates ``exclusive_with`` against currently-enabled modes. On
    conflict, raises DispatchError without touching the filesystem.

    Idempotent: enabling an already-enabled mode is a no-op (the existing
    symlink is left in place).
    """
    available_dir = _resolve_available_dir(available_dir)
    enabled_dir = _resolve_enabled_dir(enabled_dir)

    new_manifest = _available_manifest(mode, available_dir)

    enabled_dir.mkdir(parents=True, exist_ok=True)

    link_path = enabled_dir / f"{mode}.json"
    if link_path.exists() or link_path.is_symlink():
        return

    current = []
    for other_name in list_enabled(enabled_dir):
        if other_name == mode:
            continue
        try:
            current.append(_enabled_manifest(other_name, enabled_dir))
        except DispatchError:
            continue
    _check_exclusivity(new_manifest, current)

    target = Path("..") / available_dir.name / f"{mode}.json"
    os.symlink(target, link_path)


def disable(
    mode: str,
    enabled_dir: Optional[Path] = None,
) -> None:
    """Remove the symlink for ``mode`` in ``enabled/``.

    Idempotent: silently succeeds if the symlink does not exist.
    """
    enabled_dir = _resolve_enabled_dir(enabled_dir)
    link_path = enabled_dir / f"{mode}.json"
    if link_path.is_symlink() or link_path.exists():
        link_path.unlink()


# ---------------------------------------------------------------------------
# Backward-compat helpers
# ---------------------------------------------------------------------------

def get_connection_endpoint_via_dispatcher(
    vm_name: str,
    enabled_dir: Optional[Path] = None,
) -> str:
    """Resolve the public address by exec'ing the plugin's public-address command.

    Captures stdout (rather than streaming) so callers receive the address
    as a return value. Used by the deprecated ``blockhost.network_hook``
    shim and by anything that wants the address in-process.
    """
    mode = resolve_mode(vm_name)
    manifest = _enabled_manifest(mode, enabled_dir)
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
