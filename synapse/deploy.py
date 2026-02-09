#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib.deploy import ServiceDeployer
from lib.remote import write_secret_remote

REMOTE_BASE = '/opt/podman/synapse'
BASE = Path(__file__).parent


def write_signing_key(secrets, target, port):
    sk = secrets.get('synapse', {}).get('signing_key')
    if sk:
        sk_path = f"{REMOTE_BASE}/data/{secrets['synapse']['server_name']}.signing.key"
        write_secret_remote(target, sk, sk_path, port)
        print(f"  \033[0;32m✓\033[0m signing key written")


deployer = ServiceDeployer({
    'templates_dir': BASE / 'templates',
    'secrets_file': BASE / 'secrets' / 'secrets.enc.yaml',
    'files': [
        ('synapse.pod.j2', '/etc/containers/systemd/synapse.pod'),
        ('1-postgresql.container.j2', '/etc/containers/systemd/1-postgresql.container'),
        ('2-synapse.container.j2', '/etc/containers/systemd/2-synapse.container'),
        ('homeserver.yaml.j2', f'{REMOTE_BASE}/data/homeserver.yaml'),
        ('log.config.j2', lambda s: f"{REMOTE_BASE}/data/{s['synapse']['server_name']}.log.config"),
    ],
    'setup_dirs': [f'{REMOTE_BASE}/data', f'{REMOTE_BASE}/db'],
    'restart_cmd': 'systemctl daemon-reload && systemctl restart synapse-pod',
    'secrets_hooks': [write_signing_key],
})

if __name__ == '__main__':
    deployer.run_cli()
