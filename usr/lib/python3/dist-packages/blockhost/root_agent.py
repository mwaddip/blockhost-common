"""
Root Agent Client — call the privileged root agent daemon via Unix socket.

Usage:
    from blockhost.root_agent import call, ip6_route_add, generate_wallet

    call("my-action", vmid=100)
    ip6_route_add("2001:db8::1/128", "br0")
    result = generate_wallet("hot")  # returns {"address": "0x..."}
"""

import json
import socket
import struct

SOCKET_PATH = "/run/blockhost/root-agent.sock"
DEFAULT_TIMEOUT = 300  # seconds (terraform can be slow)


class RootAgentError(Exception):
    """Error returned by root agent."""
    pass


class RootAgentConnectionError(RootAgentError):
    """Cannot connect to root agent socket."""
    pass


def call(action: str, timeout: float = DEFAULT_TIMEOUT, **params) -> dict:
    """Send a command to the root agent and return the response.

    Args:
        action: Action name (e.g. 'qm-start', 'iptables-open')
        timeout: Socket timeout in seconds
        **params: Action parameters

    Returns:
        Response dict (always has 'ok' key)

    Raises:
        RootAgentConnectionError: Cannot connect to socket
        RootAgentError: Agent returned an error
    """
    msg = json.dumps({"action": action, "params": params}).encode("utf-8")

    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect(SOCKET_PATH)
    except (OSError, ConnectionRefusedError) as e:
        raise RootAgentConnectionError(f"Cannot connect to root agent: {e}")

    try:
        sock.sendall(struct.pack(">I", len(msg)) + msg)
        header = _recv_exact(sock, 4)
        length = struct.unpack(">I", header)[0]
        data = _recv_exact(sock, length)
        response = json.loads(data.decode("utf-8"))
        if not response.get("ok"):
            raise RootAgentError(response.get("error", "Unknown error"))
        return response
    finally:
        sock.close()


def _recv_exact(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise RootAgentConnectionError("Connection closed by root agent")
        buf += chunk
    return buf


# --- Convenience wrappers ---

def ip6_route_add(address: str, dev: str) -> dict:
    return call("ip6-route-add", address=address, dev=dev)

def ip6_route_del(address: str, dev: str) -> dict:
    return call("ip6-route-del", address=address, dev=dev)

def generate_wallet(name: str) -> dict:
    """Generate a new wallet. Returns {"ok": true, "address": "0x..."}."""
    return call("generate-wallet", name=name)

def addressbook_save(entries: dict) -> dict:
    return call("addressbook-save", entries=entries)
