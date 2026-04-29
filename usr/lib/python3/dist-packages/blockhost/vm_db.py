"""
VM Database Abstraction Layer

Provides a simple JSON-based database for tracking VM lifecycle,
IP allocation, NFT token management, and expiry management.

Usage:
    from blockhost.vm_db import get_database

    # Get database instance (uses /etc/blockhost/db.yaml config)
    db = get_database()

    # Allocate resources
    vmid = db.allocate_vmid()
    ip = db.allocate_ip()

    # Register a VM
    vm = db.register_vm(
        name="web-001",
        vmid=vmid,
        ip=ip,
        owner="admin",
        expiry_days=30,
        wallet_address="0x..."
    )

    # Record minted NFT on VM
    db.set_nft_minted("web-001", token_id=1)
"""

import fcntl
import json
import os
import tempfile
import warnings
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

from .config import CONFIG_DIR, load_db_config, load_broker_allocation


# Default database file path
DEFAULT_DB_FILE = "/var/lib/blockhost/vms.json"

# File the wizard writes at finalization with the operator-chosen network mode.
# Read as a fallback when register_vm is called without an explicit
# network_mode= during the rollout window (provisioners migrate first;
# common hard-rejects missing network_mode in a follow-up release).
NETWORK_MODE_FILE = CONFIG_DIR / "network-mode"

# Keys managed by other mutators — engines must not overwrite these
# via update_fields. Listed in the order they appear in the VM record
# schema (§2 in COMMON_INTERFACE.md). network_mode is included because
# it is set once at register_vm and immutable afterward.
RESERVED_FIELDS = frozenset({
    "vm_name", "vmid", "status", "created_at", "expires_at",
    "suspended_at", "destroyed_at", "ip_address", "ipv6_address",
    "nft_token_id", "nft_minted", "nft_minted_at", "network_mode",
})


def _resolve_network_mode_fallback() -> Optional[str]:
    """Read the wizard-written global network mode for the rollout window.

    Returns the trimmed file contents if present and non-empty, else None.
    """
    try:
        text = NETWORK_MODE_FILE.read_text().strip()
    except (OSError, FileNotFoundError):
        return None
    return text or None


def _normalize_ip_pool(ip_pool: dict) -> dict:
    """
    Normalize IP pool config to handle both formats:
    - Integer format: start: 200, end: 250 (last octet only)
    - String format: start: "192.168.122.200", end: "192.168.122.250" (full IP)

    Returns normalized dict with integer start/end (last octet only).
    """
    normalized = ip_pool.copy()

    # Handle start
    start = ip_pool.get("start", 200)
    if isinstance(start, str):
        # Extract last octet from full IP string
        normalized["start"] = int(start.split(".")[-1])
    else:
        normalized["start"] = int(start)

    # Handle end
    end = ip_pool.get("end", 250)
    if isinstance(end, str):
        # Extract last octet from full IP string
        normalized["end"] = int(end.split(".")[-1])
    else:
        normalized["end"] = int(end)

    return normalized


def _normalize_config(config: dict) -> dict:
    """
    Normalize database config to handle various formats.

    Handles:
    - vmid_range vs vmid_pool key names
    - IP pool start/end as integers or full IP strings
    - Optional db_file with default path
    """
    normalized = config.copy()

    # Accept both vmid_range and vmid_pool (None if neither is set)
    if "vmid_range" not in normalized and "vmid_pool" in normalized:
        normalized["vmid_range"] = normalized.pop("vmid_pool")
    elif "vmid_range" not in normalized:
        normalized["vmid_range"] = None

    # Normalize IP pool
    if "ip_pool" in normalized:
        normalized["ip_pool"] = _normalize_ip_pool(normalized["ip_pool"])
    else:
        normalized["ip_pool"] = {
            "network": "192.168.122.0/24",
            "start": 200,
            "end": 250,
            "gateway": "192.168.122.1",
        }

    # Default db_file
    if "db_file" not in normalized:
        normalized["db_file"] = DEFAULT_DB_FILE

    return normalized


