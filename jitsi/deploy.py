#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib.deploy import ServiceDeployer

BASE = Path(__file__).parent

deployer = ServiceDeployer({
    'templates_dir': BASE / 'templates',
    'secrets_file': BASE / 'secrets' / 'secrets.enc.yaml',
    'files': [
        ('jitsi.env.j2',              '/opt/podman/jitsi/jitsi.env'),
        ('meet-jitsi.network.j2',     '/etc/containers/systemd/meet-jitsi.network'),
        ('2-prosody.container.j2',    '/etc/containers/systemd/2-prosody.container'),
        ('3-jicofo.container.j2',     '/etc/containers/systemd/3-jicofo.container'),
        ('3-jvb.container.j2',        '/etc/containers/systemd/3-jvb.container'),
        ('4-jitsi-web.container.j2',  '/etc/containers/systemd/4-jitsi-web.container'),
    ],
    'setup_dirs': [
        '/opt/podman/jitsi',
        '/opt/podman/jitsi/jitsi-meet-cfg/jicofo',
        '/opt/podman/jitsi/jitsi-meet-cfg/jvb',
        '/opt/podman/jitsi/jitsi-meet-cfg/jigasi',
        '/opt/podman/jitsi/jitsi-meet-cfg/jibri',
        '/opt/podman/jitsi/jitsi-meet-cfg/prosody/config',
        '/opt/podman/jitsi/jitsi-meet-cfg/prosody/prosody-plugins-custom',
        '/opt/podman/jitsi/jitsi-meet-cfg/transcripts',
        '/opt/podman/jitsi/jitsi-meet-cfg/web/crontabs',
        '/opt/podman/jitsi/jitsi-meet-cfg/web/load-test',
    ],
    'restart_cmd': (
        'systemctl daemon-reload && '
        'systemctl restart 2-prosody && sleep 3 && '
        'systemctl restart 3-jicofo 3-jvb && sleep 2 && '
        'systemctl restart 4-jitsi-web'
    ),
})

if __name__ == '__main__':
    deployer.run_cli()
