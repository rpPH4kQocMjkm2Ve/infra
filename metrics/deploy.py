#!/usr/bin/env python3
"""deploy.py - Metrics (Prometheus + Grafana) deployer"""

import subprocess
import sys
import tempfile
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib.sops import decrypt_sops
from lib.remote import ssh_run, ssh_read_file, rsync_file
from lib.jinja import create_jinja_env

TEMPLATES_DIR = Path(__file__).parent / 'templates'
SECRETS_FILE = Path(__file__).parent / 'secrets' / 'secrets.enc.yaml'
REMOTE_BASE = '/opt/podman/metrics'

FILES = [
    ('metrics.pod.j2', '/etc/containers/systemd/metrics.pod'),
    ('1-prometheus.container.j2', '/etc/containers/systemd/1-prometheus.container'),
    ('2-node-exporter.container.j2', '/etc/containers/systemd/2-node-exporter.container'),
    ('3-grafana.container.j2', '/etc/containers/systemd/3-grafana.container'),
    ('prometheus.yml.j2', f'{REMOTE_BASE}/prometheus/prometheus.yml'),
]

SETUP_DIRS = [f'{REMOTE_BASE}/prometheus']


def get_target(secrets: dict, instance_name: str) -> tuple[str, int]:
    instance = secrets['instances'][instance_name]
    user = instance.get('ssh_user', secrets['common'].get('ssh_user', 'root'))
    port = instance.get('ssh_port', secrets['common'].get('ssh_port', 22))
    return f"{user}@{instance['host']}", port


def build_context(secrets: dict, instance_name: str) -> dict:
    return {
        'common': secrets['common'],
        'instance': secrets['instances'][instance_name],
        'instance_name': instance_name,
    }


def cmd_list(secrets: dict) -> None:
    for name, data in secrets['instances'].items():
        print(f"  {name}\t{data['host']}")


def cmd_render(secrets: dict, env, instance_name: str) -> None:
    ctx = build_context(secrets, instance_name)
    for tpl, remote_path in FILES:
        name = tpl.removesuffix('.j2')
        print(f"\033[1;33m═══ {name} → {remote_path} ═══\033[0m")
        print(env.get_template(tpl).render(**ctx))
        print()


def cmd_diff(secrets: dict, env, instance_name: str) -> None:
    ctx = build_context(secrets, instance_name)
    target, port = get_target(secrets, instance_name)
    for tpl, remote_path in FILES:
        name = tpl.removesuffix('.j2')
        rendered = env.get_template(tpl).render(**ctx)
        remote_content = ssh_read_file(target, remote_path, port)
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


def cmd_deploy(secrets: dict, env, instance_name: str, no_restart: bool = False) -> None:
    ctx = build_context(secrets, instance_name)
    target, port = get_target(secrets, instance_name)
    print(f"\033[1;33m→\033[0m deploying metrics to {instance_name} ({target})")

    ssh_run(target, f"mkdir -p {' '.join(SETUP_DIRS)}", port)

    changed = False
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        for tpl, remote_path in FILES:
            rendered = env.get_template(tpl).render(**ctx)
            local_file = tmpdir / tpl.removesuffix('.j2')
            local_file.write_text(rendered)
            if rsync_file(local_file, target, remote_path, port):
                print(f"  \033[1;33m→\033[0m {tpl.removesuffix('.j2')} updated")
                changed = True
            else:
                print(f"  \033[0;32m✓\033[0m {tpl.removesuffix('.j2')} unchanged")

    if not no_restart and changed:
        ssh_run(target, "systemctl daemon-reload && systemctl restart metrics-pod", port)
        print(f"  \033[0;32m✓\033[0m restarted")
    elif not changed:
        print(f"  \033[0;32m✓\033[0m no changes")

    print(f"\033[0;32m✓\033[0m {instance_name} done\n")


def main():
    parser = argparse.ArgumentParser(
        description='Metrics deployer',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python deploy.py list
  python deploy.py render server1
  python deploy.py diff server1
  python deploy.py deploy server1
  python deploy.py deploy --all
  python deploy.py deploy --all --no-restart
        """
    )
    parser.add_argument('command', choices=['list', 'render', 'diff', 'deploy'])
    parser.add_argument('instance', nargs='?')
    parser.add_argument('-s', '--secrets', default=str(SECRETS_FILE))
    parser.add_argument('--all', action='store_true')
    parser.add_argument('--no-restart', action='store_true')
    args = parser.parse_args()

    secrets = decrypt_sops(Path(args.secrets))
    env = create_jinja_env(TEMPLATES_DIR)

    if args.command == 'list':
        cmd_list(secrets)
        return

    # Determine targets
    if args.all:
        instances = list(secrets['instances'].keys())
    elif args.instance:
        if args.instance not in secrets['instances']:
            print(f"Instance '{args.instance}' not found", file=sys.stderr)
            print(f"Available: {', '.join(secrets['instances'].keys())}", file=sys.stderr)
            sys.exit(1)
        instances = [args.instance]
    else:
        parser.error(f"'{args.command}' requires instance name or --all")

    for instance in instances:
        if args.command == 'render':
            cmd_render(secrets, env, instance)
        elif args.command == 'diff':
            cmd_diff(secrets, env, instance)
        elif args.command == 'deploy':
            cmd_deploy(secrets, env, instance, no_restart=args.no_restart)


if __name__ == '__main__':
    main()
