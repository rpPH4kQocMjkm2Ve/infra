import subprocess
import sys
from pathlib import Path


def ssh_run(target: str, cmd: str, port: int = 22) -> None:
    result = subprocess.run(
        ['ssh', '-p', str(port), target, cmd],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"  SSH error: {result.stderr.strip()}", file=sys.stderr)


def ssh_read_file(target: str, path: str, port: int = 22) -> str:
    result = subprocess.run(
        ['ssh', '-p', str(port), target, f'cat {path} 2>/dev/null || true'],
        capture_output=True, text=True
    )
    return result.stdout


def rsync_file(local: Path, target: str, remote: str, port: int = 22) -> bool:
    result = subprocess.run(
        ['rsync', '-az', '--checksum', '--itemize-changes',
         '-e', f'ssh -p {port}',
         str(local), f'{target}:{remote}'],
        capture_output=True, text=True
    )
    return bool(result.stdout.strip())


def write_secret_remote(target: str, content: str, path: str, port: int = 22) -> None:
    subprocess.run(
        ['ssh', '-p', str(port), target, f'cat > {path} && chmod 600 {path}'],
        input=content, text=True, check=True
    )
