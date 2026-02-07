# Blockhost Common Package Design

## Overview

`blockhost-common` is the base package for the Blockhost VM hosting system. It provides:

1. **Directory structure** - Standard locations for config and data files
2. **Configuration templates** - Default config files with sensible placeholders
3. **Python library** - Shared modules for config loading and VM database access
4. **Root agent daemon** - Privileged operations service (systemd-managed, Unix socket IPC)

This package resolves circular dependencies between `proxmox-terraform` (now `blockhost-provisioner`) and `blockhost-engine` by establishing a common foundation they both depend on.

## Package Dependency Graph

```
                    blockhost-common
                          |
            +-------------+-------------+
            |                           |
            v                           v
    libpam-web3-tools           blockhost-provisioner
            |                           |
            +-------------+-------------+
                          |
                          v
                   blockhost-engine
```

### Before (Circular)

```
proxmox-terraform <---> blockhost-engine
  (ships configs)        (creates configs)
```

### After (Resolved)

```
blockhost-common (owns directories, templates)
         |
blockhost-provisioner (uses configs, no shipping)
         |
blockhost-engine (populates configs via init-server.sh)
```

## Directory Structure

### Installed by blockhost-common

```
/etc/blockhost/                     # Configuration directory (750 root:blockhost)
├── db.yaml                         # VM database settings
└── web3-defaults.yaml              # Blockchain/NFT settings

/var/lib/blockhost/                 # Data directory (750 root:blockhost)
├── vms.json                        # VM database (created at runtime)
└── terraform/                      # Terraform working directory

/usr/lib/python3/dist-packages/blockhost/
├── __init__.py                     # Package exports
├── config.py                       # Path constants, config loading
├── root_agent.py                   # Root agent daemon client
└── vm_db.py                        # VM database abstraction

/usr/share/blockhost/root-agent/
└── blockhost_root_agent.py         # Root agent daemon (runs as root)

/etc/systemd/system/
└── blockhost-root-agent.service    # Systemd unit for root agent daemon
```

### Created by blockhost-engine init

```
/etc/blockhost/
├── blockhost.yaml                  # Server config (public key, deployer address)
├── server.key                      # Server private key (600 root:root)
└── deployer.key                    # Deployer private key (600 root:root)
```

## Configuration Files

### db.yaml

**Owner:** `blockhost-common` (template), `blockhost-provisioner` (may override)

Contains VM provisioning settings:
- `terraform_dir` - Where Terraform runs
- `db_file` - Path to vms.json
- `fields` - Field name mappings (optional, for backend migration)
- `ip_pool` - IPv4 allocation range (network, start, end, gateway)
- `ipv6_pool` - IPv6 allocation range (start, end offsets within prefix)
- `vmid_range` - Proxmox VMID range (also accepts `vmid_pool`)
- `default_expiry_days` - Default VM lifetime
- `gc_grace_days` - Grace period before GC destroys suspended VMs

### web3-defaults.yaml

**Owner:** `blockhost-common` (template), `blockhost-engine` (populated by init)

Contains blockchain settings:
- `blockchain.chain_id` - Ethereum chain ID
- `blockchain.nft_contract` - Contract address (empty until deployment)
- `blockchain.rpc_url` - JSON-RPC endpoint
- `deployer.private_key_file` - Path to deployer key
- `signing_page.*` - Signing page settings
- `auth.*` - OTP settings

### blockhost.yaml

**Owner:** `blockhost-engine` (created by init-server.sh)

Contains server-specific settings:
- `public_secret` - Message users sign
- `server_public_key` - For encryption
- `deployer_address` - Ethereum address
- `contract_address` - After deployment

## Python Module API

### blockhost.config

```python
from blockhost.config import (
    # Path constants
    CONFIG_DIR,           # /etc/blockhost
    DATA_DIR,             # /var/lib/blockhost
    TERRAFORM_DIR,        # /var/lib/blockhost/terraform

    # Config loading
    get_config_path,      # Find config file with fallback
    load_config,          # Load any YAML config
    load_db_config,       # Load db.yaml
    load_web3_config,     # Load web3-defaults.yaml
    load_broker_allocation, # Load broker-allocation.json (IPv6 prefix)

    # Utilities
    get_db_file_path,     # Get vms.json path from config
    get_terraform_dir,    # Get terraform_dir from config
    ensure_directories,   # Create directories if missing
    is_development_mode,  # Check if in dev mode
)
```

### blockhost.vm_db

```python
from blockhost.vm_db import (
    get_database,         # Factory function
    VMDatabase,           # Production implementation
    MockVMDatabase,       # Testing implementation
    VMDatabaseBase,       # Abstract base class
)

# Usage
db = get_database()

# Resource allocation
vmid = db.allocate_vmid()
ip = db.allocate_ip()
ipv6 = db.allocate_ipv6()  # Returns None if broker not configured

# VM registration
vm = db.register_vm(
    name="web-001",
    vmid=vmid,
    ip=ip,
    ipv6=ipv6,            # Optional IPv6 address
    owner="user",
    expiry_days=30,
)

# NFT token management
token_id = db.reserve_nft_token_id("web-001", token_id=5)  # Or auto-allocate if None
db.mark_nft_minted(token_id, "0x...")

# VM lifecycle (two-phase garbage collection)
db.mark_suspended("web-001")       # Phase 1: suspend expired VM
db.mark_active("web-001")          # Reactivate if user renews
db.mark_destroyed("web-001")       # Phase 2: destroy after grace period

# GC queries
to_suspend = db.get_vms_to_suspend()           # Active VMs past expiry
to_destroy = db.get_vms_to_destroy(grace_days=7)  # Suspended past grace
```

