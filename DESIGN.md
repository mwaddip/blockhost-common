# Blockhost Common Package Design

## Overview

`blockhost-common` is the base package for the Blockhost VM hosting system. It provides:

1. **Directory structure** - Standard locations for config and data files
2. **Configuration templates** - Default config files with sensible placeholders
3. **Python library** - Shared modules for config loading and VM database access
4. **Root agent daemon** - Privileged operations service (systemd-managed, Unix socket IPC)

This package resolves circular dependencies between `proxmox-terraform` (now `blockhost-provisioner-proxmox`) and `blockhost-engine` by establishing a common foundation they both depend on.

## Package Dependency Graph

```
                    blockhost-common
                          |
            +-------------+-------------+
            |                           |
            v                           v
    libpam-web3-tools           blockhost-provisioner-proxmox
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
blockhost-provisioner-proxmox (uses configs, no shipping)
         |
blockhost-engine (populates configs via init-server.sh)
```

## Directory Structure

### Installed by blockhost-common

```
/etc/blockhost/                     # Configuration directory (750 root:blockhost)
├── db.yaml                         # VM database settings
└── web3-defaults.yaml              # Blockchain/NFT settings

/var/lib/blockhost/                 # Data directory (750 blockhost:blockhost)
└── vms.json                        # VM database (created at runtime)

/usr/lib/python3/dist-packages/blockhost/
├── __init__.py                     # Package exports
├── cloud_init.py                   # Cloud-init template discovery and rendering
├── config.py                       # Path constants, config loading
├── provisioner.py                  # Provisioner dispatcher (pluggable backends)
├── root_agent.py                   # Root agent daemon client
└── vm_db.py                        # VM database abstraction

/usr/share/blockhost/cloud-init/templates/
├── devbox.yaml                     # Development environment template
├── nft-auth.yaml                   # NFT-authenticated VM template (primary)
└── webserver.yaml                  # Basic webserver template

/usr/share/doc/blockhost-common/
└── provisioner-contract.md         # Provisioner implementation reference

/usr/share/blockhost/root-agent/
└── blockhost_root_agent.py         # Root agent daemon (runs as root)

/usr/share/blockhost/root-agent-actions/
├── _common.py                      # Shared validation helpers and run()
├── networking.py                   # IPv6 routing actions (core)
└── system.py                       # Firewall, disk image, wallet actions (core)

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

**Owner:** `blockhost-common` (template), `blockhost-provisioner-proxmox` (may override)

Contains VM provisioning settings:
- `db_file` - Path to vms.json
- `fields` - Field name mappings (optional, for backend migration)
- `ip_pool` - IPv4 allocation range (network, start, end, gateway)
- `ipv6_pool` - IPv6 allocation range (start, end offsets within prefix)
- `default_expiry_days` - Default VM lifetime
- `gc_grace_days` - Grace period before GC destroys suspended VMs
- `terraform_dir` - *(optional, provisioner-managed)* Where Terraform runs
- `vmid_range` - *(optional, provisioner-managed)* VMID range (also accepts `vmid_pool`)

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

    # Config loading
    get_config_path,      # Find config file with fallback
    load_config,          # Load any YAML config
    load_db_config,       # Load db.yaml
    load_web3_config,     # Load web3-defaults.yaml
    load_broker_allocation, # Load broker-allocation.json (IPv6 prefix)
    load_blockhost_config,  # Load blockhost.yaml

    # Utilities
    get_db_file_path,     # Get vms.json path from config
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

# Record minted NFT on VM
db.set_nft_minted("web-001", token_id=1)

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
    ip6_route_add,       # Add IPv6 route
    ip6_route_del,       # Remove IPv6 route
    generate_wallet,     # Generate a new wallet
    addressbook_save,    # Save addressbook entries
    RootAgentError,      # Error returned by daemon
    RootAgentConnectionError,  # Cannot connect to socket
)

# Usage
ip6_route_add("2001:db8::1/128", "br0")
result = generate_wallet("hot")  # {"ok": true, "address": "0x..."}

# Provisioner-specific commands via generic call()
call("qm-start", vmid=100)
call("my-action", timeout=60, key="value")
```

Protocol: 4-byte big-endian length prefix + JSON payload over Unix socket at `/run/blockhost/root-agent.sock`.

#### Root Agent Action Plugin System

The daemon loads action handlers at startup from `/usr/share/blockhost/root-agent-actions/`. Each `.py` file (except `_`-prefixed files) must export an `ACTIONS` dict:

