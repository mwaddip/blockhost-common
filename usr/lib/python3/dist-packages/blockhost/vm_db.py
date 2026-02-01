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

    # Reserve and mint NFT
    token_id = db.reserve_nft_token_id("web-001")
    db.mark_nft_minted(token_id, "0x...")
"""

import fcntl
import json
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from .config import load_db_config, load_broker_allocation, DATA_DIR


class VMDatabaseBase(ABC):
    """Abstract base class for VM database implementations."""

    @abstractmethod
    def get_expired_vms(self, grace_days: int = 0) -> list[dict]:
        """Get all VMs past their expiry date (plus optional grace period)."""
        pass

    @abstractmethod
    def get_vm(self, name: str) -> Optional[dict]:
        """Get a VM by name."""
        pass

    @abstractmethod
    def register_vm(
        self,
        name: str,
        vmid: int,
        ip: str,
        owner: str,
        expiry_days: int,
        purpose: str = "",
        wallet_address: Optional[str] = None,
    ) -> dict:
        """Register a new VM in the database."""
        pass

    @abstractmethod
    def mark_destroyed(self, name: str) -> None:
        """Mark a VM as destroyed."""
        pass

    @abstractmethod
    def allocate_ip(self) -> Optional[str]:
        """Allocate the next available IPv4 address."""
        pass

    @abstractmethod
    def allocate_ipv6(self) -> Optional[str]:
        """Allocate the next available IPv6 address."""
        pass

    @abstractmethod
    def allocate_vmid(self) -> int:
        """Allocate the next available VMID."""
        pass

    @abstractmethod
    def extend_expiry(self, name: str, days: int) -> None:
        """Extend a VM's expiry date by the specified number of days."""
        pass

    @abstractmethod
    def list_vms(self, status: Optional[str] = None) -> list[dict]:
        """List all VMs, optionally filtered by status."""
        pass

    @abstractmethod
    def reserve_nft_token_id(self, vm_name: str) -> int:
        """Reserve the next NFT token ID for a VM."""
        pass

    @abstractmethod
    def mark_nft_minted(self, token_id: int, owner_wallet: str) -> None:
        """Mark an NFT token as successfully minted."""
        pass

    @abstractmethod
    def mark_nft_failed(self, token_id: int) -> None:
        """Mark an NFT token reservation as failed."""
        pass

    @abstractmethod
    def get_nft_token(self, token_id: int) -> Optional[dict]:
        """Get NFT token info by ID."""
        pass


