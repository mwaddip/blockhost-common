"""
Blockhost Common Library

Shared configuration and database modules for the Blockhost VM hosting system.

This package provides:
- Path constants for Blockhost directories
- Configuration loading utilities
- VM database abstraction layer
- Provisioner dispatcher (pluggable backend discovery)
- Cloud-init template rendering

Usage:
    from blockhost.config import get_config_path, load_config
    from blockhost.vm_db import get_database
    from blockhost.provisioner import get_provisioner
    from blockhost.cloud_init import render_cloud_init
"""

__version__ = "0.1.0"

from .config import (
    CONFIG_DIR,
    DATA_DIR,
    get_config_path,
    load_config,
    load_db_config,
    load_web3_config,
    load_broker_allocation,
)
from .vm_db import get_database, VMDatabase, MockVMDatabase, VMDatabaseBase
from .root_agent import (
    call as root_agent_call,
    ip6_route_add, ip6_route_del,
    generate_wallet, addressbook_save,
    RootAgentError, RootAgentConnectionError,
)
from .provisioner import get_provisioner, ProvisionerDispatcher
from .cloud_init import render_cloud_init, find_template, list_templates

__all__ = [
    # Version
    "__version__",
    # Path constants
    "CONFIG_DIR",
    "DATA_DIR",
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
    "ip6_route_add",
    "ip6_route_del",
    "generate_wallet",
    "addressbook_save",
    "RootAgentError",
    "RootAgentConnectionError",
    # Provisioner dispatcher
    "get_provisioner",
    "ProvisionerDispatcher",
    # Cloud-init templates
    "render_cloud_init",
    "find_template",
    "list_templates",
]
