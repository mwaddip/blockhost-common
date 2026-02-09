"""
Provisioner Dispatcher — discover and invoke the active provisioner.

Reads a provisioner manifest from a well-known path. One active provisioner
per host. Falls back to legacy hardcoded command names when no manifest exists.
"""

import json
import logging
import subprocess
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

MANIFEST_PATH = Path("/usr/share/blockhost/provisioner.json")

# Legacy command names — used when no manifest is installed (transition period)
LEGACY_COMMANDS = {
    "create":         "blockhost-vm-create",
    "destroy":        "blockhost-vm-destroy",
    "start":          "blockhost-vm-start",
    "stop":           "blockhost-vm-stop",
    "kill":           "blockhost-vm-kill",
    "status":         "blockhost-vm-status",
    "list":           "blockhost-vm-list",
    "metrics":        "blockhost-vm-metrics",
    "throttle":       "blockhost-vm-throttle",
    "build-template": "blockhost-build-template",
    "gc":             "blockhost-vm-gc",
    "resume":         "blockhost-vm-resume",
}


class ProvisionerDispatcher:
    """Dispatches commands to the active provisioner."""

    def __init__(self, manifest_path: Optional[Path] = None):
        self._manifest_path = manifest_path or MANIFEST_PATH
        self._manifest = self._load_manifest()

    def _load_manifest(self) -> dict:
        """Load the provisioner manifest, or return empty dict if missing."""
        if not self._manifest_path.exists():
            log.debug("No provisioner manifest at %s, using legacy commands", self._manifest_path)
            return {}
        try:
            with open(self._manifest_path) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            log.warning("Failed to load provisioner manifest: %s", e)
            return {}

    def get_command(self, verb: str) -> str:
        """Get the CLI command name for a provisioner verb."""
        commands = self._manifest.get("commands", LEGACY_COMMANDS)
        cmd = commands.get(verb)
        if not cmd:
            raise ValueError(f"Unknown provisioner command: {verb}")
        return cmd

    def run(self, verb: str, args: Optional[list[str]] = None, **kwargs) -> subprocess.CompletedProcess:
        """Run a provisioner command.

        Args:
            verb: Command verb (create, destroy, start, stop, etc.)
            args: Additional command-line arguments
            **kwargs: Passed to subprocess.run (capture_output, text, cwd, etc.)

        Returns:
            subprocess.CompletedProcess
        """
        cmd = [self.get_command(verb)] + (args or [])
        return subprocess.run(cmd, **kwargs)

    @property
    def name(self) -> str:
        """Provisioner name (e.g. 'proxmox')."""
        return self._manifest.get("name", "unknown")

    @property
    def display_name(self) -> str:
        """Human-readable provisioner name."""
        return self._manifest.get("display_name", "Unknown Provisioner")

    @property
    def version(self) -> str:
        return self._manifest.get("version", "0.0.0")

    @property
    def wizard_module(self) -> Optional[str]:
        """Python module path for the wizard Blueprint (e.g. 'blockhost.provisioner_proxmox.wizard')."""
        return self._manifest.get("setup", {}).get("wizard_module")

    @property
    def finalization_steps(self) -> list[str]:
        """Ordered list of finalization step IDs owned by this provisioner."""
        return self._manifest.get("setup", {}).get("finalization_steps", [])

    @property
    def first_boot_hook(self) -> Optional[str]:
        """Path to the provisioner's first-boot hook script."""
        return self._manifest.get("setup", {}).get("first_boot_hook")

    @property
    def session_key(self) -> str:
        """Flask session key for provisioner-specific config (e.g. 'proxmox')."""
        return self._manifest.get("config_keys", {}).get("session_key", "provisioner")

    @property
    def root_agent_actions(self) -> Optional[str]:
        """Path to root agent action module shipped by this provisioner."""
        return self._manifest.get("root_agent_actions")

    @property
    def is_loaded(self) -> bool:
        """True if a manifest was successfully loaded."""
        return bool(self._manifest)

    @property
    def manifest(self) -> dict:
        """Raw manifest dict (empty if not loaded)."""
        return self._manifest


# Module-level singleton — lazy-loaded
_dispatcher: Optional[ProvisionerDispatcher] = None


def get_provisioner() -> ProvisionerDispatcher:
    """Get the singleton ProvisionerDispatcher instance."""
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = ProvisionerDispatcher()
    return _dispatcher
