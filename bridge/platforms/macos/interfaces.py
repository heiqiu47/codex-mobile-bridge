"""macOS interface and default-route enumeration."""
import os
import re
import socket
import struct
import subprocess


def enumerate_interfaces():
    if not os.path.exists('/sbin/ifconfig'):
        return []
    output = subprocess.run(['/sbin/ifconfig'], capture_output=True, text=True,
                            check=False, timeout=3).stdout
    rows, current = [], None
    for line in output.splitlines():
        match = re.match(r'^([A-Za-z0-9._-]+):', line)
        if match:
            name = match.group(1)
            current = {'id': name, 'name': name, 'addresses': []}
            rows.append(current)
        elif current is not None:
            match = re.match(r'^\s+inet\s+([0-9.]+)', line)
            if match:
                current['addresses'].append(match.group(1))
    return rows


def default_route():
    if not os.path.exists('/sbin/route'):
        return {}
    output = subprocess.run(['/sbin/route', '-n', 'get', 'default'],
                            capture_output=True, text=True, check=False, timeout=3).stdout
    route = {'type': 'default'}
    for line in output.splitlines():
        key, separator, value = line.partition(':')
        if not separator:
            continue
        key, value = key.strip().lower(), value.strip()
        if key == 'interface':
            route['interface'] = value
        elif key == 'gateway':
            route['gateway'] = value
    return route


def _network_event(data):
    # Darwin route.h uses a common msglen/version/type prelude. Ignore route
    # queries (including our own route -n get) and ARP/neighbor chatter.
    offset = 0
    while len(data) - offset >= 4:
        length, version, kind = struct.unpack_from('=HBB', data, offset)
        if length < 4 or offset + length > len(data):
            return False
        if version == 5:
            if kind in (0xC, 0xD, 0xE, 0x12):  # address/link state
                return True
            if kind in (1, 2, 3, 6) and length >= 12:
                flags = struct.unpack_from('=I', data, offset + 8)[0]
                if not flags & 0x400:  # RTF_LLINFO: neighbor resolution
                    return True
        offset += length
    return False


def watch_changes(callback):
    """Read kernel route notifications; never run periodic helper processes."""
    from bridge.platforms.posix.network_events import SocketNetworkWatcher
    source = None
    try:
        source = socket.socket(socket.AF_ROUTE, socket.SOCK_RAW, 0)
        return SocketNetworkWatcher(source, callback, _network_event)
    except (OSError, AttributeError, RuntimeError):
        if source is not None:
            source.close()
        return None
