#!/usr/bin/env python3
"""deploy.py - Synapse deployer"""

import subprocess
import sys
import tempfile
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib.sops import decrypt_sops
from lib.remote import ssh_run, ssh_read_file, rsync_file, write_secret_remote
from lib.jinja import create_jinja_env

TEMPLATES_DIR = Path(__file__).parent / 'templates'
SECRETS_FILE = Path(__file__).parent / 'secrets' / 'secrets.enc.yaml'
REMOTE_BASE = '/opt/podman/synapse'

FILES = [
    ('synapse.pod.j2', '/etc/containers/systemd/synapse.pod'),
    ('1-postgresql.container.j2', '/etc/containers/systemd/1-postgresql.container'),
    ('2-synapse.container.j2', '/etc/containers/systemd/2-synapse.container'),
    ('homeserver.yaml.j2', f'{REMOTE_BASE}/data/homeserver.yaml'),
    ('log.config.j2', None),  # remote_path вычисляется динамически
]

SETUP_DIRS = [f'{REMOTE_BASE}/data', f'{REMOTE_BASE}/db']


def get_target(secrets: dict) -> tuple[str, int]:
    ssh = secrets['ssh']
    return f"{ssh.get('user', 'root')}@{ssh['host']}", ssh.get('port', 22)


def get_remote_path(tpl: str, remote_path, secrets: dict) -> str:
    if remote_path is not None:
        return remote_path
    if tpl == 'log.config.j2':
        return f"{REMOTE_BASE}/data/{secrets['synapse']['server_name']}.log.config"
    raise ValueError(f"No remote path for {tpl}")


def cmd_render(secrets: dict, env) -> None:
    for tpl, remote_path in FILES:
        rp = get_remote_path(tpl, remote_path, secrets)
        name = tpl.removesuffix('.j2')
        print(f"\033[1;33m═══ {name} → {rp} ═══\033[0m")
        print(env.get_template(tpl).render(**secrets))
        print()


def cmd_diff(secrets: dict, env) -> None:
    target, port = get_target(secrets)
    for tpl, remote_path in FILES:
        rp = get_remote_path(tpl, remote_path, secrets)
        name = tpl.removesuffix('.j2')
        rendered = env.get_template(tpl).render(**secrets)
        remote_content = ssh_read_file(target, rp, port)
        if rendered == remote_content:
            print(f"\033[0;32m✓\033[0m {name}")
        else:
            print(f"\033[1;33m→\033[0m {name} differs")
            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as lf, \
                 tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as rf:
                lf.write(rendered); lf.flush()
                rf.write(remote_content); rf.flush()
                subprocess.run(['diff', '--color', '-u', rf.name, lf.name])
            print()


def cmd_deploy(secrets: dict, env, no_restart: bool = False) -> None:
    target, port = get_target(secrets)
    print(f"\033[1;33m→\033[0m deploying synapse to {target}")

    ssh_run(target, f"mkdir -p {' '.join(SETUP_DIRS)}", port)

    changed = False
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        for tpl, remote_path in FILES:
            rp = get_remote_path(tpl, remote_path, secrets)
            rendered = env.get_template(tpl).render(**secrets)
            local_file = tmpdir / tpl.removesuffix('.j2')
            local_file.write_text(rendered)
            if rsync_file(local_file, target, rp, port):
                print(f"  \033[1;33m→\033[0m {tpl.removesuffix('.j2')} updated")
                changed = True
            else:
                print(f"  \033[0;32m✓\033[0m {tpl.removesuffix('.j2')} unchanged")

    # Signing key — чистый секрет, не шаблон
    sk = secrets.get('synapse', {}).get('signing_key')
    if sk:
        sk_path = f"{REMOTE_BASE}/data/{secrets['synapse']['server_name']}.signing.key"
        write_secret_remote(target, sk, sk_path, port)
        print(f"  \033[0;32m✓\033[0m signing key written")

    if not no_restart and changed:
        ssh_run(target, "systemctl daemon-reload && systemctl restart synapse-pod", port)
        print(f"  \033[0;32m✓\033[0m restarted")
    elif not changed:
        print(f"  \033[0;32m✓\033[0m no changes")

    print(f"\033[0;32m✓\033[0m done\n")


def main():
    parser = argparse.ArgumentParser(description='Synapse deployer')
    parser.add_argument('command', choices=['render', 'diff', 'deploy'])
    parser.add_argument('-s', '--secrets', default=str(SECRETS_FILE))
    parser.add_argument('--no-restart', action='store_true')
    args = parser.parse_args()

    secrets = decrypt_sops(Path(args.secrets))
    env = create_jinja_env(TEMPLATES_DIR)

    if args.command == 'render':
        cmd_render(secrets, env)
    elif args.command == 'diff':
        cmd_diff(secrets, env)
    elif args.command == 'deploy':
        cmd_deploy(secrets, env, no_restart=args.no_restart)


if __name__ == '__main__':
    main()
