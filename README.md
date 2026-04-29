# blockhost-common

Base package for the Blockhost VM hosting system. Provides shared configuration, directory structure, and Python libraries used by all Blockhost components.

## Installation

```bash
# Build
./build.sh

# Install
sudo dpkg -i ../blockhost-common_0.1.0_all.deb
```

## What's Included

### System User and Group

The package creates a `blockhost` system group and user on install:
- Group `blockhost` — shared by all Blockhost services
- User `blockhost` — system account, no login shell, home `/var/lib/blockhost`

### Directory Structure

- `/etc/blockhost/` - Configuration files (root:blockhost 750)
- `/var/lib/blockhost/` - Runtime data, VM database (blockhost:blockhost 750)
- `/usr/share/blockhost/root-agent/` - Root agent daemon

### Systemd Service

The package ships a `blockhost-root-agent.service` that runs the privileged operations daemon. It is enabled and started automatically on install.

```bash
systemctl status blockhost-root-agent
journalctl -u blockhost-root-agent
```

### Configuration Files

- `db.yaml` - VM database and IP pool settings
- `web3-defaults.yaml` - Blockchain and NFT settings

### CLIs

Engine helpers installed under `/usr/bin/`. Engines call these binaries
instead of spawning `python3 -c "<inline>"`, which avoids per-call
interpreter startup + import cost (~50–150 ms each).

```bash
blockhost-vmdb get-vm <vm_name>                       # JSON on stdout, exit 1 if not found
blockhost-vmdb mark-nft-minted <vm_name> <token_id>   # exit 1 if not found
blockhost-vmdb extend-expiry <vm_name> <days>         # prints NEEDS_RESUME if previously suspended
blockhost-vmdb update-fields <vm_name> --fields '{...}'  # engine-defined merge

# blockhost-network-hook dispatches to the network-mode plugin enabled
# via /etc/blockhost/network-modes.enabled/<mode>.json (apache-style
# available/enabled symlink pattern). See facts/NETWORK_INTERFACE.md.
blockhost-network-hook public-address <vm_name>       # publicly-routable address
blockhost-network-hook push-vm-config <vm_name>       # idempotent VM-side config push
blockhost-network-hook cleanup <vm_name>              # release per-VM resources
blockhost-network-hook pre-provision <mode> <plan>    # pre-allocate values for a plan (future)
blockhost-network-hook mode <vm_name>                 # echo the resolved mode (debugging)
blockhost-network-hook list-available                 # installed mode names, one per line
blockhost-network-hook list-enabled                   # currently-enabled mode names, one per line
blockhost-network-hook enable <mode>                  # symlink available → enabled (validates exclusive_with)
blockhost-network-hook disable <mode>                 # remove the enabled symlink
```

### Python Module

```python
from blockhost.config import load_db_config, load_web3_config
from blockhost.vm_db import get_database
from blockhost.root_agent import call
from blockhost.provisioner import get_provisioner
from blockhost.cloud_init import render_cloud_init
from blockhost.network import (
    dispatch_vm, dispatch_mode, resolve_mode,
    list_available, list_enabled, enable, disable,
)

# Load configuration
db_config = load_db_config()
web3_config = load_web3_config()

# Access VM database
db = get_database()
vmid = db.allocate_vmid()

# Register a VM (network_mode is required per NETWORK_INTERFACE.md §3)
vm = db.register_vm(
    name='web-001', vmid=vmid, ip='192.168.122.50',
    network_mode='onion',
)

# Call root agent daemon (requires root-agent.sock)
call("qm-start", vmid=vmid)       # Provisioner-specific actions via generic call()

# Provisioner dispatcher (discovers active backend via manifest)
p = get_provisioner()
cmd = p.get_command('create')        # Requires provisioner manifest

# Cloud-init template rendering
content = render_cloud_init('nft-auth.yaml', {'VM_NAME': 'web-001'})

# Network plugin dispatch — resolves via /etc/blockhost/network-modes.enabled/
exit_code = dispatch_vm('public-address', 'web-001')
mode = resolve_mode('web-001')                       # 'onion'

# Activation management (apache sites-available/sites-enabled pattern)
enable('onion')                                       # create symlink, validate exclusive_with
list_enabled()                                        # ['onion']
disable('onion')                                      # remove symlink

# Deprecated shim — engines that haven't migrated yet keep working
# (each call emits a DeprecationWarning)
from blockhost.network_hook import get_connection_endpoint, cleanup
host = get_connection_endpoint('web-001', '192.168.122.50', 'onion')
cleanup('web-001', 'onion')
```

## Development

For local development without installing the package:

```bash
# Set PYTHONPATH to include the module
export PYTHONPATH=/path/to/blockhost-common/usr/lib/python3/dist-packages:$PYTHONPATH

# Or set development mode
export BLOCKHOST_DEV=1

# Config files will fall back to ./config/ directory
```

## Documentation

See [DESIGN.md](DESIGN.md) for architecture details and migration guide.

## Dependencies

- Python 3.10+
- python3-yaml

## Related Packages

- `libpam-web3` - PAM module for NFT authentication (installed on VMs)
- `libpam-web3-tools` - CLI tools and signing page
- `blockhost-provisioner-proxmox` - VM provisioning scripts (Terraform)
- `blockhost-engine-evm` - EVM blockchain event monitor and orchestrator
