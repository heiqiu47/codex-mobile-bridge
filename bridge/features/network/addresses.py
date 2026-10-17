"""IPv4 listener selection shared by the desktop controller and gateway."""
import ipaddress

from bridge.features.network.interfaces import addresses_for_interfaces, eligible_lan_addresses


def selected_addresses(value):
    if value is None:
        return None
    if not isinstance(value, list) or len(value) > 256:
        raise ValueError('请选择有效的局域网 IPv4 地址')
    result = []
    for item in value:
        try:
            address = ipaddress.IPv4Address(item) if isinstance(item, str) else None
        except ipaddress.AddressValueError:
            address = None
        if address is None or address.is_loopback or address.is_unspecified or address.is_multicast or str(address) == '255.255.255.255':
            raise ValueError('请选择有效的局域网 IPv4 地址')
        if str(address) not in result:
            result.append(str(address))
    return result


def bindings(preferences, interfaces=None):
    """Resolve the startup listeners; selected adapter listeners are dynamic."""
    selected_ids = preferences.get('lanInterfaces')
    if 'lanInterfaces' in preferences:
        selected = None if selected_ids is None else selected_ids
        resolved_addresses = (eligible_lan_addresses(interfaces or [])
                              if selected_ids is None else
                              addresses_for_interfaces(interfaces or [], selected_ids))
    else:
        selected = selected_addresses(preferences.get('lanAddresses'))
        resolved_addresses = selected or []
    if preferences.get('lan') and selected is None:
        return ['127.0.0.1'] + resolved_addresses
    return ['127.0.0.1'] + (resolved_addresses if preferences.get('lan') else [])
