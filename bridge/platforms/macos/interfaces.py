"""macOS interface and default-route enumeration."""
import os
import re
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