class VMDatabaseBase(ABC):
    """Base class for VM database implementations.

    Subclasses must implement __init__, _read_db, and _atomic_update.
    All business logic lives here; subclasses only control storage and locking.
    """

    @abstractmethod
    def _read_db(self) -> dict:
        """Read and return the database contents."""
        pass

    @abstractmethod
    def _atomic_update(self, mutator: Callable[[dict], None]) -> dict:
        """Atomically read-modify-write the database.

        Acquires exclusive access, reads the DB, calls mutator(db_dict)
        which mutates the dict in place, then writes the result.

        Returns the database dict after mutation.
        """
        pass

    def get_expired_vms(self, grace_days: int = 0) -> list[dict]:
        """Get all VMs past their expiry date (plus optional grace period)."""
        db = self._read_db()
        now = datetime.now(timezone.utc)
        expired = []

        for vm in db["vms"].values():
            if vm.get("status") != "active":
                continue

            expires_at = datetime.fromisoformat(
                vm["expires_at"].replace("Z", "+00:00")
            )
            expiry_with_grace = expires_at + timedelta(days=grace_days)

            if now > expiry_with_grace:
                expired.append(vm)

        return expired

    def get_vm(self, name: str) -> Optional[dict]:
        """Get a VM by name."""
        db = self._read_db()
        return db["vms"].get(name)

    def register_vm(
        self,
        name: str,
        vmid: int,
        ip: str,
        ipv6: Optional[str] = None,
        owner: str = "",
        expiry_days: int = 30,
        purpose: str = "",
        wallet_address: Optional[str] = None,
        username: Optional[str] = None,
        network_mode: Optional[str] = None,
    ) -> dict:
        """Register a new VM in the database.

        Args:
            name: VM name (unique identifier)
            vmid: numeric VM identifier (provisioner-defined; 0 for libvirt)
            ip: IPv4 address
            ipv6: IPv6 address (optional)
            owner: Owner identifier
            expiry_days: Days until expiry
            purpose: Purpose description
            wallet_address: Owner's wallet address
            username: Linux username provisioned on the VM
            network_mode: Plugin name for ``/usr/share/blockhost/network/<mode>.json``
                (e.g. ``onion``, ``broker``, ``manual``). Required by the
                contract; passing ``None`` falls back to reading
                ``/etc/blockhost/network-mode`` and emits a
                ``DeprecationWarning`` for the rollout window. Empty string
                is rejected outright.
        """
        if network_mode is None:
            warnings.warn(
                "register_vm() without network_mode= is deprecated; "
                "provisioners must read /etc/blockhost/network-mode and "
                "pass it through. Falling back to the global file for now.",
                DeprecationWarning,
                stacklevel=2,
            )
            network_mode = _resolve_network_mode_fallback()
            if not network_mode:
                raise ValueError(
                    "register_vm requires network_mode (no fallback found at "
                    f"{NETWORK_MODE_FILE}). See NETWORK_INTERFACE.md §3."
                )
        elif not isinstance(network_mode, str) or not network_mode.strip():
            raise ValueError(
                "network_mode must be a non-empty string "
                "(see NETWORK_INTERFACE.md §3)"
            )

        result = [None]

        def mutator(db):
            if name in db["vms"]:
                raise ValueError(f"VM '{name}' already exists")

            now = datetime.now(timezone.utc)
            expires_at = now + timedelta(days=expiry_days)

            vm = {
                "vm_name": name,
                "vmid": vmid,
                "ip_address": ip,
                "ipv6_address": ipv6,
                "expires_at": expires_at.isoformat(),
                "owner": owner,
                "status": "active",
                "created_at": now.isoformat(),
                "purpose": purpose,
                "wallet_address": wallet_address,
                "username": username,
                "network_mode": network_mode,
            }

            db["vms"][name] = vm

            # Track allocated IPv4
            if ip not in db["allocated_ips"]:
                db["allocated_ips"].append(ip)

            # Track allocated IPv6
            if ipv6:
                db.setdefault("allocated_ipv6", [])
                if ipv6 not in db["allocated_ipv6"]:
                    db["allocated_ipv6"].append(ipv6)

            # Update next_vmid if necessary
            if vmid >= db["next_vmid"]:
                db["next_vmid"] = vmid + 1

            result[0] = vm

        self._atomic_update(mutator)
        return result[0]

    def mark_suspended(self, name: str) -> None:
        """Mark a VM as suspended (Phase 1 of garbage collection)."""

        def mutator(db):
            if name not in db["vms"]:
                raise ValueError(f"VM '{name}' not found")

            vm = db["vms"][name]
            vm["status"] = "suspended"
            vm["suspended_at"] = datetime.now(timezone.utc).isoformat()

        self._atomic_update(mutator)

    def mark_active(self, name: str, new_expiry: Optional[datetime] = None) -> None:
        """Mark a VM as active (reactivate a suspended VM)."""

        def mutator(db):
            if name not in db["vms"]:
                raise ValueError(f"VM '{name}' not found")

            vm = db["vms"][name]
            vm["status"] = "active"

            # Clear suspended_at
            if "suspended_at" in vm:
                del vm["suspended_at"]

            # Update expiry if provided
            if new_expiry is not None:
                vm["expires_at"] = new_expiry.isoformat()

        self._atomic_update(mutator)

    def mark_destroyed(self, name: str) -> None:
        """Mark a VM as destroyed and release its IPs (Phase 2 of garbage collection)."""

        def mutator(db):
            if name not in db["vms"]:
                raise ValueError(f"VM '{name}' not found")

            vm = db["vms"][name]
            vm["status"] = "destroyed"
            vm["destroyed_at"] = datetime.now(timezone.utc).isoformat()

            # Release IPv4
            ip = vm.get("ip_address")
            if ip and ip in db["allocated_ips"]:
                db["allocated_ips"].remove(ip)

            # Release IPv6
            ipv6 = vm.get("ipv6_address")
            if ipv6 and ipv6 in db.get("allocated_ipv6", []):
                db["allocated_ipv6"].remove(ipv6)

        self._atomic_update(mutator)

    def delete_vm(self, name: str) -> None:
        """Permanently remove a VM record from the database.

        Releases any IPv4/IPv6 allocations still attached to the record,
        so calling delete_vm without a prior mark_destroyed cleans up too.

        Raises:
            ValueError: If no record with that name exists.
        """

        def mutator(db):
            if name not in db["vms"]:
                raise ValueError(f"VM '{name}' not found")

            vm = db["vms"][name]

            ip = vm.get("ip_address")
            if ip and ip in db["allocated_ips"]:
                db["allocated_ips"].remove(ip)

            ipv6 = vm.get("ipv6_address")
            if ipv6 and ipv6 in db.get("allocated_ipv6", []):
                db["allocated_ipv6"].remove(ipv6)

            del db["vms"][name]

        self._atomic_update(mutator)

    def get_vms_to_suspend(self) -> list[dict]:
        """Get active VMs that have expired and are ready for suspension."""
        db = self._read_db()
        now = datetime.now(timezone.utc)
        to_suspend = []

        for vm in db["vms"].values():
            if vm.get("status") != "active":
                continue

            expires_at = datetime.fromisoformat(
                vm["expires_at"].replace("Z", "+00:00")
            )

            if now > expires_at:
                to_suspend.append(vm)

        return to_suspend

    def get_vms_to_destroy(self, grace_days: int) -> list[dict]:
        """Get suspended VMs past grace period that are ready for destruction."""
        db = self._read_db()
        now = datetime.now(timezone.utc)
        to_destroy = []

        for vm in db["vms"].values():
            if vm.get("status") != "suspended":
                continue

            suspended_at = vm.get("suspended_at")
            if not suspended_at:
                continue

            suspended_at = datetime.fromisoformat(
                suspended_at.replace("Z", "+00:00")
            )
            grace_expires = suspended_at + timedelta(days=grace_days)

            if now > grace_expires:
                to_destroy.append(vm)

        return to_destroy

    def allocate_ip(self) -> Optional[str]:
        """Allocate the next available IPv4 address from the pool."""
        result = [None]

        def mutator(db):
            network_prefix = ".".join(self.ip_pool["network"].split(".")[:3])
            start = self.ip_pool["start"]
            end = self.ip_pool["end"]

            for i in range(start, end + 1):
                ip = f"{network_prefix}.{i}"
                if ip not in db["allocated_ips"]:
                    db["allocated_ips"].append(ip)
                    result[0] = ip
                    return

        self._atomic_update(mutator)
        return result[0]

    def allocate_ipv6(self) -> Optional[str]:
        """Allocate the next available IPv6 address from the pool."""
        if not self.ipv6_prefix:
            return None  # IPv6 not configured (no broker allocation)

        import ipaddress
        result = [None]

        def mutator(db):
            db.setdefault("allocated_ipv6", [])

            # Parse prefix to get network base
            network = ipaddress.IPv6Network(self.ipv6_prefix, strict=False)
            base = int(network.network_address)

            start = self.ipv6_pool.get("start", 2)
            end = self.ipv6_pool.get("end", 254)

            for i in range(start, end + 1):
                ipv6 = str(ipaddress.IPv6Address(base + i))
                if ipv6 not in db["allocated_ipv6"]:
                    db["allocated_ipv6"].append(ipv6)
                    result[0] = ipv6
                    return

        self._atomic_update(mutator)
        return result[0]

    def allocate_vmid(self) -> int:
        """Allocate the next available VMID.

        Raises:
            RuntimeError: If vmid_range is not configured
            ValueError: If VMID range is exhausted
        """
        if not self.vmid_range:
            raise RuntimeError(
                "vmid_range not configured in db.yaml — "
                "set vmid_range.start and vmid_range.end, or let the provisioner configure it"
            )

        result = [None]

        def mutator(db):
            vmid = db["next_vmid"]
            if vmid > self.vmid_range["end"]:
                raise ValueError("VMID range exhausted")

            db["next_vmid"] = vmid + 1
            result[0] = vmid

        self._atomic_update(mutator)
        return result[0]

    def extend_expiry(self, name: str, days: int) -> None:
        """Extend a VM's expiry date by the specified number of days."""

        def mutator(db):
            if name not in db["vms"]:
                raise ValueError(f"VM '{name}' not found")

            vm = db["vms"][name]
            current_expiry = datetime.fromisoformat(
                vm["expires_at"].replace("Z", "+00:00")
            )
            new_expiry = current_expiry + timedelta(days=days)
            vm["expires_at"] = new_expiry.isoformat()

        self._atomic_update(mutator)

    def list_vms(self, status: Optional[str] = None) -> list[dict]:
        """List all VMs, optionally filtered by status."""
        db = self._read_db()
        vms = list(db["vms"].values())

        if status:
            vms = [vm for vm in vms if vm.get("status") == status]

        return vms

    def set_nft_minted(self, vm_name: str, token_id: int) -> None:
        """Record a minted NFT token on a VM record."""

        def mutator(db):
            if vm_name not in db["vms"]:
                raise ValueError(f"VM '{vm_name}' not found")
            db["vms"][vm_name]["nft_token_id"] = token_id
            db["vms"][vm_name]["nft_minted"] = True
            db["vms"][vm_name]["nft_minted_at"] = datetime.now(timezone.utc).isoformat()

        self._atomic_update(mutator)

    def update_fields(self, vm_name: str, fields: dict) -> bool:
        """Merge an arbitrary field dict into a VM record under the lockfile.

        Common does not know or validate what keys an engine writes — it
        just merges and persists. Engines pick names that fit their chain
        (e.g. cardano writes ``beacon_name``/``utxo_ref``).

        Returns ``False`` if ``vm_name`` is not in the DB (no exception);
        ``True`` on successful merge. The bool return — different from
        every other mutator's raise convention — lets engines call this
        after a chain commit without crashing on a concurrent deletion.

        Raises ``ValueError`` (before the lockfile is acquired) if
        ``fields`` contains any key that another mutator manages.
        """
        for key in fields:
            if key in RESERVED_FIELDS:
                raise ValueError(f"Cannot overwrite reserved key: {key!r}")

        result = [False]

        def mutator(db):
            if vm_name not in db["vms"]:
                return
            db["vms"][vm_name].update(fields)
            result[0] = True

        self._atomic_update(mutator)
        return result[0]


