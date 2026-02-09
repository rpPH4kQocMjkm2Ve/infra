#!/usr/bin/env python3
"""deploy.py - Traefik config generator and deployer"""

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
REMOTE_BASE = '/opt/podman/traefik'


def get_target(secrets: dict, instance_name: str) -> tuple[str, int]:
    instance = secrets['instances'][instance_name]
    user = instance.get('ssh_user', secrets['common'].get('ssh_user', 'root'))
    port = instance.get('ssh_port', secrets['common'].get('ssh_port', 22))
    return f"{user}@{instance['domain']}", port


def build_context(secrets: dict, instance_name: str) -> dict:
    return {
        'common': secrets['common'],
        'instance': secrets['instances'][instance_name],
    }


def cmd_list(secrets: dict) -> None:
    for name, data in secrets['instances'].items():
        print(f"  {name}\t{data['domain']}")


def cmd_render(secrets: dict, env, instance_name: str) -> None:
    if instance_name not in secrets['instances']:
        print(f"Instance '{instance_name}' not found", file=sys.stderr)
        sys.exit(1)
    ctx = build_context(secrets, instance_name)
    for tpl in ['traefik.yml.j2', 'dynamic1.yml.j2', 'traefik.container.j2']:
        name = tpl.removesuffix('.j2')
        print(f"\033[1;33m═══ {name} ═══\033[0m")
        print(env.get_template(tpl).render(**ctx))
        print()


def cmd_diff(secrets: dict, env, instance_name: str) -> None:
    if instance_name not in secrets['instances']:
        print(f"Instance '{instance_name}' not found", file=sys.stderr)
        sys.exit(1)
    ctx = build_context(secrets, instance_name)
    target, port = get_target(secrets, instance_name)
    files = {
        'traefik.yml.j2': f'{REMOTE_BASE}/settings/traefik.yml',
        'dynamic1.yml.j2': f'{REMOTE_BASE}/settings/dynamic/dynamic1.yml',
    }
    for tpl, remote_path in files.items():
        name = tpl.removesuffix('.j2')
        rendered = env.get_template(tpl).render(**ctx)
        remote_content = ssh_read_file(target, remote_path, port)
        if rendered == remote_content:
            print(f"\033[0;32m✓\033[0m {name} — no changes")
        else:
            print(f"\033[1;33m→\033[0m {name} — differs:")
            with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as lf, \
                 tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as rf:
                lf.write(rendered); lf.flush()
                rf.write(remote_content); rf.flush()
                subprocess.run(['diff', '--color', '-u', rf.name, lf.name])
            print()


def cmd_deploy(secrets: dict, env, instance_name: str, restart: bool = True) -> None:
    if instance_name not in secrets['instances']:
        print(f"Instance '{instance_name}' not found", file=sys.stderr)
        sys.exit(1)
    ctx = build_context(secrets, instance_name)
    target, port = get_target(secrets, instance_name)
    print(f"\033[1;33m→\033[0m deploying {instance_name} ({target}:{port})")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        files = {
            'traefik.yml.j2': ('traefik.yml', f'{REMOTE_BASE}/settings/traefik.yml'),
            'dynamic1.yml.j2': ('dynamic1.yml', f'{REMOTE_BASE}/settings/dynamic/dynamic1.yml'),
            'traefik.container.j2': ('traefik.container', '/etc/containers/systemd/traefik.container'),
        }
        ssh_run(target, f"mkdir -p {REMOTE_BASE}/settings/dynamic {REMOTE_BASE}/google_acme {REMOTE_BASE}/logs", port)

        changed = False
        for tpl, (local_name, remote_path) in files.items():
            rendered = env.get_template(tpl).render(**ctx)
            local_file = tmpdir / local_name
            local_file.write_text(rendered)
            if rsync_file(local_file, target, remote_path, port):
                print(f"  \033[1;33m→\033[0m {local_name} updated")
                changed = True
            else:
                print(f"  \033[0;32m✓\033[0m {local_name} unchanged")

        cf_email = secrets['common']['cf_email']
        cf_token = secrets['common']['cf_api_token']
        write_secret_remote(target, cf_email, f'{REMOTE_BASE}/cf_email', port)
        write_secret_remote(target, cf_token, f'{REMOTE_BASE}/cf_token', port)
        print(f"  \033[0;32m✓\033[0m secrets written")

        if restart and changed:
            ssh_run(target, "systemctl daemon-reload && systemctl restart traefik", port)
            print(f"  \033[0;32m✓\033[0m traefik restarted")
        elif not changed:
            print(f"  \033[0;32m✓\033[0m no changes, skipping restart")

    print(f"\033[0;32m✓\033[0m {instance_name} done\n")


def main():
    parser = argparse.ArgumentParser(description='Traefik config deployer')
    parser.add_argument('command', choices=['list', 'render', 'diff', 'deploy'])
    parser.add_argument('instance', nargs='?')
    parser.add_argument('-s', '--secrets', default=str(SECRETS_FILE))
    parser.add_argument('-t', '--templates', default=str(TEMPLATES_DIR))
    parser.add_argument('--all', action='store_true')
    parser.add_argument('--no-restart', action='store_true')
    args = parser.parse_args()

    secrets = decrypt_sops(Path(args.secrets))
    env = create_jinja_env(Path(args.templates))

    if args.command == 'list':
        cmd_list(secrets)
        return

    if args.all:
        instances = list(secrets['instances'].keys())
    elif args.instance:
        instances = [args.instance]
    else:
        parser.error(f"'{args.command}' requires instance name or --all")

    for instance in instances:
        if args.command == 'render':
            cmd_render(secrets, env, instance)
        elif args.command == 'diff':
            cmd_diff(secrets, env, instance)
        elif args.command == 'deploy':
            cmd_deploy(secrets, env, instance, restart=not args.no_restart)


if __name__ == '__main__':
    main()
