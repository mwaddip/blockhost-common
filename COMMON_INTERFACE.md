# blockhost-common Interface Specification

> Authoritative contract for everything blockhost-common exposes to other packages.
> Derived from source code audit (2026-02-09). When code and this doc disagree, investigate both.

---

## 1. Configuration API

Module: `blockhost.config`

### Path Constants

```python
CONFIG_DIR = Path("/etc/blockhost")
DATA_DIR   = Path("/var/lib/blockhost")
```

### Functions

| Function | Signature | Returns | Reads |
|----------|-----------|---------|-------|
| `load_config` | `(filename, fallback_dir=None)` | `dict` | `CONFIG_DIR/{filename}` |
| `load_db_config` | `(fallback_dir=None)` | `dict` | `db.yaml` (see schema below) |
| `load_web3_config` | `(fallback_dir=None)` | `dict` | `web3-defaults.yaml` (see schema below) |
| `load_blockhost_config` | `(fallback_dir=None)` | `dict` | `blockhost.yaml` (see schema below) |
| `load_broker_allocation` | `(fallback_dir=None)` | `Optional[dict]` | `broker-allocation.json` (returns None if missing) |
| `get_config_path` | `(filename, fallback_dir=None)` | `Path` | Search order: CONFIG_DIR, fallback_dir, `./config/` |
| `get_db_file_path` | `(fallback_dir=None)` | `Path` | Derives from `db.yaml` → `db_file` key |
| `is_development_mode` | `()` | `bool` | `BLOCKHOST_DEV` env var or CONFIG_DIR missing |

**Search order**: `/etc/blockhost/{filename}` → `fallback_dir/{filename}` → `./config/{filename}`. Raises `FileNotFoundError` if all fail.

**`fallback_dir`**: Every load function accepts this. Intended for development and testing — lets scripts run without `/etc/blockhost/` existing.

### Contract Violations (existing)

| Export | Problem | Resolution |
|--------|---------|------------|
| `get_terraform_dir()` | Terraform is Proxmox-specific. Common shouldn't know about it. | Move to provisioner-proxmox or make generic ("provisioner working dir") |
| `TERRAFORM_DIR` constant | Same — hardcoded `/var/lib/blockhost/terraform` | Remove from common |

---

## 2. VM Database API

Module: `blockhost.vm_db`

### Factory

```python
get_database(use_mock=False, config_path=None, fallback_dir=None) -> VMDatabaseBase
```

Returns `MockVMDatabase` if `use_mock=True`, otherwise `VMDatabase`.

### Public Methods (all implementations)

#### VM Lifecycle

| Method | Signature | Returns | Notes |
|--------|-----------|---------|-------|
| `register_vm` | `(name, vmid, ip, ipv6=None, owner="", expiry_days=30, purpose="", wallet_address=None)` | `dict` (VM record) | Creates new record |
| `get_vm` | `(name)` | `Optional[dict]` | Lookup by name |
| `list_vms` | `(status=None)` | `list[dict]` | Filter: `"active"`, `"suspended"`, `"destroyed"`, or `None` for all |
| `extend_expiry` | `(name, days)` | `None` | Extends from current expiry |
| `mark_suspended` | `(name)` | `None` | Sets status + suspended_at |
| `mark_active` | `(name, new_expiry=None)` | `None` | Reactivates, optionally sets new expiry |
| `mark_destroyed` | `(name)` | `None` | Sets status + destroyed_at, releases IPs |

#### Allocation

| Method | Signature | Returns | Notes |
|--------|-----------|---------|-------|
| `allocate_ip` | `()` | `Optional[str]` | Next available IPv4 from pool |
| `allocate_ipv6` | `()` | `Optional[str]` | Next available IPv6 (requires broker allocation) |
| `allocate_vmid` | `()` | `int` | Next available VMID. Raises `RuntimeError` if `vmid_range` not configured |
| `release_ip` | `(ip)` | `None` | VMDatabase only (not on mock) |
| `release_ipv6` | `(ipv6)` | `None` | VMDatabase only (not on mock) |

