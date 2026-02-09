#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib.deploy import ServiceDeployer

BASE = Path(__file__).parent
REMOTE_BASE = '/opt/podman/metrics'

deployer = ServiceDeployer({
    'templates_dir': BASE / 'templates',
    'secrets_file': BASE / 'secrets' / 'secrets.enc.yaml',
    'multi_instance': True,
    'files': [
        ('metrics.pod.j2', '/etc/containers/systemd/metrics.pod'),
        ('1-prometheus.container.j2', '/etc/containers/systemd/1-prometheus.container'),
        ('2-node-exporter.container.j2', '/etc/containers/systemd/2-node-exporter.container'),
        ('3-grafana.container.j2', '/etc/containers/systemd/3-grafana.container'),
        ('prometheus.yml.j2', f'{REMOTE_BASE}/prometheus/prometheus.yml'),
    ],
    'setup_dirs': [f'{REMOTE_BASE}/prometheus'],
    'restart_cmd': 'systemctl daemon-reload && systemctl restart metrics-pod',
})

if __name__ == '__main__':
    deployer.run_cli()
