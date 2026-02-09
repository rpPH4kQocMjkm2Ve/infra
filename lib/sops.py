import subprocess
import sys
from pathlib import Path
import yaml


def decrypt_sops(file_path: Path) -> dict:
    try:
        result = subprocess.run(
            ['sops', '-d', str(file_path)],
            capture_output=True, text=True, check=True
        )
        return yaml.safe_load(result.stdout)
    except subprocess.CalledProcessError as e:
        print(f"SOPS decryption error: {e.stderr}", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError:
        print("sops not found in PATH", file=sys.stderr)
        sys.exit(1)
