#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib.deploy import ServiceDeployer

BASE = Path(__file__).parent
REMOTE_BASE = '/opt/podman/element_synapse_admin'

deployer = ServiceDeployer({
    'templates_dir': BASE / 'templates',
    'secrets_file': BASE / 'secrets' / 'secrets.enc.yaml',
    'files': [
        ('element-web.container.j2', '/etc/containers/systemd/element-web.container'),
        ('synapse-admin.container.j2', '/etc/containers/systemd/synapse-admin.container'),
        ('element_config.json.j2', f'{REMOTE_BASE}/element_config.json'),
        ('synapse_config.json.j2', f'{REMOTE_BASE}/synapse_config.json'),
    ],
    'setup_dirs': [REMOTE_BASE],
    'restart_cmd': 'systemctl daemon-reload && systemctl restart element-web synapse-admin',
})

if __name__ == '__main__':
    deployer.run_cli()
