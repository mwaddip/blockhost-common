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

### Directory Structure

- `/etc/blockhost/` - Configuration files
- `/var/lib/blockhost/` - Runtime data (VM database)

### Configuration Files

- `db.yaml` - VM database and IP pool settings
- `web3-defaults.yaml` - Blockchain and NFT settings

### Python Module

```python
from blockhost.config import load_db_config, load_web3_config
from blockhost.vm_db import get_database

# Load configuration
db_config = load_db_config()
web3_config = load_web3_config()

# Access VM database
db = get_database()
vmid = db.allocate_vmid()
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
- `blockhost-provisioner` - VM provisioning scripts (Terraform)
- `blockhost-engine` - Blockchain event monitor and orchestrator
