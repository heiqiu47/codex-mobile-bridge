"""Linux interface and default-route enumeration."""
import json
import shutil
import subprocess


def enumerate_interfaces():
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
