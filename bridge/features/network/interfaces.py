"""IPv4 interface identity and address snapshots used by gateway adapters.

Interface identity, not an address, is the persistent selection.  Interface
names are stable on Linux/macOS; Windows uses the adapter GUID from the OS.
"""
import ctypes
import ipaddress
import json
import os
import platform
import re
import socket
import shutil
import subprocess


def valid_ipv4(value):
    try:
        address = ipaddress.IPv4Address(value)
    except (ipaddress.AddressValueError, TypeError):
        return None
    if (address.is_loopback or address.is_unspecified or address.is_multicast or
            address.is_link_local or address == ipaddress.IPv4Address('255.255.255.255')):
        return None
    return str(address)


def _rows(rows):
    result = []
    seen = set()
    for row in rows:
        identifier = str(row.get('id', '')).strip()
        name = str(row.get('name', '')).strip() or identifier or 'unknown'
        addresses = []
        for value in row.get('addresses', []):
            address = valid_ipv4(value)
            if address and address not in addresses:
                addresses.append(address)
        key = (identifier, name)
        if key in seen:
            existing = next(item for item in result if (item['id'], item['name']) == key)
            existing['addresses'] = list(dict.fromkeys(existing['addresses'] + addresses))
            continue
        seen.add(key)
        result.append({'id': identifier, 'name': name,
                       'addresses': sorted(addresses, key=lambda value: ipaddress.IPv4Address(value))})
    return sorted(result, key=lambda row: (row['name'].lower(), row['id'], row['addresses']))


def _linux_rows():
    executable = shutil.which('ip')
    if not executable:
        return []
    output = subprocess.run([executable, '-j', '-4', 'address', 'show', 'up'],
                            capture_output=True, text=True, check=False, timeout=3)
    if output.returncode:
        return []
    interfaces = json.loads(output.stdout)
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
    return _rows(rows)


def _macos_rows():
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
    return _rows(rows)


class _IP_ADDR_STRING(ctypes.Structure):
    pass


_IP_ADDR_STRING._fields_ = [
    ('Next', ctypes.POINTER(_IP_ADDR_STRING)),
    ('IpAddress', ctypes.c_char * 16),
    ('IpMask', ctypes.c_char * 16),
    ('Context', ctypes.c_ulong),
]


class _IP_ADAPTER_INFO(ctypes.Structure):
    pass


_IP_ADAPTER_INFO._fields_ = [
    ('Next', ctypes.POINTER(_IP_ADAPTER_INFO)),
    ('ComboIndex', ctypes.c_ulong),
    ('AdapterName', ctypes.c_char * 260),
    ('Description', ctypes.c_char * 132),
    ('AddressLength', ctypes.c_uint),
    ('Address', ctypes.c_ubyte * 8),
    ('Index', ctypes.c_ulong),
    ('Type', ctypes.c_uint),
    ('DhcpEnabled', ctypes.c_uint),
    ('CurrentIpAddress', ctypes.POINTER(_IP_ADDR_STRING)),
    ('IpAddressList', _IP_ADDR_STRING),
    ('GatewayList', _IP_ADDR_STRING),
    ('DhcpServer', _IP_ADDR_STRING),
    ('HaveWins', ctypes.c_int),
    ('PrimaryWinsServer', _IP_ADDR_STRING),
    ('SecondaryWinsServer', _IP_ADDR_STRING),
    ('LeaseObtained', ctypes.c_longlong),
    ('LeaseExpires', ctypes.c_longlong),
]


def _windows_rows():
    library = ctypes.windll.iphlpapi
    size = ctypes.c_ulong(0)
    if library.GetAdaptersInfo(None, ctypes.byref(size)) != 111:
        return []
    buffer = ctypes.create_string_buffer(size.value)
    adapter = ctypes.cast(buffer, ctypes.POINTER(_IP_ADAPTER_INFO))
    if library.GetAdaptersInfo(adapter, ctypes.byref(size)) != 0:
        return []
    rows = []
    while adapter:
        item = adapter.contents
        identifier = item.AdapterName.decode('utf-8', 'replace')
        name = item.Description.decode('utf-8', 'replace') or identifier
        addresses = []
        candidate = ctypes.pointer(item.IpAddressList)
        for _ in range(64):
            if not candidate:
                break
            addresses.append(candidate.contents.IpAddress.value.decode('ascii', 'replace'))
            candidate = candidate.contents.Next
            if not candidate:
                break
        rows.append({'id': identifier, 'name': name, 'addresses': addresses})
        adapter = item.Next
    return _rows(rows)


def _fallback_rows():
    addresses = []
    try:
        for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            addresses.append(item[4][0])
    except OSError:
        pass
    return _rows([{'id': '', 'name': 'unknown', 'addresses': addresses}])


def enumerate_interfaces():
    """Return adapter identities and IPv4 addresses without DNS waits."""
    try:
        if platform.system() == 'Windows':
            rows = _windows_rows()
        elif platform.system() == 'Linux':
            rows = _linux_rows()
        elif platform.system() == 'Darwin':
            rows = _macos_rows()
        else:
            rows = []
        if not rows:
            rows = _fallback_rows()
        return rows
    except (OSError, ValueError, TypeError, KeyError, AttributeError, subprocess.SubprocessError):
        try:
            return _fallback_rows()
        except Exception:
            return []


def interface_addresses(rows=None):
    rows = enumerate_interfaces() if rows is None else rows
    return sorted({address for row in rows for address in row['addresses']})


def selected_interfaces(value):
    if value is None:
        return None
    if not isinstance(value, list) or len(value) > 256:
        raise ValueError('请选择有效的局域网网卡')
    result = []
    for item in value:
        if not isinstance(item, str) or not item.strip() or len(item) > 256:
            raise ValueError('请选择有效的局域网网卡')
        item = item.strip()
        if item not in result:
            result.append(item)
    return result


def migrate_addresses_to_interfaces(rows, value):
    """Map a legacy address-only selection to currently visible interfaces."""
    if value is None:
        return None
    selected = set(value or [])
    return [row['id'] for row in rows if row['id'] and selected.intersection(row['addresses'])]


def addresses_for_interfaces(rows, identifiers):
    selected = set(identifiers or [])
    return sorted({address for row in rows if row['id'] in selected for address in row['addresses']})
