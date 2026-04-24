"""Network-mode-agnostic connection endpoint resolution.

Maps a VM's (name, bridge_ip) + network mode to the subscriber-facing host.

- broker / manual: pass-through (IPv6 or static IP)
- onion: create Tor hidden service, push .onion into VM, return .onion
"""

import subprocess

from . import root_agent
from .provisioner import get_provisioner


def get_connection_endpoint(vm_name: str, bridge_ip: str, mode: str) -> str:
    """Return the subscriber-facing host for a VM."""
    if mode == "onion":
        return _setup_onion(vm_name, bridge_ip)
    return bridge_ip


def cleanup(vm_name: str, mode: str) -> None:
    """Release network resources allocated for a VM."""
    if mode == "onion":
        _teardown_onion(vm_name)


def _setup_onion(vm_name: str, bridge_ip: str) -> str:
    response = root_agent.call(
        "tor-hidden-service-add",
        vm_name=vm_name,
        bridge_ip=bridge_ip,
        port=22,
    )
    onion = response["hostname"]

    guest_exec = get_provisioner().get_command("guest-exec")
    subprocess.run(
        [guest_exec, vm_name,
         f"sed -i '/^{bridge_ip} /d' /etc/hosts && "
         f"echo '{bridge_ip} {onion} {vm_name}' >> /etc/hosts"],
        check=True,
    )
    subprocess.run(
        [guest_exec, vm_name,
         f"echo '{onion}' > /run/libpam-web3/signing_host"],
        check=True,
    )
    subprocess.run(
        [guest_exec, vm_name,
         f"sed -i 's|signing_url = .*|signing_url = \"http://{onion}:8443\"|' "
         f"/etc/pam_web3/config.toml"],
        check=True,
    )
    # Tor provides transport encryption — disable TLS in the auth service.
    subprocess.run(
        [guest_exec, vm_name,
         "if grep -q '^use_tls' /etc/pam_web3/config.toml; then "
         "sed -i 's/^use_tls = .*/use_tls = false/' /etc/pam_web3/config.toml; "
         "else sed -i '/^\\[auth\\]/a use_tls = false' /etc/pam_web3/config.toml; fi"],
        check=True,
    )
    return onion


def _teardown_onion(vm_name: str) -> None:
    root_agent.call("tor-hidden-service-remove", vm_name=vm_name)
