"""Naming validators shared across BlockHost components."""

import re

# VM domain name: alphanumeric leading char, then alphanumeric / . _ -. 1–64 chars.
# Used as the natural key for VMs in vm-db.json, and as the libvirt domain name.
DOMAIN_NAME_RE = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$')


def is_valid_domain_name(name: str) -> bool:
    """Return True if name matches the domain naming rules."""
    return isinstance(name, str) and bool(DOMAIN_NAME_RE.match(name))


def validate_domain_name(name: str) -> str:
    """Return name if valid; raise ValueError otherwise."""
    if not is_valid_domain_name(name):
        raise ValueError(f'Invalid domain name: {name!r}')
    return name
