"""
Root agent actions: networking (IPv6 routing, bridge port isolation).
"""

from _common import validate_ipv6_128, validate_dev, run


def handle_ip6_route_add(params):
    address = validate_ipv6_128(params['address'])
    dev = validate_dev(params['dev'])
    rc, out, err = run(['ip', '-6', 'route', 'replace', address, 'dev', dev])
    if rc != 0:
        return {'ok': False, 'error': err or out}
    return {'ok': True, 'output': out}


def handle_ip6_route_del(params):
    address = validate_ipv6_128(params['address'])
    dev = validate_dev(params['dev'])
    rc, out, err = run(['ip', '-6', 'route', 'del', address, 'dev', dev])
    if rc != 0:
        return {'ok': False, 'error': err or out}
    return {'ok': True, 'output': out}


def handle_bridge_port_isolate(params):
    """Enable bridge port isolation on a tap interface.

    Isolated ports cannot exchange frames with each other,
    only with non-isolated ports (the host uplink).
    Requires kernel 5.2+.
    """
    dev = validate_dev(params['dev'])
    rc, out, err = run(['bridge', 'link', 'set', 'dev', dev, 'isolated', 'on'])
    if rc != 0:
        return {'ok': False, 'error': err or out}
    return {'ok': True, 'output': out}


ACTIONS = {
    'ip6-route-add': handle_ip6_route_add,
    'ip6-route-del': handle_ip6_route_del,
    'bridge-port-isolate': handle_bridge_port_isolate,
}
