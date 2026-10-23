"""Windows interface and default-route enumeration through iphlpapi.

Windows ULONG/DWORD stay 32-bit on x64 (unlike POSIX unsigned long), so
fixed-width ctypes also let ABI fixtures run correctly on macOS and Linux.
"""
import ctypes
import threading
from ctypes import c_char_p, c_ubyte, c_uint32, c_ulonglong, c_ushort, c_void_p, POINTER, Structure, Union


AF_INET = 2
ERROR_BUFFER_OVERFLOW = 111
GAA_FLAG_SKIP_ANYCAST = 2
GAA_FLAG_SKIP_MULTICAST = 4
GAA_FLAG_SKIP_DNS_SERVER = 8
IF_TYPE_SOFTWARE_LOOPBACK = 24
IF_TYPE_TUNNEL = 131


class SOCKADDR(Structure):
    _fields_ = [('sa_family', c_ushort), ('sa_data', c_ubyte * 14)]


class SOCKET_ADDRESS(Structure):
    _fields_ = [('lpSockaddr', POINTER(SOCKADDR)), ('iSockaddrLength', ctypes.c_int)]


class IP_ADAPTER_UNICAST_ADDRESS_LH(Structure):
    pass


class _UNICAST_HEADER(Structure):
    _fields_ = [('Length', c_uint32), ('Flags', c_uint32)]


class _UNICAST_ALIGNMENT(Union):
    _anonymous_ = ('Header',)
    _fields_ = [('Alignment', c_ulonglong), ('Header', _UNICAST_HEADER)]


IP_ADAPTER_UNICAST_ADDRESS_LH._anonymous_ = ('Header',)
IP_ADAPTER_UNICAST_ADDRESS_LH._fields_ = [
    ('Header', _UNICAST_ALIGNMENT),
    ('Next', POINTER(IP_ADAPTER_UNICAST_ADDRESS_LH)),
    ('Address', SOCKET_ADDRESS),
    ('PrefixOrigin', ctypes.c_int32),
    ('SuffixOrigin', ctypes.c_int32),
    ('DadState', ctypes.c_int32),
    ('ValidLifetime', c_uint32),
    ('PreferredLifetime', c_uint32),
    ('LeaseLifetime', c_uint32),
    ('OnLinkPrefixLength', c_ubyte),
]


class MIB_IPFORWARDROW(Structure):
    _fields_ = [(name, c_uint32) for name in (
        'ForwardDest', 'ForwardMask', 'ForwardPolicy', 'ForwardNextHop',
        'ForwardIfIndex', 'ForwardType', 'ForwardProto', 'ForwardAge',
        'ForwardNextHopAS', 'ForwardMetric1', 'ForwardMetric2',
        'ForwardMetric3', 'ForwardMetric4', 'ForwardMetric5',
    )]


class _IP_ADAPTER_ADDRESSES_LH(Structure):
    pass


class _IP_ADAPTER_ADDRESSES_HEADER(Structure):
    _fields_ = [('Length', c_uint32), ('IfIndex', c_uint32)]


class _IP_ADAPTER_ADDRESSES_ALIGNMENT(Union):
    _anonymous_ = ('Header',)
    _fields_ = [('Alignment', c_ulonglong), ('Header', _IP_ADAPTER_ADDRESSES_HEADER)]


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
    ('PhysicalAddressLength', c_uint32),
    ('Flags', c_uint32),
    ('Mtu', c_uint32),
    ('IfType', c_uint32),
    ('OperStatus', c_uint32),
    ('Ipv6IfIndex', c_uint32),
    ('ZoneIndices', c_uint32 * 16),
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
    raw = ctypes.string_at(ctypes.addressof(address) + 4, 4)
    return '.'.join(str(byte) for byte in raw)


def _ipv4_number(value):
    # Windows route-table DWORDs store IPv4 bytes in network order; loading
    # them on little-endian Windows reverses the numeric byte order.
    return '.'.join(str((value >> shift) & 255) for shift in (0, 8, 16, 24))


def enumerate_interfaces():
    library = ctypes.windll.iphlpapi
    library.GetAdaptersAddresses.argtypes = (ctypes.c_uint32, c_uint32, c_void_p,
                                             POINTER(_IP_ADAPTER_ADDRESSES_LH), POINTER(c_uint32))
    library.GetAdaptersAddresses.restype = c_uint32
    flags = GAA_FLAG_SKIP_ANYCAST | GAA_FLAG_SKIP_MULTICAST | GAA_FLAG_SKIP_DNS_SERVER
    size = c_uint32(0)
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
    library.GetBestRoute.argtypes = (c_uint32, c_uint32, POINTER(MIB_IPFORWARDROW))
    library.GetBestRoute.restype = c_uint32
    route = MIB_IPFORWARDROW()
    if library.GetBestRoute(0, 0, ctypes.byref(route)):
        return {}
    return {'type': 'default', 'index': route.ForwardIfIndex,
            'gateway': _ipv4_number(route.ForwardNextHop)}


class _NetworkWatcher:
    """Keep the Win32 callback alive until both registrations are cancelled."""
    def __init__(self, library, callback, callback_type):
        self._library = library
        self._callback = callback
        self._lock = threading.RLock()
        self._closed = False
        self._handles = []
        self._native_callback = callback_type(self._changed)
        library.CancelMibChangeNotify2.argtypes = (c_void_p,)
        library.CancelMibChangeNotify2.restype = c_uint32
        try:
            for name in ('NotifyUnicastIpAddressChange', 'NotifyRouteChange2'):
                register = getattr(library, name)
                register.argtypes = (c_ushort, callback_type, c_void_p, c_ubyte,
                                     POINTER(c_void_p))
                register.restype = c_uint32
                handle = c_void_p()
                result = register(AF_INET, self._native_callback, None, False,
                                  ctypes.byref(handle))
                if result:
                    raise OSError(result, 'Network change notification unavailable')
                self._handles.append(handle)
        except Exception:
            self.close()
            raise

    def _changed(self, _context, _row, _notification_type):
        with self._lock:
            if not self._closed:
                self._callback()

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
        # Never cancel while holding a lock needed by the native callback:
        # CancelMibChangeNotify2 waits for any outstanding callback to finish.
        failed = []
        for handle in self._handles:
            if self._library.CancelMibChangeNotify2(handle):
                failed.append(handle)
        self._handles = failed
        if failed:
            # The OS may still own the C function pointer. Suppress callbacks
            # but retain it until process exit instead of freeing live memory.
            _uncancelled_watchers.append(self)


_uncancelled_watchers = []


def watch_changes(callback):
    """Subscribe to IPv4 address and route changes without a polling thread."""
    try:
        return _NetworkWatcher(ctypes.windll.iphlpapi, callback,
                               ctypes.WINFUNCTYPE(None, c_void_p, c_void_p,
                                                 ctypes.c_int32))
    except (OSError, AttributeError):
        return None
