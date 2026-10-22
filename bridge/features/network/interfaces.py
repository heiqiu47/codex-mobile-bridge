"""Normalize platform adapter data and resolve publishable LAN addresses."""
import importlib
import ipaddress
import json
import platform
from functools import lru_cache


IF_TYPE_SOFTWARE_LOOPBACK = 24
IF_TYPE_TUNNEL = 53
VIRTUAL_PREFIXES = (
    'bridge', 'vmenet', 'vmnet', 'veth', 'virbr', 'docker', 'utun', 'tun',
    'tap', 'wg', 'awdl', 'llw', 'anpi', 'ap1', 'lo', 'vethernet', 'zerotier',
)
VIRTUAL_TOKENS = {
    'virtual', 'vmware', 'virtualbox', 'hyper-v', 'wsl', 'docker', 'tap',
    'tun', 'wireguard', 'vpn', 'tailscale', 'openvpn',
}
_VIRTUAL_IF_TYPES = {IF_TYPE_SOFTWARE_LOOPBACK, IF_TYPE_TUNNEL}


def valid_ipv4(value):
    try:
        address = ipaddress.IPv4Address(value)
    except (ipaddress.AddressValueError, TypeError):
        return None
    if (address.is_loopback or address.is_unspecified or address.is_multicast or
            address.is_link_local or address == ipaddress.IPv4Address('255.255.255.255')):
        return None
    return str(address)


def _is_private_lan(number):
    value = int(number)
    return ((value & 0xFF000000) == 0x0A000000 or
            (value & 0xFFF00000) == 0xAC100000 or
            (value & 0xFFFF0000) == 0xC0A80000)


def _rows(rows):
    result, seen = [], set()
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
        result.append({
            'id': identifier, 'name': name,
            'addresses': sorted(addresses, key=lambda value: tuple(map(int, value.split('.')))),
            'index': row.get('index'), 'if_type': row.get('if_type'),
            'virtual': bool(row.get('virtual')),
        })
    return sorted(result, key=lambda row: (row['name'].lower(), row['id'],
                                           tuple(map(int, row['addresses'][0].split('.'))) if row['addresses'] else ()))


@lru_cache(maxsize=1)
def _platform_module():
    system = platform.system()
    module_name = {'Linux': 'linux', 'Darwin': 'macos', 'Windows': 'windows'}.get(system)
    if not module_name:
        return None
    module = importlib.import_module('bridge.platforms.' + module_name + '.interfaces')
    return module


def enumerate_interfaces():
    module = _platform_module()
    return _rows(module.enumerate_interfaces()) if module else []


def default_route():
    module = _platform_module()
    return module.default_route() if module else {}


def _name_text(row):
    return ' '.join((str(row.get('id', '')), str(row.get('name', '')))).lower()


def is_virtual_interface(row):
    if row.get('virtual') is True:
        return True
    if row.get('if_type') in _VIRTUAL_IF_TYPES:
        return True
    identity = _name_text(row)
    if any(identity.startswith(prefix) for prefix in VIRTUAL_PREFIXES):
        return True
    tokens = set(identity.replace('-', ' ').replace('_', ' ').split())
    return bool(tokens.intersection(VIRTUAL_TOKENS)) or any(token in identity for token in ('vmware', 'virtualbox'))


def eligible_lan_addresses(rows=None):
    """Addresses that may be published as same-LAN HTTP entries.

    Host-only and provider networks (Parallels/WSL/Docker/VPN) must not become
    entries merely because they have an RFC1918 address. Public and carrier NAT
    addresses are never published as LAN entries.
    """
    rows = enumerate_interfaces() if rows is None else rows
    result = []
    for row in rows:
        if is_virtual_interface(row):
            continue
        for value in row.get('addresses', []):
            address = valid_ipv4(value)
            if not address:
                continue
            number = ipaddress.IPv4Address(address)
            excluded = number.is_loopback or number.is_link_local or not _is_private_lan(number)
            if excluded or address in result:
                continue
            result.append(address)
    return sorted(result, key=ipaddress.IPv4Address)


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
    """Map a legacy address-only selection without expanding ambiguous scope."""
    if value is None:
        return None
    selected = set(value or [])
    matches = [row for row in rows if row['id'] and selected.intersection(row.get('addresses', []))]
    if len(matches) == 1:
        return [matches[0]['id']]
    non_virtual = [row for row in matches if not is_virtual_interface(row)]
    return [non_virtual[0]['id']] if len(non_virtual) == 1 else []


def addresses_for_interfaces(rows, identifiers):
    selected = set(identifiers or [])
    return sorted({address for row in rows if row['id'] in selected
                   for address in row.get('addresses', [])}, key=ipaddress.IPv4Address)


def network_signature(rows=None, route=None):
    """Identity of the default route and its adapter, independent of LAN scope."""
    rows = enumerate_interfaces() if rows is None else rows
    route = default_route() if route is None else route
    route_interface = route.get('interface')
    route_index = route.get('index')
    routable = [row for row in rows if not is_virtual_interface(row) and (
        (route_interface and row['id'] == route_interface) or
        (route_index is not None and row.get('index') == route_index))]
    if not routable and not route_interface:
        routable = [row for row in rows if not is_virtual_interface(row)]
    interfaces = [{'id': row['id'], 'name': row['name'], 'addresses': row['addresses'],
                   'if_type': row.get('if_type'), 'index': row.get('index')}
                  for row in routable]
    # Route fixtures may hand back a mutable dict; signatures must be snapshots.
    return {'interfaces': interfaces,
            'route': json.loads(json.dumps(route, sort_keys=True)) if route is not None else {}}