#### Garbage Collection

| Method | Signature | Returns | Notes |
|--------|-----------|---------|-------|
| `get_vms_to_suspend` | `()` | `list[dict]` | Active VMs past expiry |
| `get_vms_to_destroy` | `(grace_days)` | `list[dict]` | Suspended VMs past grace period |
| `get_expired_vms` | `(grace_days=0)` | `list[dict]` | All VMs past expiry + grace |

#### NFT Token Management

| Method | Signature | Returns | Notes |
|--------|-----------|---------|-------|
| `reserve_nft_token_id` | `(vm_name, token_id=None)` | `int` | Auto-allocates if token_id is None |
| `mark_nft_minted` | `(token_id, owner_wallet)` | `None` | Records successful mint |
| `mark_nft_failed` | `(token_id)` | `None` | Marks reservation as failed |
| `get_nft_token` | `(token_id)` | `Optional[dict]` | Lookup by token ID |

### VM Record Schema

```python
{
    "vm_name": str,
    "vmid": int,
    "ip_address": str,
    "ipv6_address": Optional[str],
    "status": "active" | "suspended" | "destroyed",
    "owner": str,
    "wallet_address": Optional[str],
    "purpose": str,
    "created_at": str,       # ISO 8601
    "expires_at": str,       # ISO 8601
    "suspended_at": Optional[str],   # Added on suspend
    "destroyed_at": Optional[str],   # Added on destroy
}
```

### Storage

- Production: JSON file with `fcntl` file locking at path from `db.yaml` → `db_file`
- Default: `/var/lib/blockhost/vms.json`
- Mock: in-memory, no file I/O

---

## 3. Root Agent Client API

Module: `blockhost.root_agent`

### Protocol

- **Socket**: `/run/blockhost/root-agent.sock`
- **Framing**: 4-byte big-endian length prefix + JSON payload (both directions)
- **Request**: `{"action": "action-name", "params": {...}}`
- **Response**: `{"ok": true/false, "error": "...", ...}`

### Generic Call

```python
call(action: str, timeout: float = 300, **params) -> dict
```

This is the real interface. Everything else is a wrapper around this.

### Convenience Wrappers

| Function | Calls Action | Params |
|----------|-------------|--------|
| `ip6_route_add(address, dev="vmbr0")` | `ip6-route-add` | `{address, dev}` |
| `ip6_route_del(address, dev="vmbr0")` | `ip6-route-del` | `{address, dev}` |
| `generate_wallet(name)` | `generate-wallet` | `{name}` |
| `addressbook_save(entries)` | `addressbook-save` | `{entries}` |

### Exceptions

- `RootAgentError` — base exception, agent returned `{"ok": false}`
- `RootAgentConnectionError(RootAgentError)` — socket unreachable

### Contract Violations (existing)

| Export | Problem | Resolution |
|--------|---------|------------|
| `qm_start(vmid)` | Proxmox-specific. Calls `qm-start` action. | Provisioner should call `call("qm-start", vmid=vmid)` directly |
| `qm_stop(vmid)` | Same | Same |
| `qm_shutdown(vmid)` | Same | Same |
| `qm_destroy(vmid)` | Same | Same |

These wrappers leak Proxmox into common's public API. Consumers should use the generic `call()` with provisioner-specific action names. The wrappers can be deprecated.

---

## 4. Root Agent Daemon

Location: `/usr/share/blockhost/root-agent/blockhost_root_agent.py`

### Plugin Discovery

- Scans `/usr/share/blockhost/root-agent-actions/` for `.py` files
- Skips files starting with `_` (e.g., `_common.py`)
- Each module must export `ACTIONS: dict[str, callable]`
- Handler signature: `handler(params: dict) -> dict`
- Response must include `"ok": bool`

### Built-in Actions (from common)

