"""Build a standalone WSL worker with an in-memory, account-only TOML fallback."""
import json

from bridge.resources import source_text


def worker_source():
    # Source files are copied byte-for-byte from pip's vendored Tomli 2.0.1.
    # No dependency is installed or written into the selected Linux environment.
    modules = {name: source_text('vendor/wsl_tomli/'+filename) for name, filename in (
        ('_types', '_types.py'), ('_re', '_re.py'), ('_parser', '_parser.py'), ('', '__init__.py'))}
    loader = '''
try:
    import tomllib
except ImportError:
    try:
        import tomli
    except ImportError:
        import sys, types
        _wsl_toml_sources = json.loads(SOURCES)
        _wsl_toml_package = types.ModuleType('_bridge_wsl_tomli')
        _wsl_toml_package.__path__ = []
        _wsl_toml_package.__package__ = '_bridge_wsl_tomli'
        sys.modules['_bridge_wsl_tomli'] = _wsl_toml_package
        for _part in ('_types', '_re', '_parser', ''):
            _name = '_bridge_wsl_tomli' + ('.'+_part if _part else '')
            _module = types.ModuleType(_name) if _part else _wsl_toml_package
            _module.__package__ = '_bridge_wsl_tomli'
            sys.modules[_name] = _module
            exec(compile(_wsl_toml_sources[_part], '<wsl-tomli:'+_part+'>', 'exec'), _module.__dict__)
        _WSL_TOML_LOADS = _wsl_toml_package.loads
'''.replace('SOURCES', repr(json.dumps(modules)))
    # The fallback loader has no external inputs and runs before target requests.
    models = source_text('features/auth/tls.py') + '\n'
    models += source_text('features/accounts/models.py').replace('from bridge.features.auth.tls import client_context', '') + '\n'
    return 'import json\n'+loader+'\n'+models+source_text('features/accounts/wsl_account_worker.py')
