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
    load_broker_allocation,
)
from .vm_db import get_database, VMDatabase, MockVMDatabase, VMDatabaseBase
from .root_agent import (
    call as root_agent_call,
    qm_start, qm_stop, qm_shutdown, qm_destroy,
    ip6_route_add, ip6_route_del,
    generate_wallet, addressbook_save,
    RootAgentError, RootAgentConnectionError,
)

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
    "load_broker_allocation",
    # Database classes
    "get_database",
    "VMDatabase",
    "MockVMDatabase",
    "VMDatabaseBase",
    # Root agent client
    "root_agent_call",
    "qm_start",
    "qm_stop",
    "qm_shutdown",
    "qm_destroy",
    "ip6_route_add",
    "ip6_route_del",
    "generate_wallet",
    "addressbook_save",
    "RootAgentError",
    "RootAgentConnectionError",
]