Shipped in `root-agent-actions/system.py` and `networking.py`:

| Action | Params | Returns | Module |
|--------|--------|---------|--------|
| `iptables-open` | `{port: int, proto: str, comment: str}` | `{ok, output}` | system.py |
| `iptables-close` | `{port: int, proto: str, comment: str}` | `{ok, output}` | system.py |
| `virt-customize` | `{image_path: str, commands: list[list]}` | `{ok, output}` | system.py |
| `generate-wallet` | `{name: str}` | `{ok, address}` | system.py |
| `addressbook-save` | `{entries: dict}` | `{ok}` | system.py |
| `ip6-route-add` | `{address: str, dev: str}` | `{ok, output}` | networking.py |
| `ip6-route-del` | `{address: str, dev: str}` | `{ok, output}` | networking.py |

### Shared Utilities (`_common.py`)

Available to all action plugins via `from _common import ...`:

**Constants:**
```python
CONFIG_DIR = Path('/etc/blockhost')
STATE_DIR = Path('/var/lib/blockhost')
VMID_MIN = 100
VMID_MAX = 999999
```

**Validation Regexes:**
```python
NAME_RE          = re.compile(r'^[a-z0-9-]{1,64}$')
SHORT_NAME_RE    = re.compile(r'^[a-z0-9-]{1,32}$')
STORAGE_RE       = re.compile(r'^[a-z0-9-]+$')
ADDRESS_RE       = re.compile(r'^0x[0-9a-fA-F]{40}$')
COMMENT_RE       = re.compile(r'^[a-zA-Z0-9-]+$')
IPV6_CIDR128_RE  = re.compile(r'^([0-9a-fA-F:]+)/128$')
```

**Validation Functions:**
- `validate_vmid(vmid: int) -> int`
- `validate_ipv6_128(address: str) -> str`
- `validate_dev(dev: str) -> str`

**Execution:**
- `run(cmd: list, timeout: int = 120) -> tuple[int, str, str]` — returns `(returncode, stdout, stderr)`

**Allowed Sets:**
- `ALLOWED_ROUTE_DEVS = frozenset({'vmbr0'})`
- `WALLET_DENY_NAMES = frozenset({'admin', 'server', 'dev', 'broker'})`
- `VIRT_CUSTOMIZE_ALLOWED_OPS` — validated operations for virt-customize
- `QM_SET_ALLOWED_KEYS`, `QM_CREATE_ALLOWED_ARGS` — Proxmox-specific allow lists

### Contract Violations (existing)

| Item | Problem | Resolution |
|------|---------|------------|
| `ALLOWED_ROUTE_DEVS = {'vmbr0'}` | vmbr0 is Proxmox's bridge name. libvirt uses different bridge names. | Make configurable or expand the allowed set |
| `QM_SET_ALLOWED_KEYS`, `QM_CREATE_ALLOWED_ARGS` | Proxmox-specific constants in shared _common | Move to provisioner-proxmox's action module |

---

## 5. Cloud-Init API

Module: `blockhost.cloud_init`

### Functions

| Function | Signature | Returns |
|----------|-----------|---------|
| `render_cloud_init` | `(template_name: str, variables: dict[str, str], extra_dirs: list[Path] = None)` | `str` (rendered YAML) |
| `find_template` | `(name: str, extra_dirs: list[Path] = None)` | `Path` |
| `list_templates` | `(extra_dirs: list[Path] = None)` | `list[str]` |

**Template search order**: `extra_dirs` (first match) → `/usr/share/blockhost/cloud-init/templates/` → `./cloud-init/templates/` (dev)

**Rendering**: `string.Template.safe_substitute()` — unknown `${VAR}` left as-is (no error).

### Shipped Templates