```python
# /usr/share/blockhost/root-agent-actions/networking.py
from _common import validate_ipv6_128, validate_dev, run

def handle_ip6_route_add(params):
    address = validate_ipv6_128(params['address'])
    dev = validate_dev(params['dev'])
    rc, out, err = run(['ip', '-6', 'route', 'replace', address, 'dev', dev])
    if rc != 0:
        return {'ok': False, 'error': err or out}
    return {'ok': True, 'output': out}

ACTIONS = {
    'ip6-route-add': handle_ip6_route_add,
}
```

**Contract:**
- Each handler receives a `params` dict and returns `{"ok": True, ...}` or `{"ok": False, "error": "reason"}`
- Shared helpers (validation regexes, `run()`) live in `_common.py` — import with `from _common import ...`
- Action name conflicts are logged and the first-loaded module wins (files loaded in sorted order)
- Only stdlib imports — no third-party dependencies

**Core modules** (shipped by blockhost-common):
- `networking.py` — `ip6-route-add`, `ip6-route-del`, `bridge-port-isolate`
- `system.py` — `iptables-open`, `iptables-close`, `virt-customize`, `generate-wallet`, `addressbook-save`, `broker-renew`

**Provisioner modules** (shipped by provisioner packages):
- e.g. `qm.py` — `qm-start`, `qm-stop`, `qm-create`, etc.

### blockhost.provisioner

```python
from blockhost.provisioner import (
    get_provisioner,          # Singleton factory
    ProvisionerDispatcher,    # Class (for testing with custom manifest path)
)

# Get the active provisioner
p = get_provisioner()

# Query provisioner metadata
p.name                # 'proxmox' (or 'unknown' if no manifest)
p.display_name        # 'Proxmox VE + Terraform'
p.is_loaded           # True if manifest was found and parsed

# Get CLI command for a verb
cmd = p.get_command('create')   # 'blockhost-vm-create'

# Run a provisioner command
result = p.run('status', ['--vmid', '100'], capture_output=True, text=True)

# Wizard/installer integration
p.wizard_module       # Python module path for wizard Blueprint
p.finalization_steps  # Ordered step IDs for wizard finalization
p.first_boot_hook     # Path to first-boot hook script

# Root agent extension
p.root_agent_actions  # Path to action module for root agent daemon
```

When no manifest exists at `/usr/share/blockhost/provisioner.json`, `get_command()` raises `RuntimeError`. See `provisioner-contract.md` for the full manifest schema and implementation guide.

### blockhost.cloud_init

```python
from blockhost.cloud_init import (
    find_template,        # Locate a template file by name
    render_cloud_init,    # Render template with variable substitution
    list_templates,       # List available template filenames
)

# Find and render a template
path = find_template('nft-auth.yaml')
content = render_cloud_init('nft-auth.yaml', {
    'VM_NAME': 'web-001',
    'WALLET_ADDRESS': '0x...',
})

# List available templates
names = list_templates()  # ['devbox.yaml', 'nft-auth.yaml']
```

Template search order: extra_dirs (if provided) → `/usr/share/blockhost/cloud-init/templates/` → `cloud-init/templates/` (dev fallback). Uses `string.Template.safe_substitute` so shell variables in templates are preserved.

## Migration Guide

### For proxmox-terraform (becomes blockhost-provisioner-proxmox)

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
   Depends: blockhost-provisioner-proxmox, blockhost-common (>= 0.1.0)
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

### 5. System user and group permissions

**Decision:** Create `blockhost` system user and group; use 750/640 permissions.

**Rationale:**
- `blockhost` system user owns `/var/lib/blockhost/` (data directory)
- `blockhost` group shared across all services for config access
- `/etc/blockhost/` remains root-owned (root:blockhost) — services read, only root writes
- Services can run as unprivileged users
- Key files remain 600 root:root

### 6. Cloud-init templates in blockhost-common

**Decision:** Ship cloud-init templates in blockhost-common, not the provisioner.

**Rationale:**
- Templates are hypervisor-agnostic — the same `nft-auth.yaml` works for Proxmox, libvirt, or Docker
- The provisioner passes rendered content to its backend-specific VM creation process
- Templates use `string.Template` syntax (`${VAR}`) — rendered by `blockhost.cloud_init.render_cloud_init()`
- Search path allows provisioners to supply additional templates via `extra_dirs`

**Templates shipped:**
- `nft-auth.yaml` — Primary template for web3 NFT-authenticated VMs (PAM + signing page + HTTPS)
- `webserver.yaml` — Basic nginx webserver with firewall
- `devbox.yaml` — Development environment with common tools

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
