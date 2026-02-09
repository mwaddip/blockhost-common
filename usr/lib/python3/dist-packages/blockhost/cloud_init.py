"""
Cloud-Init Template Rendering

Provides template discovery and rendering for cloud-init user-data.
Templates are hypervisor-agnostic — the provisioner passes rendered
content to its backend-specific VM creation process.

Template search paths (in order):
  1. /usr/share/blockhost/cloud-init/templates/  (shipped by blockhost-common)
  2. Provisioner-specific paths (if provided)
"""

import logging
import string
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# Default template directory (shipped by blockhost-common .deb)
TEMPLATE_DIR = Path("/usr/share/blockhost/cloud-init/templates")

# Development fallback
DEV_TEMPLATE_DIR = Path("cloud-init/templates")


def find_template(name: str, extra_dirs: Optional[list[Path]] = None) -> Path:
    """Find a cloud-init template by name.

    Args:
        name: Template filename (e.g. 'nft-auth.yaml')
        extra_dirs: Additional directories to search (checked first)

    Returns:
        Path to the template file

    Raises:
        FileNotFoundError: If template not found in any search path
    """
    search_paths = []

    if extra_dirs:
        search_paths.extend(extra_dirs)

    search_paths.append(TEMPLATE_DIR)
    search_paths.append(DEV_TEMPLATE_DIR)

    for directory in search_paths:
        candidate = directory / name
        if candidate.exists():
            return candidate

    raise FileNotFoundError(
        f"Cloud-init template '{name}' not found. Searched:\n"
        + "\n".join(f"  - {d}" for d in search_paths)
    )


def render_cloud_init(
    template_name: str,
    variables: dict[str, str],
    extra_dirs: Optional[list[Path]] = None,
) -> str:
    """Render a cloud-init template with variable substitution.

    Uses safe_substitute — undefined variables are left as-is rather
    than raising an error, since cloud-init templates may contain
    shell variables that shouldn't be expanded.

    Args:
        template_name: Template filename (e.g. 'nft-auth.yaml')
        variables: Dict of variable names to values (without ${} wrappers)
        extra_dirs: Additional template search directories

    Returns:
        Rendered cloud-init content as a string
    """
    template_path = find_template(template_name, extra_dirs)
    raw = template_path.read_text()

    # Use string.Template for ${VAR} substitution (safe_substitute keeps unknowns)
    template = string.Template(raw)
    rendered = template.safe_substitute(variables)

    log.debug("Rendered cloud-init template %s (%d bytes)", template_name, len(rendered))
    return rendered


def list_templates(extra_dirs: Optional[list[Path]] = None) -> list[str]:
    """List available cloud-init template names.

    Returns:
        List of template filenames (e.g. ['nft-auth.yaml', 'devbox.yaml'])
    """
    templates = set()
    search_paths = [TEMPLATE_DIR, DEV_TEMPLATE_DIR]

    if extra_dirs:
        search_paths = list(extra_dirs) + search_paths

    for directory in search_paths:
        if directory.is_dir():
            for f in directory.iterdir():
                if f.suffix in ('.yaml', '.yml') and f.is_file():
                    templates.add(f.name)

    return sorted(templates)