class VMDatabase(VMDatabaseBase):
    """JSON file-based VM database implementation."""

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
                self.config = yaml.safe_load(f)
        else:
            self.config = load_db_config(fallback_dir)

        self.db_file = Path(self.config["db_file"])
        self.fields = self.config["fields"]
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
            self._write_db({
                "vms": {},
                "next_vmid": self.vmid_range["start"],
                "allocated_ips": [],
                "allocated_ipv6": [],
                "next_nft_token_id": 0,
                "nft_tokens": {},
            })

    def _read_db(self) -> dict:
        """Read the database file with shared lock."""
        with open(self.db_file, "r") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)
            try:
                return json.load(f)
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    def _write_db(self, data: dict) -> None:
        """Write to the database file with exclusive lock."""
        with open(self.db_file, "w") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                json.dump(data, f, indent=2, default=str)
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

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
        owner: str,
        expiry_days: int,
        purpose: str = "",
        wallet_address: Optional[str] = None,
    ) -> dict:
        """Register a new VM in the database."""
        db = self._read_db()

        if name in db["vms"]:
            raise ValueError(f"VM '{name}' already exists")

        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(days=expiry_days)

        vm = {
            self.fields["vm_name"]: name,
            self.fields["vmid"]: vmid,
            self.fields["ip_address"]: ip,
            self.fields["expires_at"]: expires_at.isoformat(),
            self.fields["owner"]: owner,
            self.fields["status"]: "active",
            self.fields["created_at"]: now.isoformat(),
            "purpose": purpose,
            "wallet_address": wallet_address,
        }

        db["vms"][name] = vm

        # Track allocated IP
        if ip not in db["allocated_ips"]:
            db["allocated_ips"].append(ip)

        # Update next_vmid if necessary
        if vmid >= db["next_vmid"]:
            db["next_vmid"] = vmid + 1

        self._write_db(db)
        return vm

    def mark_destroyed(self, name: str) -> None:
        """Mark a VM as destroyed and release its IPs."""
        db = self._read_db()

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

        self._write_db(db)

    def allocate_ip(self) -> Optional[str]:
        """Allocate the next available IPv4 address from the pool."""
        db = self._read_db()

        network_prefix = ".".join(self.ip_pool["network"].split(".")[:3])
        start = self.ip_pool["start"]
        end = self.ip_pool["end"]

        for i in range(start, end + 1):
            ip = f"{network_prefix}.{i}"
            if ip not in db["allocated_ips"]:
                db["allocated_ips"].append(ip)
                self._write_db(db)
                return ip

        return None  # Pool exhausted

    def allocate_ipv6(self) -> Optional[str]:
        """Allocate the next available IPv6 address from the pool."""
        if not self.ipv6_prefix:
            return None  # IPv6 not configured (no broker allocation)

        import ipaddress
        db = self._read_db()
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
                self._write_db(db)
                return ipv6

        return None  # Pool exhausted

    def release_ipv6(self, ipv6: str) -> None:
        """Release an IPv6 address back to the pool."""
        db = self._read_db()
        if ipv6 in db.get("allocated_ipv6", []):
            db["allocated_ipv6"].remove(ipv6)
            self._write_db(db)

    def allocate_vmid(self) -> int:
        """Allocate the next available VMID."""
        db = self._read_db()

        vmid = db["next_vmid"]
        if vmid > self.vmid_range["end"]:
            raise ValueError("VMID range exhausted")

        db["next_vmid"] = vmid + 1
        self._write_db(db)
        return vmid

    def extend_expiry(self, name: str, days: int) -> None:
        """Extend a VM's expiry date by the specified number of days."""
        db = self._read_db()

        if name not in db["vms"]:
            raise ValueError(f"VM '{name}' not found")

        vm = db["vms"][name]
        current_expiry = datetime.fromisoformat(
            vm["expires_at"].replace("Z", "+00:00")
        )
        new_expiry = current_expiry + timedelta(days=days)
        vm["expires_at"] = new_expiry.isoformat()

        self._write_db(db)

    def list_vms(self, status: Optional[str] = None) -> list[dict]:
        """List all VMs, optionally filtered by status."""
        db = self._read_db()
        vms = list(db["vms"].values())

        if status:
            vms = [vm for vm in vms if vm.get("status") == status]

        return vms

    def release_ip(self, ip: str) -> None:
        """Release an IP address back to the pool."""
        db = self._read_db()
        if ip in db["allocated_ips"]:
            db["allocated_ips"].remove(ip)
            self._write_db(db)

    def reserve_nft_token_id(self, vm_name: str) -> int:
        """Reserve the next NFT token ID for a VM."""
        db = self._read_db()
        db.setdefault("next_nft_token_id", 0)
        db.setdefault("nft_tokens", {})

        token_id = db["next_nft_token_id"]
        db["next_nft_token_id"] = token_id + 1
        db["nft_tokens"][str(token_id)] = {
            "status": "reserved",
            "vm_name": vm_name,
            "reserved_at": datetime.now(timezone.utc).isoformat(),
        }

        self._write_db(db)
        return token_id

    def mark_nft_minted(self, token_id: int, owner_wallet: str) -> None:
        """Mark an NFT token as successfully minted."""
        db = self._read_db()
        key = str(token_id)
        if key not in db.get("nft_tokens", {}):
            raise ValueError(f"NFT token {token_id} not found")

        db["nft_tokens"][key]["status"] = "minted"
        db["nft_tokens"][key]["owner_wallet"] = owner_wallet
        db["nft_tokens"][key]["minted_at"] = datetime.now(timezone.utc).isoformat()

        self._write_db(db)

    def mark_nft_failed(self, token_id: int) -> None:
        """Mark an NFT token reservation as failed."""
        db = self._read_db()
        key = str(token_id)
        if key not in db.get("nft_tokens", {}):
            raise ValueError(f"NFT token {token_id} not found")

        db["nft_tokens"][key]["status"] = "failed"
        db["nft_tokens"][key]["failed_at"] = datetime.now(timezone.utc).isoformat()

        self._write_db(db)

    def get_nft_token(self, token_id: int) -> Optional[dict]:
        """Get NFT token info by ID."""
        db = self._read_db()
        return db.get("nft_tokens", {}).get(str(token_id))


