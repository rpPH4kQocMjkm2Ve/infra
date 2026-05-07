#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib.deploy import ServiceDeployer

BASE = Path(__file__).parent

def build_context(secrets, instance_name):
    instance = secrets['instances'][instance_name]
    port = instance.get('port') or secrets['common']['port']

    return {
        **secrets,
        'current_instance': {
            **instance,
            'port': port,
        },
    }

deployer = ServiceDeployer({
    'templates_dir': BASE / 'templates',
    'secrets_file': BASE / 'secrets' / 'secrets.enc.yaml',
    'multi_instance': True,
    'context_builder': build_context,
    'files': [
        ('i2pd.conf.j2', '/etc/i2pd/i2pd.conf'),
    ],
    'setup_dirs': ['/etc/i2pd'],
})

if __name__ == '__main__':
    deployer.run_cli()
