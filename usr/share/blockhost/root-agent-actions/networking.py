"""
Root agent actions: IPv6 routing.
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


ACTIONS = {
    'ip6-route-add': handle_ip6_route_add,
    'ip6-route-del': handle_ip6_route_del,
}
