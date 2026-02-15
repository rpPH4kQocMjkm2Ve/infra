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
        ('public.xml.j2', '/etc/firewalld/zones/public.xml'),
        ('filter-closed.xml.j2', '/etc/firewalld/zones/filter-closed.xml'),
        ('wireguard.xml.j2', '/etc/firewalld/zones/wireguard.xml'),
        ('trusted.xml.j2', '/etc/firewalld/zones/trusted.xml'),
    ],
    'setup_dirs': ['/etc/firewalld/zones'],
    'restart_cmd': 'firewall-cmd --reload',
})

if __name__ == '__main__':
    deployer.run_cli()
