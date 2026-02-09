# Provisioner Contract

Reference for implementing a new provisioner backend for Blockhost.

## Overview

A provisioner is a package that teaches Blockhost how to create, manage, and destroy VMs on a specific hypervisor or cloud platform. Each host has exactly one active provisioner. The provisioner registers itself by installing a **manifest file** at a well-known path.

## Manifest

**Path:** `/usr/share/blockhost/provisioner.json`

The manifest is a JSON file installed by the provisioner's `.deb` package. It declares the provisioner's capabilities and integration points.

### Schema

```json
{
  "name": "proxmox",
  "version": "0.1.0",
  "display_name": "Proxmox VE + Terraform",
  "commands": {
    "create":         "blockhost-vm-create",
    "destroy":        "blockhost-vm-destroy",
    "start":          "blockhost-vm-start",
    "stop":           "blockhost-vm-stop",
    "kill":           "blockhost-vm-kill",
    "status":         "blockhost-vm-status",
    "list":           "blockhost-vm-list",
    "metrics":        "blockhost-vm-metrics",
    "throttle":       "blockhost-vm-throttle",
    "build-template": "blockhost-build-template",
    "gc":             "blockhost-vm-gc",
    "resume":         "blockhost-vm-resume"
  },
  "setup": {
    "first_boot_hook": "/usr/share/blockhost/provisioner-hooks/first-boot.sh",
    "detect":          "blockhost-provisioner-detect",
    "wizard_module":   "blockhost.provisioner_proxmox.wizard",
    "finalization_steps": ["token", "terraform", "bridge", "template"]
  },
  "root_agent_actions": "/usr/share/blockhost/root-agent-actions/qm.py",
  "config_keys": {
    "session_key": "proxmox",
    "provisioner_config": ["terraform_dir", "vmid_range"]
  }
}
```

### Field Reference

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | yes | Machine-readable identifier (e.g. `proxmox`) |
| `version` | string | yes | Provisioner package version |
| `display_name` | string | yes | Human-readable name shown in UI |
| `commands` | object | yes | Maps verb names to CLI executables |
| `setup` | object | no | Installer/wizard integration points |
| `setup.wizard_module` | string | no | Python module path for wizard Blueprint |
| `setup.finalization_steps` | list | no | Ordered step IDs for wizard finalization |
| `setup.first_boot_hook` | string | no | Path to first-boot hook script |
| `setup.detect` | string | no | CLI command to detect if this provisioner's platform is available |
| `root_agent_actions` | string | no | Path to root agent action module |
| `config_keys.session_key` | string | no | Flask session key for provisioner config |
| `config_keys.provisioner_config` | list | no | Config keys owned by this provisioner |

## CLI Verb Interface

Each verb in `commands` maps to an executable that follows these conventions:

### Common Conventions

- **Exit code 0** = success
- **Exit code non-zero** = failure
- **stdout** = structured output (JSON) when applicable
- **stderr** = human-readable log/error messages

### Verbs

#### `create`

Create a new VM.

```
blockhost-vm-create --name NAME --vmid VMID --ip IP [--ipv6 IPV6] [--cloud-init PATH]
```

Reads additional configuration from `db.yaml`. Outputs JSON with created VM details on success.

#### `destroy`

Destroy a VM and clean up all resources.

```
blockhost-vm-destroy --vmid VMID
```

Must be idempotent — destroying an already-destroyed VM is not an error.

#### `start` / `stop` / `kill`

VM power management.

```
blockhost-vm-start --vmid VMID
blockhost-vm-stop --vmid VMID      # Graceful shutdown
blockhost-vm-kill --vmid VMID      # Immediate stop
```

#### `status`

Query VM status.

```
blockhost-vm-status --vmid VMID
```

Outputs JSON: `{"vmid": 100, "status": "running"|"stopped"|"unknown"}`.

#### `list`

List all managed VMs.

```
blockhost-vm-list
```

Outputs JSON array of VM status objects.

#### `metrics`

Collect VM resource metrics.

```
blockhost-vm-metrics --vmid VMID
```

Outputs JSON with CPU, memory, disk, and network usage.

#### `throttle`

Apply resource limits to a VM.

```
blockhost-vm-throttle --vmid VMID --cpu CORES --memory MB
```

#### `build-template`

Build or update the VM template image.

```
blockhost-build-template [--force]
```

#### `gc`

Run garbage collection on suspended/expired VMs.

```
blockhost-vm-gc [--dry-run]
```

#### `resume`

Resume a suspended VM.

```
blockhost-vm-resume --vmid VMID
```

## Wizard Plugin Interface

Provisioners can contribute pages and finalization logic to the setup wizard.

### Blueprint Registration

The `setup.wizard_module` must export a Flask Blueprint named `wizard_bp`:

```python
# blockhost/provisioner_proxmox/wizard.py
from flask import Blueprint

wizard_bp = Blueprint('provisioner_wizard', __name__, template_folder='templates')

@wizard_bp.route('/provisioner-config')
def config_page():
    ...
```

The wizard imports this Blueprint dynamically using the module path from the manifest.

### Finalization Steps

`setup.finalization_steps` lists step IDs that the wizard runs during finalization. Each step ID corresponds to a function in the wizard module:

```python
def finalize_token(session_data: dict) -> dict:
    """Returns {"ok": True} or {"ok": False, "error": "..."}."""
    ...

def finalize_terraform(session_data: dict) -> dict:
    ...
```

Step function names are derived from step IDs: `finalize_{step_id}`.

## Root Agent Action Module

The `root_agent_actions` field points to a Python file that extends the root agent daemon with provisioner-specific privileged commands.

The module must define a `COMMANDS` dict mapping action names to handler functions:

```python
# /usr/share/blockhost/root-agent-actions/qm.py

def qm_start(params: dict) -> dict:
    vmid = params["vmid"]
    # ... run privileged qm command ...
    return {"ok": True}

COMMANDS = {
    "qm-start": qm_start,
    "qm-stop": qm_stop,
    "qm-shutdown": qm_shutdown,
    "qm-destroy": qm_destroy,
}
```

Each handler receives the request params dict and returns a response dict. The root agent daemon loads this module at startup.

## First-Boot Hook

The `setup.first_boot_hook` script runs once during initial system setup, after the provisioner package is installed but before the wizard starts.

**Contract:**
- Must be idempotent (safe to run multiple times)
- Exit 0 on success, non-zero on failure
- Should detect and configure platform-specific prerequisites
- Runs as root
