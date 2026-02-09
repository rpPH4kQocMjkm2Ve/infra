#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib.deploy import ServiceDeployer

BASE = Path(__file__).parent
REMOTE_BASE = '/opt/podman/nextcloud'

deployer = ServiceDeployer({
    'templates_dir': BASE / 'templates',
    'secrets_file': BASE / 'secrets' / 'secrets.enc.yaml',
    'files': [
        ('nextcloud.pod.j2', '/etc/containers/systemd/nextcloud.pod'),
        ('1-mariadb.container.j2', '/etc/containers/systemd/1-mariadb.container'),
        ('2-valkey.container.j2', '/etc/containers/systemd/2-valkey.container'),
        ('3-nextcloud-app.container.j2', '/etc/containers/systemd/3-nextcloud-app.container'),
        ('4-nginx.container.j2', '/etc/containers/systemd/4-nginx.container'),
        ('nginx.conf.j2', f'{REMOTE_BASE}/nginx.conf'),
        ('config.php.j2', f'{REMOTE_BASE}/nextcloud/config/config.php'),
    ],
    'setup_dirs': [f'{REMOTE_BASE}/db', f'{REMOTE_BASE}/nextcloud/config', f'{REMOTE_BASE}/log'],
    'restart_cmd': 'systemctl daemon-reload && systemctl restart nextcloud-pod',
})

if __name__ == '__main__':
    deployer.run_cli()
