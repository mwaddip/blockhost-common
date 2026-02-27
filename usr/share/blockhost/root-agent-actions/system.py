"""
Root agent actions: firewall, disk images, wallet, addressbook, broker.
"""

import json
import os

from _common import (
    CONFIG_DIR,
    COMMENT_RE,
    SHORT_NAME_RE,
    NAME_RE,
    is_valid_address,
    VIRT_CUSTOMIZE_ALLOWED_OPS,
    log,
    run,
)


def handle_iptables_open(params):
    port = params.get('port')
    if not isinstance(port, int) or port < 1 or port > 65535:
        return {'ok': False, 'error': 'port must be 1-65535'}
    proto = params.get('proto', 'tcp')
    if proto not in ('tcp', 'udp'):
        return {'ok': False, 'error': 'proto must be tcp or udp'}
    comment = params.get('comment', '')
    if not COMMENT_RE.match(comment):
        return {'ok': False, 'error': 'Invalid comment (alphanumeric/dash only)'}
    rc, out, err = run([
        'iptables', '-A', 'INPUT', '-p', proto,
        '--dport', str(port), '-j', 'ACCEPT',
        '-m', 'comment', '--comment', comment,
    ])
    if rc != 0:
        return {'ok': False, 'error': err or out}
    return {'ok': True, 'output': out}


def handle_iptables_close(params):
    port = params.get('port')
    if not isinstance(port, int) or port < 1 or port > 65535:
        return {'ok': False, 'error': 'port must be 1-65535'}
    proto = params.get('proto', 'tcp')
    if proto not in ('tcp', 'udp'):
        return {'ok': False, 'error': 'proto must be tcp or udp'}
    comment = params.get('comment', '')
    if not COMMENT_RE.match(comment):
        return {'ok': False, 'error': 'Invalid comment (alphanumeric/dash only)'}
    rc, out, err = run([
        'iptables', '-D', 'INPUT', '-p', proto,
        '--dport', str(port), '-j', 'ACCEPT',
        '-m', 'comment', '--comment', comment,
    ])
    if rc != 0:
        return {'ok': False, 'error': err or out}
    return {'ok': True, 'output': out}


def handle_virt_customize(params):
    image_path = params.get('image_path', '')
    commands = params.get('commands', [])
    if not (image_path.startswith('/var/lib/blockhost/') or image_path.startswith('/tmp/')):
        return {'ok': False, 'error': 'image_path must be under /var/lib/blockhost/ or /tmp/'}
    if not os.path.isfile(image_path):
        return {'ok': False, 'error': f'Image not found: {image_path}'}
    if not isinstance(commands, list) or not commands:
        return {'ok': False, 'error': 'commands must be a non-empty list'}
    cmd = ['virt-customize', '-a', image_path]
    for entry in commands:
        if not isinstance(entry, list) or len(entry) < 2:
            return {'ok': False, 'error': f'Each command must be [op, arg, ...]: {entry}'}
        op = entry[0]
        if op not in VIRT_CUSTOMIZE_ALLOWED_OPS:
            return {'ok': False, 'error': f'Disallowed virt-customize op: {op}'}
        cmd.extend(entry)
    rc, out, err = run(cmd, timeout=600)
    if rc != 0:
        return {'ok': False, 'error': err or out}
    return {'ok': True, 'output': out}


def handle_addressbook_save(params):
    import grp
    entries = params.get('entries', {})
    if not isinstance(entries, dict):
        return {'ok': False, 'error': 'entries must be a dict'}
    for name, entry in entries.items():
        if not SHORT_NAME_RE.match(name) and not NAME_RE.match(name):
            return {'ok': False, 'error': f'Invalid entry name: {name}'}
        if not isinstance(entry, dict):
            return {'ok': False, 'error': f'Entry {name} must be a dict'}
        addr = entry.get('address', '')
        if not is_valid_address(addr):
            return {'ok': False, 'error': f'Invalid address for {name}: {addr}'}
        keyfile = entry.get('keyfile')
        if keyfile and not keyfile.startswith('/etc/blockhost/'):
            return {'ok': False, 'error': f'keyfile for {name} must be under /etc/blockhost/'}
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    ab_file = CONFIG_DIR / 'addressbook.json'
    ab_file.write_text(json.dumps(entries, indent=2))
    gid = grp.getgrnam('blockhost').gr_gid
    os.chown(str(ab_file), 0, gid)
    os.chmod(str(ab_file), 0o640)
    log.info('Saved addressbook with %d entries', len(entries))
    return {'ok': True}


def handle_broker_renew(params):
    alloc_file = CONFIG_DIR / 'broker-allocation.json'
    if not alloc_file.exists():
        return {'ok': False, 'error': 'no existing broker allocation found'}
    try:
        alloc = json.loads(alloc_file.read_text())
    except (json.JSONDecodeError, IOError) as e:
        return {'ok': False, 'error': f'failed to read broker allocation: {e}'}
    nft_contract = alloc.get('nft_contract', '')
    if not nft_contract:
        return {'ok': False, 'error': 'no existing broker allocation found'}
    rc, out, err = run([
        'broker-client', 'renew',
        '--nft-contract', nft_contract,
        '--wallet-key', str(CONFIG_DIR / 'deployer.key'),
        '--configure-wg',
    ], timeout=120)
    if rc != 0:
        return {'ok': False, 'error': err or out}
    return {'ok': True, 'output': out}


ACTIONS = {
    'iptables-open': handle_iptables_open,
    'iptables-close': handle_iptables_close,
    'virt-customize': handle_virt_customize,
    'addressbook-save': handle_addressbook_save,
    'broker-renew': handle_broker_renew,
}