### blockhost.root_agent

```python
from blockhost.root_agent import (
    call,                 # Send arbitrary command to root agent
    qm_start,            # Start a VM
    qm_stop,             # Stop a VM (immediate)
    qm_shutdown,         # Graceful shutdown
    qm_destroy,          # Destroy a VM
    ip6_route_add,       # Add IPv6 route
    ip6_route_del,       # Remove IPv6 route
    generate_wallet,     # Generate a new wallet
    addressbook_save,    # Save addressbook entries
    RootAgentError,      # Error returned by daemon
    RootAgentConnectionError,  # Cannot connect to socket
)

# Usage
qm_start(100)
ip6_route_add("2001:db8::1/128", "vmbr0")
result = generate_wallet("hot")  # {"ok": true, "address": "0x..."}

# Custom command
call("my-action", timeout=60, key="value")
```

Protocol: 4-byte big-endian length prefix + JSON payload over Unix socket at `/run/blockhost/root-agent.sock`.

## Migration Guide

### For proxmox-terraform (becomes blockhost-provisioner)

1. **Remove config files:**
   - Delete `config/db.yaml`
   - Delete `config/web3-defaults.yaml`

2. **Update scripts to use blockhost module:**

   Before:
   ```python
   PROJECT_DIR = Path(__file__).parent.parent

   def get_config_path(filename: str) -> Path:
       etc_path = Path("/etc/blockhost") / filename
       if etc_path.exists():
           return etc_path
       return PROJECT_DIR / "config" / filename
   ```

   After:
   ```python
   from blockhost.config import get_config_path, load_db_config
   from blockhost.vm_db import get_database
   ```

3. **Remove local vm_db.py:**
   - Delete `scripts/vm_db.py`
   - Import from `blockhost.vm_db` instead

4. **Add dependency:**
   ```
   Depends: blockhost-common (>= 0.1.0)
   ```

### For blockhost-engine

1. **Update init-server.sh:**
   - Don't create `/etc/blockhost/` (already exists)
   - Don't create `/var/lib/blockhost/` (already exists)
   - Still create `/etc/blockhost/blockhost.yaml`
   - Still create key files

2. **Use config module for consistency:**
   ```python
   from blockhost.config import (
       CONFIG_DIR, DATA_DIR,
       SERVER_KEY_FILE, DEPLOYER_KEY_FILE
   )
   ```

3. **Add dependency:**
   ```
   Depends: blockhost-provisioner, blockhost-common (>= 0.1.0)
   ```

## Design Decisions

### 1. Separate db.yaml and web3-defaults.yaml

**Decision:** Keep as separate files.

**Rationale:**
- `db.yaml` is infrastructure-focused (IPs, VMIDs)
- `web3-defaults.yaml` is blockchain-focused
- Different update frequencies
- Easier to manage per-environment overrides

### 2. vm_db.py in blockhost-common

**Decision:** Move from proxmox-terraform to blockhost-common.

**Rationale:**
- Used by multiple scripts
- Tightly coupled to config paths
- Provides consistent database access
- Enables code sharing without copy-paste

### 3. Config file population

**Decision:** blockhost-common ships templates, blockhost-engine populates.

**Rationale:**
- blockhost-common has no runtime dependencies
- blockhost-engine already has init-server.sh
- Clear separation: structure vs. values

### 4. Development mode fallback

**Decision:** Support `./config/` fallback for development.

**Rationale:**
- Developers don't need root/installed package
- `BLOCKHOST_DEV` env var for explicit mode
- `get_config_path()` handles fallback automatically

### 5. Group permissions

**Decision:** Use `blockhost` group with 750/640 permissions.

**Rationale:**
- Services can run as unprivileged users
- Add service users to blockhost group
- Key files remain 600 root:root

## Build Instructions

```bash
# Build .deb package
cd blockhost-common
dpkg-deb --build . ../blockhost-common_0.1.0_all.deb

# Install
sudo dpkg -i ../blockhost-common_0.1.0_all.deb
```

## Testing

```python
# Test with mock database (no root required)
from blockhost.vm_db import get_database

db = get_database(use_mock=True)
vmid = db.allocate_vmid()
print(f"Allocated VMID: {vmid}")
```

## Future Considerations

1. **blockhost-init CLI:** Could move init-server.sh logic to a `blockhost-init` command in this package.

2. **Config validation:** Add schema validation for YAML files.

3. **Multiple environments:** Support `/etc/blockhost/conf.d/` drop-in configs.

4. **Database backends:** Abstract storage to support PostgreSQL/SQLite.
