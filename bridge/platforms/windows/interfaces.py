"""Windows interface and default-route enumeration through iphlpapi."""
import ctypes
from ctypes import c_char_p, c_ubyte, c_ulong, c_ulonglong, c_ushort, c_void_p, POINTER, Structure, Union


AF_INET = 2
ERROR_BUFFER_OVERFLOW = 111
GAA_FLAG_SKIP_ANYCAST = 2
GAA_FLAG_SKIP_MULTICAST = 4
GAA_FLAG_SKIP_DNS_SERVER = 8
IF_TYPE_SOFTWARE_LOOPBACK = 24
IF_TYPE_TUNNEL = 53


class SOCKADDR(Structure):
    _fields_ = [('sa_family', c_ushort), ('sa_data', c_ubyte * 14)]


class SOCKET_ADDRESS(Structure):
    _fields_ = [('lpSockaddr', POINTER(SOCKADDR)), ('iSockaddrLength', ctypes.c_int)]


class IP_ADAPTER_UNICAST_ADDRESS_LH(Structure):
    pass


IP_ADAPTER_UNICAST_ADDRESS_LH._fields_ = [
    ('Length', c_ulong),
    ('Flags', c_ulong),
    ('Next', POINTER(IP_ADAPTER_UNICAST_ADDRESS_LH)),
    ('Address', SOCKET_ADDRESS),
    ('DnsSuffixLength', c_ulong),
    ('ValidLifetime', c_ulong),
    ('PreferredLifetime', c_ulong),
    ('LeaseLifetime', c_ulong),
    ('PrefixOrigin', c_ubyte),
    ('SuffixOrigin', c_ubyte),
    ('DadState', c_ubyte),
    ('ScopeId', c_ubyte),
]


class MIB_IPFORWARDROW(Structure):
    _fields_ = [(name, c_ulong) for name in (
        'ForwardDest', 'ForwardMask', 'ForwardPolicy', 'ForwardNextHop',
        'ForwardIfIndex', 'ForwardType', 'ForwardProto', 'ForwardAge',
        'ForwardNextHopAS', 'ForwardMetric1', 'ForwardMetric2',
        'ForwardMetric3', 'ForwardMetric4', 'ForwardMetric5',
    )]


class _IP_ADAPTER_ADDRESSES_LH(Structure):
    pass


class _IP_ADAPTER_ADDRESSES_ALIGNMENT(Union):
    _fields_ = [('Alignment', c_ulonglong), ('Length', c_ulong), ('IfIndex', c_ulong)]


_IP_ADAPTER_ADDRESSES_LH._fields_ = [
    ('Alignment', _IP_ADAPTER_ADDRESSES_ALIGNMENT),
    ('Next', POINTER(_IP_ADAPTER_ADDRESSES_LH)),
    ('AdapterName', c_char_p),
    ('FirstUnicastAddress', POINTER(IP_ADAPTER_UNICAST_ADDRESS_LH)),
    ('FirstAnycastAddress', c_void_p),
    ('FirstMulticastAddress', c_void_p),
    ('FirstDnsServerAddress', c_void_p),
    ('DnsSuffix', c_void_p),
    ('Description', c_void_p),
    ('FriendlyName', c_void_p),
    ('PhysicalAddress', ctypes.c_ubyte * 8),
    ('PhysicalAddressLength', c_ulong),
    ('Flags', c_ulong),
    ('Mtu', c_ulong),
    ('IfType', c_ulong),
    ('OperStatus', c_ulong),
    ('Ipv6IfIndex', c_ulong),
    ('ZoneIndices', c_ulong * 16),
    ('FirstPrefix', c_void_p),
    ('TransmitLinkSpeed', c_ulonglong),
    ('ReceiveLinkSpeed', c_ulonglong),
]


def _string(pointer):
    if not pointer:
        return ''
    return ctypes.wstring_at(pointer)


def _ipv4(sockaddr):
    if not sockaddr or not sockaddr.lpSockaddr or sockaddr.iSockaddrLength < 16:
        return None
    address = sockaddr.lpSockaddr.contents
    if address.sa_family != AF_INET:
        return None
    raw = ctypes.string_at(ctypes.addressof(address) + 8, 4)
    return '.'.join(str(byte) for byte in raw)


def _ipv4_number(value):
    # Windows route-table DWORDs store IPv4 bytes in network order; loading
    # them on little-endian Windows reverses the numeric byte order.
    return '.'.join(str((value >> shift) & 255) for shift in (0, 8, 16, 24))


def enumerate_interfaces():
    library = ctypes.windll.iphlpapi
    library.GetAdaptersAddresses.argtypes = (ctypes.c_ulong, c_ulong, c_void_p,
                                             POINTER(_IP_ADAPTER_ADDRESSES_LH), POINTER(c_ulong))
    library.GetAdaptersAddresses.restype = c_ulong
    flags = GAA_FLAG_SKIP_ANYCAST | GAA_FLAG_SKIP_MULTICAST | GAA_FLAG_SKIP_DNS_SERVER
    size = c_ulong(0)
    result = library.GetAdaptersAddresses(AF_INET, flags, None, None, ctypes.byref(size))
    if result != ERROR_BUFFER_OVERFLOW:
        return []
    buffer = ctypes.create_string_buffer(size.value)
    adapter = ctypes.cast(buffer, ctypes.POINTER(_IP_ADAPTER_ADDRESSES_LH))
    result = library.GetAdaptersAddresses(AF_INET, flags, None, adapter, ctypes.byref(size))
    if result:
        return []
    rows = []
    seen = set()
    while adapter:
        item = adapter.contents
        identifier = item.AdapterName.decode('utf-8', 'replace') if item.AdapterName else ''
        name = _string(item.FriendlyName) or _string(item.Description) or identifier
        addresses = []
        unicast = item.FirstUnicastAddress
        for _ in range(256):
            if not unicast:
                break
            value = _ipv4(unicast.contents.Address)
            if value and value not in addresses:
                addresses.append(value)
            unicast = unicast.contents.Next
        key = (identifier, name)
        if key not in seen:
            seen.add(key)
            rows.append({'id': identifier, 'name': name, 'addresses': addresses,
                         'index': item.Alignment.IfIndex, 'if_type': item.IfType})
        adapter = item.Next
    return rows


def default_route():
    library = ctypes.windll.iphlpapi
    library.GetBestRoute.argtypes = (c_ulong, c_ulong, POINTER(MIB_IPFORWARDROW))
    library.GetBestRoute.restype = c_ulong
    route = MIB_IPFORWARDROW()
    if library.GetBestRoute(0, 0, ctypes.byref(route)):
        return {}
    return {'type': 'default', 'index': route.ForwardIfIndex,
            'gateway': _ipv4_number(route.ForwardNextHop)}
