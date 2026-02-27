"""
Shared utilities for root agent action modules.

All action modules should import validation helpers and the run() function
from here rather than reimplementing them.
"""

import json
import logging
import os
import re
import subprocess
from pathlib import Path

log = logging.getLogger('root-agent')

CONFIG_DIR = Path('/etc/blockhost')
STATE_DIR = Path('/var/lib/blockhost')

VMID_MIN = 100
VMID_MAX = 999999

NAME_RE = re.compile(r'^[a-z0-9-]{1,64}$')
SHORT_NAME_RE = re.compile(r'^[a-z0-9-]{1,32}$')
STORAGE_RE = re.compile(r'^[a-z0-9-]+$')
_HEX_ADDRESS_RE = re.compile(r'^0x[0-9a-fA-F]{40,128}$')
_BECH32_ADDRESS_RE = re.compile(r'^[a-z][a-z0-9]{0,9}1[02-9ac-hj-np-z]{39,90}$')


def is_valid_address(addr):
    """Structural address validation — chain-agnostic."""
    if not isinstance(addr, str) or not addr:
        return False
    return bool(_HEX_ADDRESS_RE.match(addr) or _BECH32_ADDRESS_RE.match(addr))

COMMENT_RE = re.compile(r'^[a-zA-Z0-9-]+$')
IPV6_CIDR128_RE = re.compile(r'^([0-9a-fA-F:]+)/128$')

ALLOWED_ROUTE_DEVS = frozenset({'vmbr0', 'virbr0', 'br0', 'br-ext', 'docker0'})
TAP_DEV_RE = re.compile(r'^tap\d+i\d+$')
WALLET_DENY_NAMES = frozenset({'admin', 'server', 'dev', 'broker'})

VIRT_CUSTOMIZE_ALLOWED_OPS = frozenset({
    '--install', '--run-command', '--copy-in', '--upload',
    '--chmod', '--mkdir', '--write', '--append-line',
    '--firstboot-command', '--run', '--delete',
})


def validate_vmid(vmid):
    if not isinstance(vmid, int) or vmid < VMID_MIN or vmid > VMID_MAX:
        raise ValueError(f'vmid must be int {VMID_MIN}-{VMID_MAX}')
    return vmid


def validate_ipv6_128(address):
    if not IPV6_CIDR128_RE.match(address):
        raise ValueError(f'Invalid IPv6/128: {address}')
    return address


def validate_dev(dev):
    if dev not in ALLOWED_ROUTE_DEVS and not TAP_DEV_RE.match(dev):
        raise ValueError(f'Device not allowed: {dev}')
    return dev


def run(cmd, timeout=120):
    """Execute a command and return (returncode, stdout, stderr)."""
    log.info('exec: %s', ' '.join(str(c) for c in cmd))
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return result.returncode, result.stdout.strip(), result.stderr.strip()
