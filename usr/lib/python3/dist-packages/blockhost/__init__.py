"""
Blockhost Common Library

Shared configuration and database modules for the Blockhost VM hosting system.

This package provides:
- Path constants for Blockhost directories
- Configuration loading utilities
- VM database abstraction layer

Usage:
    from blockhost.config import get_config_path, load_config
    from blockhost.vm_db import get_database
"""

__version__ = "0.1.0"

from .config import (
    CONFIG_DIR,
    DATA_DIR,
    TERRAFORM_DIR,
    get_config_path,
    load_config,
    load_db_config,
    load_web3_config,
)
from .vm_db import get_database, VMDatabase, MockVMDatabase, VMDatabaseBase

__all__ = [
    # Version
    "__version__",
    # Path constants
    "CONFIG_DIR",
    "DATA_DIR",
    "TERRAFORM_DIR",
    # Config functions
    "get_config_path",
    "load_config",
    "load_db_config",
    "load_web3_config",
    # Database classes
    "get_database",
    "VMDatabase",
    "MockVMDatabase",
    "VMDatabaseBase",
]
