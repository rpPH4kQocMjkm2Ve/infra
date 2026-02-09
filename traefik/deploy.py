#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib.deploy import ServiceDeployer
from lib.remote import write_secret_remote

BASE = Path(__file__).parent
REMOTE_BASE = '/opt/podman/traefik'


def write_cf_secrets(secrets, target, port):
    write_secret_remote(target, secrets['common']['cf_email'], f'{REMOTE_BASE}/cf_email', port)
    write_secret_remote(target, secrets['common']['cf_api_token'], f'{REMOTE_BASE}/cf_token', port)
    print(f"  \033[0;32m✓\033[0m secrets written")


def traefik_context(secrets, instance_name):
    return {
        'common': secrets['common'],
        'instance': secrets['instances'][instance_name],
    }


deployer = ServiceDeployer({
    'templates_dir': BASE / 'templates',
    'secrets_file': BASE / 'secrets' / 'secrets.enc.yaml',
    'multi_instance': True,
    'context_builder': traefik_context,
    'files': [
        ('traefik.yml.j2', f'{REMOTE_BASE}/settings/traefik.yml'),
        ('dynamic1.yml.j2', f'{REMOTE_BASE}/settings/dynamic/dynamic1.yml'),
        ('traefik.container.j2', '/etc/containers/systemd/traefik.container'),
    ],
    'setup_dirs': [
        f'{REMOTE_BASE}/settings/dynamic',
        f'{REMOTE_BASE}/google_acme',
        f'{REMOTE_BASE}/logs',
    ],
    'restart_cmd': 'systemctl daemon-reload && systemctl restart traefik',
    'secrets_hooks': [write_cf_secrets],
})

if __name__ == '__main__':
    deployer.run_cli()
