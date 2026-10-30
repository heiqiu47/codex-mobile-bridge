"""Bounded subprocess input without a synchronous Windows pipe write."""
import subprocess
import tempfile


def run_with_input(command, source, **options):
    # Windows communicate() writes PIPE input before enforcing its timeout.
    # A private inherited file handle lets an offline SSH process time out even
    # when it never reads the script. The file is removed on every exit path.
    with tempfile.TemporaryFile() as stream:
        stream.write(source.encode('utf-8') if isinstance(source, str) else source)
        stream.seek(0)
        return subprocess.run(command, stdin=stream, **options)
