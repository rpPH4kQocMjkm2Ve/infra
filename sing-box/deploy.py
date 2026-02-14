#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib.deploy import ServiceDeployer

BASE = Path(__file__).parent
REMOTE_BASE = '/opt/podman/sing-box'


def build_context(secrets, instance_name):
    instance = secrets['instances'][instance_name]
    warp_instance = secrets.get('warp', {}).get(instance_name, {})

    return {
        **secrets,
        'current_instance': {
            **instance,
            'warp_private_key': warp_instance.get('private_key', ''),
            'warp_ipv4': warp_instance.get('ipv4', ''),
            'warp_ipv6': warp_instance.get('ipv6', ''),
        },
        'instance_name': instance_name,
    }


deployer = ServiceDeployer({
    'templates_dir': BASE / 'templates',
    'secrets_file': BASE / 'secrets' / 'secrets.enc.yaml',
    'multi_instance': True,
    'context_builder': build_context,
    'files': [
        ('server_main.json.j2',     f'{REMOTE_BASE}/sing-box_settings/main.json'),
        ('server_inbounds.json.j2', f'{REMOTE_BASE}/sing-box_settings/inbounds.json'),
        ('server_ruleset.json.j2',  f'{REMOTE_BASE}/sing-box_settings/ruleset.json'),
        ('server_warp.json.j2',     f'{REMOTE_BASE}/sing-box_settings/warp.json'),
        ('server_container.j2',     '/etc/containers/systemd/sing-box.container'),
        ('server_pod.j2',           '/etc/containers/systemd/sing-box.pod'),
    ],
    'setup_dirs': [f'{REMOTE_BASE}/sing-box_settings'],
    'restart_cmd': 'systemctl daemon-reload && systemctl restart sing-box',
})

if __name__ == '__main__':
    deployer.run_cli()
