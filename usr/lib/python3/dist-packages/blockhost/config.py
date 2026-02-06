"""
Blockhost Configuration Module

Provides centralized path constants and configuration loading for all
Blockhost components. This module is the single source of truth for
directory locations and configuration file paths.

Usage:
    from blockhost.config import get_config_path, load_db_config

    # Get path to a config file (checks /etc/blockhost first)
    config_path = get_config_path("db.yaml")

    # Load configuration directly
    db_config = load_db_config()
    web3_config = load_web3_config()
"""

import json
import os
from pathlib import Path
from typing import Optional

import yaml


# =============================================================================
# Path Constants
# =============================================================================

# Primary configuration directory (installed by blockhost-common)
CONFIG_DIR = Path("/etc/blockhost")

# Data directory for runtime state (VM database, etc.)
DATA_DIR = Path("/var/lib/blockhost")

# Terraform working directory
TERRAFORM_DIR = DATA_DIR / "terraform"

# Key file paths
SERVER_KEY_FILE = CONFIG_DIR / "server.key"
DEPLOYER_KEY_FILE = CONFIG_DIR / "deployer.key"

# Database file path
DB_FILE = DATA_DIR / "vms.json"

# Configuration file names
DB_CONFIG_FILE = "db.yaml"
WEB3_CONFIG_FILE = "web3-defaults.yaml"
BLOCKHOST_CONFIG_FILE = "blockhost.yaml"
BROKER_ALLOCATION_FILE = "broker-allocation.json"


# =============================================================================
# Configuration Loading
# =============================================================================

def get_config_path(
    filename: str,
    fallback_dir: Optional[Path] = None,
) -> Path:
    """
    Get the path to a configuration file.

    Searches in order:
    1. /etc/blockhost/{filename}
    2. fallback_dir/{filename} (if provided)
    3. ./config/{filename} (for development)

    Args:
        filename: Name of the configuration file (e.g., "db.yaml")
        fallback_dir: Optional fallback directory for development

    Returns:
        Path to the configuration file

    Raises:
        FileNotFoundError: If the configuration file is not found
    """
    search_paths = [
        CONFIG_DIR / filename,
    ]

    if fallback_dir:
        search_paths.append(fallback_dir / filename)

    # Development fallback: look in ./config/
    search_paths.append(Path("config") / filename)

    for path in search_paths:
        if path.exists():
            return path

    raise FileNotFoundError(
        f"Configuration file '{filename}' not found. Searched:\n" +
        "\n".join(f"  - {p}" for p in search_paths)
    )


def load_config(
    filename: str,
    fallback_dir: Optional[Path] = None,
) -> dict:
    """
    Load a YAML configuration file.

    Args:
        filename: Name of the configuration file
        fallback_dir: Optional fallback directory for development

    Returns:
        Parsed configuration dictionary
    """
    config_path = get_config_path(filename, fallback_dir)
    with open(config_path) as f:
        return yaml.safe_load(f)


def load_db_config(fallback_dir: Optional[Path] = None) -> dict:
    """
    Load the VM database configuration (db.yaml).

    Returns:
        Configuration dictionary with keys:
        - terraform_dir: Path to Terraform working directory
        - db_file: Path to VM database JSON file
        - ip_pool: IP allocation pool settings
        - vmid_range: VMID range for new VMs
        - default_expiry_days: Default VM expiry period
        - gc_grace_days: Grace period before GC destroys expired VMs
    """
    return load_config(DB_CONFIG_FILE, fallback_dir)


def load_web3_config(fallback_dir: Optional[Path] = None) -> dict:
    """
    Load the Web3/blockchain configuration (web3-defaults.yaml).

    Returns:
        Configuration dictionary with keys:
        - blockchain: Chain ID, contract address, RPC URL
        - deployer: Private key file path
        - signing_page: Port and HTML path settings
        - auth: OTP settings
    """
    return load_config(WEB3_CONFIG_FILE, fallback_dir)


def load_blockhost_config(fallback_dir: Optional[Path] = None) -> dict:
    """
    Load the main Blockhost configuration (blockhost.yaml).

    This file is created by init-server.sh and contains server-specific
    settings like the server public key and deployer address.

    Returns:
        Configuration dictionary with keys:
        - public_secret: Static message for encryption key derivation
        - server_public_key: Server's secp256k1 public key
        - deployer_address: Ethereum address of the deployer wallet
        - contract_address: Deployed subscription contract address
    """
    return load_config(BLOCKHOST_CONFIG_FILE, fallback_dir)


def load_broker_allocation(fallback_dir: Optional[Path] = None) -> Optional[dict]:
    """
    Load the broker allocation configuration (broker-allocation.json).

    This file is created by blockhost-broker-client when registering with
    the IPv6 tunnel broker. It contains the allocated IPv6 prefix and
    WireGuard tunnel configuration.

    Args:
        fallback_dir: Optional fallback directory for development

    Returns:
        Configuration dictionary with keys:
        - prefix: Allocated IPv6 prefix (e.g., "2a11:6c7:f04:276::/120")
        - gateway: IPv6 gateway address
        - broker_pubkey: WireGuard public key of the broker
        - broker_endpoint: WireGuard endpoint of the broker
        Or None if the file doesn't exist (broker not configured)
    """
    search_paths = [
        CONFIG_DIR / BROKER_ALLOCATION_FILE,
    ]

    if fallback_dir:
        search_paths.append(fallback_dir / BROKER_ALLOCATION_FILE)

    # Development fallback
    search_paths.append(Path("config") / BROKER_ALLOCATION_FILE)

    for path in search_paths:
        if path.exists():
            with open(path) as f:
                return json.load(f)

    return None  # Broker not configured


def get_db_file_path(fallback_dir: Optional[Path] = None) -> Path:
    """
    Get the path to the VM database file.

    Reads db_file from db.yaml configuration.

    Returns:
        Path to the vms.json database file
    """
    config = load_db_config(fallback_dir)
    return Path(config.get("db_file", str(DB_FILE)))


def get_terraform_dir(fallback_dir: Optional[Path] = None) -> Path:
    """
    Get the Terraform working directory.

    Reads terraform_dir from db.yaml configuration.

    Returns:
        Path to the Terraform directory
    """
    config = load_db_config(fallback_dir)
    tf_dir = config.get("terraform_dir")
    if tf_dir:
        return Path(tf_dir)
    return TERRAFORM_DIR


def ensure_directories():
    """
    Ensure all required Blockhost directories exist.

    Creates:
    - /etc/blockhost/
    - /var/lib/blockhost/
    - /var/lib/blockhost/terraform/

    Note: This is typically done by the postinst script, but can be
    called manually for development/testing.
    """
    CONFIG_DIR.mkdir(mode=0o750, parents=True, exist_ok=True)
    DATA_DIR.mkdir(mode=0o750, parents=True, exist_ok=True)
    TERRAFORM_DIR.mkdir(mode=0o755, parents=True, exist_ok=True)


# =============================================================================
# Environment-based Configuration
# =============================================================================

def is_development_mode() -> bool:
    """
    Check if running in development mode.

    Development mode is enabled when:
    - BLOCKHOST_DEV environment variable is set
    - /etc/blockhost does not exist

    Returns:
        True if in development mode
    """
    if os.environ.get("BLOCKHOST_DEV"):
        return True
    return not CONFIG_DIR.exists()
