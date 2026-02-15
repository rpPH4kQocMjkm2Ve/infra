#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib.deploy import ServiceDeployer

BASE = Path(__file__).parent

deployer = ServiceDeployer({
    'templates_dir': BASE / 'templates',
    'secrets_file': BASE / 'secrets' / 'secrets.enc.yaml',
    'multi_instance': True,
    'files': [
        ('wg0.conf.j2', '/etc/wireguard/wg0.conf', {'owner': 'root:root', 'mode': '600'}),
    ],
    'setup_dirs': ['/etc/wireguard'],
    'restart_cmd': 'systemctl restart wg-quick@wg0',
})

if __name__ == '__main__':
    deployer.run_cli()
