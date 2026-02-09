#!/usr/bin/env python3
"""
BlockHost Root Agent — Privileged Operations Daemon

Runs as root, listens on a Unix domain socket, accepts validated JSON
commands. Action handlers are loaded as plugins from the actions directory.

Each .py file in ACTIONS_DIR (except _-prefixed files) must export an
ACTIONS dict mapping action names to handler functions.

Protocol: 4-byte big-endian length prefix + JSON payload (both directions).
"""

import asyncio
import importlib.util
import json
import logging
import os
import struct
import sys
from pathlib import Path

SOCKET_PATH = '/run/blockhost/root-agent.sock'
ACTIONS_DIR = Path('/usr/share/blockhost/root-agent-actions')

logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s %(message)s',
    stream=sys.stderr,
)
log = logging.getLogger('root-agent')

ACTIONS = {}


def _load_action_plugins() -> dict:
    """Load action handler modules from the actions directory.

    Each .py file in ACTIONS_DIR must define an ACTIONS dict mapping
    action names to handler functions: {"action-name": handler_func}

    Files starting with _ (like _common.py) are skipped — they provide
    shared utilities, not actions.
    """
    actions = {}

    if not ACTIONS_DIR.is_dir():
        log.warning('Actions directory not found: %s', ACTIONS_DIR)
        return actions

    # Add ACTIONS_DIR to the front of sys.path so action modules can
    # import _common with a bare `from _common import ...`
    actions_dir_str = str(ACTIONS_DIR)
    if actions_dir_str not in sys.path:
        sys.path.insert(0, actions_dir_str)

    for path in sorted(ACTIONS_DIR.glob('*.py')):
        if path.name.startswith('_'):
            continue
        module_name = path.stem
        try:
            spec = importlib.util.spec_from_file_location(
                f'root_agent_actions.{module_name}', path
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

            module_actions = getattr(mod, 'ACTIONS', {})
            if not isinstance(module_actions, dict):
                log.warning('Module %s: ACTIONS is not a dict, skipping', module_name)
                continue

            loaded = 0
            for name in module_actions:
                if name in actions:
                    log.warning('Action %s from %s conflicts with existing, skipping', name, module_name)
                    continue
                actions[name] = module_actions[name]
                loaded += 1

            log.info('Loaded %d actions from %s', loaded, module_name)
        except Exception as e:
            log.error('Failed to load action module %s: %s', module_name, e)

    return actions


async def read_message(reader):
    header = await reader.readexactly(4)
    length = struct.unpack('>I', header)[0]
    if length > 10 * 1024 * 1024:
        raise ValueError(f'Message too large: {length}')
    data = await reader.readexactly(length)
    return json.loads(data.decode('utf-8'))


async def write_message(writer, msg):
    data = json.dumps(msg).encode('utf-8')
    writer.write(struct.pack('>I', len(data)) + data)
    await writer.drain()


async def handle_connection(reader, writer):
    try:
        msg = await asyncio.wait_for(read_message(reader), timeout=10)
        action = msg.get('action', '')
        params = msg.get('params', {})
        log.info('Request: action=%s', action)
        handler = ACTIONS.get(action)
        if not handler:
            response = {'ok': False, 'error': f'Unknown action: {action}'}
        else:
            try:
                response = handler(params)
            except Exception as e:
                log.exception('Handler error for %s', action)
                response = {'ok': False, 'error': str(e)}
        await write_message(writer, response)
    except asyncio.IncompleteReadError:
        log.warning('Client disconnected mid-message')
    except asyncio.TimeoutError:
        log.warning('Client read timeout')
    except Exception as e:
        log.exception('Connection error')
        try:
            await write_message(writer, {'ok': False, 'error': str(e)})
        except Exception:
            pass
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


async def main():
    if os.getuid() != 0:
        log.error('Root agent must run as root')
        sys.exit(1)

    global ACTIONS
    ACTIONS = _load_action_plugins()
    log.info('Loaded %d total actions', len(ACTIONS))

    run_dir = Path(SOCKET_PATH).parent
    run_dir.mkdir(parents=True, exist_ok=True)
    socket_path = Path(SOCKET_PATH)
    if socket_path.exists():
        socket_path.unlink()
    server = await asyncio.start_unix_server(handle_connection, path=SOCKET_PATH)
    try:
        import grp
        gid = grp.getgrnam('blockhost').gr_gid
        os.chown(SOCKET_PATH, 0, gid)
    except (KeyError, OSError) as e:
        log.warning('Could not set socket group to blockhost: %s', e)
    os.chmod(SOCKET_PATH, 0o660)
    log.info('Root agent listening on %s', SOCKET_PATH)
    async with server:
        await server.serve_forever()


if __name__ == '__main__':
    asyncio.run(main())