class MockVMDatabase(VMDatabaseBase):
    """Mock database for local development/testing."""

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
            mock_ipv6_prefix: Mock IPv6 prefix for testing (default: fd00:mock:test::/120)
        """
        if db_file is None:
            db_file = Path.cwd() / "mock-db.json"
        self.db_file = Path(db_file)

        # Load config for IP pool settings
        self.config = load_db_config(fallback_dir)
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
            self._write_db({
                "vms": {},
                "next_vmid": self.vmid_range["start"],
                "allocated_ips": [],
                "allocated_ipv6": [],
                "next_nft_token_id": 0,
                "nft_tokens": {},
            })

    def _read_db(self) -> dict:
        with open(self.db_file) as f:
            return json.load(f)

    def _write_db(self, data: dict) -> None:
        with open(self.db_file, "w") as f:
            json.dump(data, f, indent=2, default=str)

    def get_expired_vms(self, grace_days: int = 0) -> list[dict]:
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
        db = self._read_db()
        return db["vms"].get(name)

    def register_vm(
        self,
        name: str,
        vmid: int,
        ip: str,
        owner: str,
        expiry_days: int,
        purpose: str = "",
        wallet_address: Optional[str] = None,
    ) -> dict:
        db = self._read_db()

        if name in db["vms"]:
            raise ValueError(f"VM '{name}' already exists")

        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(days=expiry_days)

        vm = {
            "vm_name": name,
            "vmid": vmid,
            "ip_address": ip,
            "expires_at": expires_at.isoformat(),
            "owner": owner,
            "status": "active",
            "created_at": now.isoformat(),
            "purpose": purpose,
            "wallet_address": wallet_address,
        }

        db["vms"][name] = vm
        if ip not in db["allocated_ips"]:
            db["allocated_ips"].append(ip)
        if vmid >= db["next_vmid"]:
            db["next_vmid"] = vmid + 1

        self._write_db(db)
        return vm

    def mark_destroyed(self, name: str) -> None:
        db = self._read_db()
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

        self._write_db(db)

    def allocate_ip(self) -> Optional[str]:
        db = self._read_db()
        network_prefix = ".".join(self.ip_pool["network"].split(".")[:3])
        start = self.ip_pool["start"]
        end = self.ip_pool["end"]

        for i in range(start, end + 1):
            ip = f"{network_prefix}.{i}"
            if ip not in db["allocated_ips"]:
                db["allocated_ips"].append(ip)
                self._write_db(db)
                return ip
        return None

    def allocate_ipv6(self) -> Optional[str]:
        """Allocate the next available IPv6 address from the pool."""
        if not self.ipv6_prefix:
            return None  # IPv6 not configured

        import ipaddress
        db = self._read_db()
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
                self._write_db(db)
                return ipv6

        return None  # Pool exhausted

    def allocate_vmid(self) -> int:
        db = self._read_db()
        vmid = db["next_vmid"]
        if vmid > self.vmid_range["end"]:
            raise ValueError("VMID range exhausted")
        db["next_vmid"] = vmid + 1
        self._write_db(db)
        return vmid

    def extend_expiry(self, name: str, days: int) -> None:
        db = self._read_db()
        if name not in db["vms"]:
            raise ValueError(f"VM '{name}' not found")

        vm = db["vms"][name]
        current_expiry = datetime.fromisoformat(
            vm["expires_at"].replace("Z", "+00:00")
        )
        new_expiry = current_expiry + timedelta(days=days)
        vm["expires_at"] = new_expiry.isoformat()
        self._write_db(db)

    def list_vms(self, status: Optional[str] = None) -> list[dict]:
        db = self._read_db()
        vms = list(db["vms"].values())
        if status:
            vms = [vm for vm in vms if vm.get("status") == status]
        return vms

    def reserve_nft_token_id(self, vm_name: str) -> int:
        db = self._read_db()
        db.setdefault("next_nft_token_id", 0)
        db.setdefault("nft_tokens", {})

        token_id = db["next_nft_token_id"]
        db["next_nft_token_id"] = token_id + 1
        db["nft_tokens"][str(token_id)] = {
            "status": "reserved",
            "vm_name": vm_name,
            "reserved_at": datetime.now(timezone.utc).isoformat(),
        }

        self._write_db(db)
        return token_id

    def mark_nft_minted(self, token_id: int, owner_wallet: str) -> None:
        db = self._read_db()
        key = str(token_id)
        if key not in db.get("nft_tokens", {}):
            raise ValueError(f"NFT token {token_id} not found")

        db["nft_tokens"][key]["status"] = "minted"
        db["nft_tokens"][key]["owner_wallet"] = owner_wallet
        db["nft_tokens"][key]["minted_at"] = datetime.now(timezone.utc).isoformat()
        self._write_db(db)

    def mark_nft_failed(self, token_id: int) -> None:
        db = self._read_db()
        key = str(token_id)
        if key not in db.get("nft_tokens", {}):
            raise ValueError(f"NFT token {token_id} not found")

        db["nft_tokens"][key]["status"] = "failed"
        db["nft_tokens"][key]["failed_at"] = datetime.now(timezone.utc).isoformat()
        self._write_db(db)

    def get_nft_token(self, token_id: int) -> Optional[dict]:
        db = self._read_db()
        return db.get("nft_tokens", {}).get(str(token_id))


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
