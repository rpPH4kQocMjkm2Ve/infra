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
        ('sshd_config.j2', '/etc/ssh/sshd_config'),
        ('10-default-sysctl.conf.j2', '/etc/sysctl.d/10-default.conf'),
        ('11-overcommit_memory.conf.j2', '/etc/sysctl.d/11-overcommit_memory.conf'),
        ('10-default.network.j2', '/etc/systemd/network/10-default.network'),
        ('journald.conf.j2', '/etc/systemd/journald.conf'),
        ('paccache.timer.j2', '/etc/systemd/system/10-paccache_user.timer'),
        ('paccache.service.j2', '/etc/systemd/system/10-paccache_user.service'),
        ('btrfs-scrub.timer.j2', '/etc/systemd/system/10-btrfs_scrub.timer'),
        ('btrfs-scrub.service.j2', '/etc/systemd/system/10-btrfs_scrub.service'),
        ('sysctl-boot.timer.j2', '/etc/systemd/system/10-sysctl_user.timer'),
        ('sysctl-boot.service.j2', '/etc/systemd/system/10-sysctl_user.service'),
    ],
    'restart_cmd': (
        'sshd -t && '
        'systemctl daemon-reload && '
        'sysctl --system && '
        'systemctl restart sshd && '
        'systemctl try-reload-or-restart systemd-journald && '
        'systemctl enable --now 10-paccache_user.timer 10-btrfs_scrub.timer 10-sysctl_user.timer'
    ),
})

if __name__ == '__main__':
    deployer.run_cli()