| Template | Variables Required | Purpose |
|----------|-------------------|---------|
| `nft-auth.yaml` | `VM_NAME`, `VM_IP`, `VM_IPV6`, `SIGNING_HOST`, `USERNAME`, `NFT_TOKEN_ID`, `CHAIN_ID`, `NFT_CONTRACT`, `RPC_URL`, `OTP_LENGTH`, `OTP_TTL`, `SECRET_KEY`, `SSH_KEYS` | NFT-authenticated VM with PAM module |
| `webserver.yaml` | (none) | nginx + UFW |
| `devbox.yaml` | (none) | Build tools + dev environment |

---

## 6. Provisioner Dispatcher

Module: `blockhost.provisioner`

### Factory

```python
get_provisioner() -> ProvisionerDispatcher  # singleton
```

### Class: ProvisionerDispatcher

**Constructor**: `__init__(manifest_path: Path = None)` — defaults to `/usr/share/blockhost/provisioner.json`

**Properties:**

| Property | Type | Source |
|----------|------|--------|
| `name` | `str` | `manifest["name"]` |
| `display_name` | `str` | `manifest["display_name"]` |
| `version` | `str` | `manifest["version"]` |
| `is_loaded` | `bool` | True if manifest exists and parsed |
| `manifest` | `dict` | Raw manifest (empty dict if not loaded) |
| `wizard_module` | `Optional[str]` | `manifest["setup"]["wizard_module"]` |
| `finalization_steps` | `list[str]` | `manifest["setup"]["finalization_steps"]` |
| `first_boot_hook` | `Optional[str]` | `manifest["setup"]["first_boot_hook"]` |
| `session_key` | `str` | `manifest["config_keys"]["session_key"]` |
| `root_agent_actions` | `Optional[str]` | `manifest["root_agent_actions"]` |

**Methods:**

| Method | Signature | Returns | Notes |
|--------|-----------|---------|-------|
| `get_command` | `(verb: str)` | `str` | Maps verb to CLI command name from manifest |
| `run` | `(verb: str, args: list = None, **kwargs)` | `CompletedProcess` | Runs command via `subprocess.run()` |

**Legacy fallback**: If no manifest exists, uses hardcoded `LEGACY_COMMANDS` dict. This should be removed (see section 9).

---

## 7. Config File Schemas

### `/etc/blockhost/db.yaml`

```yaml
db_file: /var/lib/blockhost/vms.json
default_expiry_days: 30
gc_grace_days: 7

ip_pool:
  network: "192.168.122.0/24"
  start: 200              # int (last octet) or full IP string
  end: 250
  gateway: "192.168.122.1"

ipv6_pool:
  start: 2
  end: 254

# Optional — set by provisioner if needed
# vmid_range:
#   start: 100
#   end: 999

# Optional — set by provisioner if needed
# terraform_dir: /var/lib/blockhost/terraform

fields:                   # Optional — field name mapping
  vm_name: vm_name
  vmid: vmid
  ip_address: ip_address
  expires_at: expires_at
  owner: owner
  status: status
  created_at: created_at
```

**Owned by**: common (ships template in .deb)
**Written by**: wizard finalization (fills in actual IP pool, expiry values)
**Read by**: every provisioner script, VM database, GC

### `/etc/blockhost/web3-defaults.yaml`

```yaml
blockchain:
  chain_id: 11155111
  nft_contract: ""          # Set after contract deployment
  rpc_url: "https://ethereum-sepolia-rpc.publicnode.com"

deployer:
  private_key_file: "/etc/blockhost/deployer.key"

signing_page:
  port: 8080
  html_path: "/usr/share/libpam-web3-tools/signing-page/index.html"

auth:
  otp_length: 6
  otp_ttl_seconds: 300
```

**Owned by**: common (ships template in .deb)
**Written by**: wizard finalization (fills in contract address, chain ID)
**Read by**: mint_nft, vm-create, app.py, engine

### `/etc/blockhost/broker-allocation.json`

```json
{
  "prefix": "2a11:6c7:f04:276::/120",
  "gateway": "2a11:6c7:f04:276::1",
  "broker_pubkey": "...",
  "broker_endpoint": "..."
}
```