class VMDatabase(VMDatabaseBase):
    """JSON file-based VM database with fcntl file locking."""

    def __init__(
        self,
        config_path: Optional[str] = None,
        fallback_dir: Optional[Path] = None,
    ):
        """
        Initialize the database.

        Args:
            config_path: Path to db.yaml config file. If None, uses default location.
            fallback_dir: Optional fallback directory for config file lookup.
        """
        if config_path is not None:
            import yaml
            with open(config_path) as f:
                raw_config = yaml.safe_load(f)
        else:
            raw_config = load_db_config(fallback_dir)

        # Normalize config to handle various formats
        self.config = _normalize_config(raw_config)

        self.db_file = Path(self.config["db_file"])
        self.lock_file = Path(str(self.db_file) + ".lock")
        self.ip_pool = self.config["ip_pool"]
        self.vmid_range = self.config["vmid_range"]
        self.ipv6_pool = self.config.get("ipv6_pool", {"start": 2, "end": 254})

        # Load broker allocation for IPv6 prefix (may be None if not configured)
        broker_allocation = load_broker_allocation(fallback_dir)
        self.ipv6_prefix = broker_allocation.get("prefix") if broker_allocation else None

        # Ensure database directory exists
        self.db_file.parent.mkdir(parents=True, exist_ok=True)

        # Initialize empty database if it doesn't exist
        if not self.db_file.exists():
            initial_db = {
                "vms": {},
                "next_vmid": self.vmid_range["start"] if self.vmid_range else 0,
                "allocated_ips": [],
                "allocated_ipv6": [],
            }
            self._write_db_unlocked(initial_db)

    def _read_db(self) -> dict:
        """Read the database file with shared lock."""
        with open(self.db_file, "r") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)
            try:
                return json.load(f)
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    def _read_db_unlocked(self) -> dict:
        """Read the database file without locking (called within _atomic_update)."""
        with open(self.db_file, "r") as f:
            return json.load(f)

    def _write_db_unlocked(self, data: dict) -> None:
        """Write database via temp file + rename (called within _atomic_update)."""
        fd, tmp_path = tempfile.mkstemp(
            dir=str(self.db_file.parent), suffix='.tmp'
        )
        try:
            with os.fdopen(fd, 'w') as f:
                json.dump(data, f, indent=2, default=str)
            os.rename(tmp_path, str(self.db_file))
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def _atomic_update(self, mutator: Callable[[dict], None]) -> dict:
        """Atomically read-modify-write with exclusive lockfile."""
        with open(self.lock_file, "a") as lf:
            fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
            try:
                db = self._read_db_unlocked()
                mutator(db)
                self._write_db_unlocked(db)
                return db
            finally:
                fcntl.flock(lf.fileno(), fcntl.LOCK_UN)

    def release_ip(self, ip: str) -> None:
        """Release an IP address back to the pool."""

        def mutator(db):
            if ip in db["allocated_ips"]:
                db["allocated_ips"].remove(ip)

        self._atomic_update(mutator)

    def release_ipv6(self, ipv6: str) -> None:
        """Release an IPv6 address back to the pool."""

        def mutator(db):
            if ipv6 in db.get("allocated_ipv6", []):
                db["allocated_ipv6"].remove(ipv6)

        self._atomic_update(mutator)


