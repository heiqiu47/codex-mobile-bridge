"""Linux interface and default-route enumeration."""
import json
import shutil
import socket
import struct
import subprocess


def enumerate_interfaces():
    executable = shutil.which('ip')
    if not executable:
        return []
    output = subprocess.run([executable, '-j', '-4', 'address', 'show', 'up'],
                            capture_output=True, text=True, check=False, timeout=3)
    if output.returncode:
        return []
    try:
        interfaces = json.loads(output.stdout)
    except (ValueError, TypeError):
        return []
    if not isinstance(interfaces, list):
        return []
    rows = []
    for item in interfaces:
        if not isinstance(item, dict):
            continue
        name = item.get('ifname') or item.get('altname') or ''
        addresses = [addr.get('local') for addr in item.get('addr_info', [])
                     if isinstance(addr, dict) and addr.get('family') == 'inet']
        rows.append({'id': name, 'name': name, 'addresses': addresses})
    return rows


def default_route():
    executable = shutil.which('ip')
    if not executable:
        return {}
    output = subprocess.run([executable, '-4', 'route', 'show', 'default'],
                            capture_output=True, text=True, check=False, timeout=3)
    if output.returncode:
        return {}
    fields = output.stdout.split()
    route = {'type': 'default'}
    if 'dev' in fields:
        route['interface'] = fields[fields.index('dev') + 1]
    if 'via' in fields:
        route['gateway'] = fields[fields.index('via') + 1]
    return route


def _network_event(data):
    # rtnetlink messages may be batched in one datagram and use 4-byte padding.
    offset = 0
    while len(data) - offset >= 16:
        length, kind = struct.unpack_from('=IH', data, offset)
        if length < 16 or offset + length > len(data):
            return False
        if kind in (16, 17, 20, 21, 24, 25):  # link/address/route changes
            return True
        offset += (length + 3) & ~3
    return False


def watch_changes(callback):
    """Subscribe to IPv4 address, link and route multicast notifications."""
    from bridge.platforms.posix.network_events import SocketNetworkWatcher
    source = None
    try:
        source = socket.socket(socket.AF_NETLINK, socket.SOCK_RAW, 0)  # NETLINK_ROUTE
        source.bind((0, 1 | 0x10 | 0x40))  # RTMGRP_LINK/IPV4_IFADDR/IPV4_ROUTE
        return SocketNetworkWatcher(source, callback, _network_event)
    except (OSError, AttributeError, RuntimeError):
        if source is not None:
            source.close()
        return None