**Owned by**: blockhost-broker-client (writes on allocation)
**Read by**: common's `load_broker_allocation()`, VM database (IPv6 pool)
**Optional**: Missing = no IPv6 allocation available

### `/etc/blockhost/blockhost.yaml`

```yaml
public_secret: "..."
server_public_key: "..."
deployer_address: "0x..."
contract_address: "0x..."
```

**Owned by**: installer / init scripts
**Read by**: `load_blockhost_config()`, validate_system.py

---

## 8. Installed File Locations

### From blockhost-common .deb

```
/etc/blockhost/
  ├── db.yaml                    # Config template (conffile)
  └── web3-defaults.yaml         # Config template (conffile)

/usr/lib/python3/dist-packages/blockhost/
  ├── __init__.py                # Package entry, re-exports
  ├── config.py                  # Configuration loading
  ├── vm_db.py                   # VM database abstraction
  ├── provisioner.py             # Provisioner dispatcher
  ├── root_agent.py              # Root agent client
  └── cloud_init.py              # Template rendering

/usr/share/blockhost/
  ├── root-agent/
  │   └── blockhost_root_agent.py
  ├── root-agent-actions/
  │   ├── _common.py             # Shared utilities (not an action module)
  │   ├── system.py              # iptables, virt-customize, wallet
  │   └── networking.py          # IPv6 routes
  └── cloud-init/templates/
      ├── nft-auth.yaml
      ├── webserver.yaml
      └── devbox.yaml

/var/lib/blockhost/              # Data directory (created by postinst, mode 750)
```

**No CLI tools in `/usr/bin/`** — common has no commands, only libraries and daemon.

---

## 9. Contract Violations & Cleanup Needed

| # | Item | Location | Problem | Resolution |
|---|------|----------|---------|------------|
| 1 | `qm_start/stop/shutdown/destroy` | `root_agent.py` | Proxmox-specific wrappers in common | Deprecate. Provisioners call `call()` directly. |
| 2 | `get_terraform_dir()` | `config.py` | Terraform is Proxmox-specific | Move to provisioner-proxmox or generalize |
| 3 | `TERRAFORM_DIR` constant | `config.py`, `__init__.py` | Same | Remove from common |
| 4 | `mint_nft` module | `blockhost/mint_nft.py` (if present) | Minting is engine responsibility | Move to engine |
| 5 | `LEGACY_COMMANDS` fallback | `provisioner.py` | Hardcoded Proxmox commands when no manifest | Remove — no manifest = no provisioner |
| 6 | `ALLOWED_ROUTE_DEVS = {'vmbr0'}` | `_common.py` | vmbr0 is Proxmox-specific bridge name | Make configurable or expand set |
| 7 | `QM_SET_ALLOWED_KEYS`, `QM_CREATE_ALLOWED_ARGS` | `_common.py` | Proxmox constants in shared code | Move to provisioner-proxmox's `qm.py` |
| 8 | `vmid_range` optional in db.yaml | `vm_db.py` | VMID is Proxmox-specific (libvirt uses domain names) | `allocate_vmid()` should only exist where needed |

---

## 10. Consumers

| Package | Imports From Common | Config Files Read |
|---------|--------------------|--------------------|
| **blockhost-provisioner-proxmox** | config (5 functions), vm_db, root_agent (4 qm wrappers + ip6 + errors), cloud_init, mint_nft | db.yaml, web3-defaults.yaml, broker-allocation.json |
| **blockhost-provisioner-libvirt** | (stubs — will use config, vm_db, root_agent.call, cloud_init) | db.yaml, web3-defaults.yaml, broker-allocation.json |
| **blockhost (installer)** | config, mint_nft, provisioner dispatcher | web3-defaults.yaml |
| **blockhost-engine** | config, vm_db, root_agent | db.yaml, web3-defaults.yaml |
| **blockhost-broker** | config (broker allocation) | broker-allocation.json |