class MockVMDatabase(VMDatabaseBase):
    """Mock database for local development/testing (no file locking)."""

    def __init__(
        self,
        db_file: Optional[str] = None,
        fallback_dir: Optional[Path] = None,
        mock_ipv6_prefix: Optional[str] = "fd00::/120",
    ):
        """
        Initialize mock database.

        Args:
            db_file: Path to mock database file
            fallback_dir: Fallback directory for config lookup
            mock_ipv6_prefix: Mock IPv6 prefix for testing (default: fd00::/120)
        """
        if db_file is None:
            db_file = Path.cwd() / "mock-db.json"
        self.db_file = Path(db_file)

        # Load and normalize config for IP pool settings
        raw_config = load_db_config(fallback_dir)
        self.config = _normalize_config(raw_config)
        self.ip_pool = self.config["ip_pool"]
        self.vmid_range = self.config["vmid_range"]
        self.ipv6_pool = self.config.get("ipv6_pool", {"start": 2, "end": 254})

        # Use mock prefix for testing, or try to load real broker allocation
        if mock_ipv6_prefix:
            self.ipv6_prefix = mock_ipv6_prefix
        else:
            broker_allocation = load_broker_allocation(fallback_dir)
            self.ipv6_prefix = broker_allocation.get("prefix") if broker_allocation else None

        if not self.db_file.exists():
            initial_db = {
                "vms": {},
                "next_vmid": self.vmid_range["start"] if self.vmid_range else 0,
                "allocated_ips": [],
                "allocated_ipv6": [],
            }
            self._write_db(initial_db)

    def _read_db(self) -> dict:
        with open(self.db_file) as f:
            return json.load(f)

    def _write_db(self, data: dict) -> None:
        with open(self.db_file, "w") as f:
            json.dump(data, f, indent=2, default=str)

    def _atomic_update(self, mutator: Callable[[dict], None]) -> dict:
        """Passthrough atomic update for mock (no locking needed)."""
        db = self._read_db()
        mutator(db)
        self._write_db(db)
        return db


def get_database(
    use_mock: bool = False,
    config_path: Optional[str] = None,
    fallback_dir: Optional[Path] = None,
) -> VMDatabaseBase:
    """
    Factory function to get the appropriate database implementation.

    Args:
        use_mock: If True, use mock database for local testing
        config_path: Optional path to db.yaml config
        fallback_dir: Optional fallback directory for config file lookup

    Returns:
        VMDatabaseBase implementation
    """
    if use_mock:
        return MockVMDatabase(fallback_dir=fallback_dir)
    return VMDatabase(config_path, fallback_dir)
