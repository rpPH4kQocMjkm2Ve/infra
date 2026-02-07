#!/usr/bin/env python3
"""deploy.py - Traefik config generator and deployer"""

import subprocess
import sys
import tempfile
import argparse
from pathlib import Path
from typing import Optional

import yaml
from jinja2 import Environment, FileSystemLoader

TEMPLATES_DIR = Path(__file__).parent / 'templates'
SECRETS_FILE = Path(__file__).parent / 'secrets' / 'secrets.enc.yaml'
REMOTE_BASE = '/opt/podman/traefik'


# ── SOPS ─────────────────────────────────────────────

def decrypt_sops(file_path: Path) -> dict:
    try:
        result = subprocess.run(
            ['sops', '-d', str(file_path)],
            capture_output=True, text=True, check=True
        )
        return yaml.safe_load(result.stdout)
    except subprocess.CalledProcessError as e:
        print(f"SOPS decryption error: {e.stderr}", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError:
        print("SOPS not installed. Install sops", file=sys.stderr)
        sys.exit(1)


# ── Jinja2 ───────────────────────────────────────────

def create_jinja_env(templates_dir: Path) -> Environment:
    return Environment(
        loader=FileSystemLoader(templates_dir),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True
    )


def render_template(env: Environment, template_name: str, context: dict) -> str:
    template = env.get_template(template_name)
    return template.render(**context)


# ── SSH / rsync ──────────────────────────────────────

def get_ssh_port(secrets: dict, instance_name: str) -> int:
    """Get SSH port: instance-level overrides common, default 22."""
    instance = secrets['instances'][instance_name]
    return instance.get('ssh_port', secrets['common'].get('ssh_port', 22))

def get_ssh_user(secrets: dict, instance_name: str) -> str:
    """Get SSH user: instance-level overrides common, default 'root'."""
    instance = secrets['instances'][instance_name]
    return instance.get('ssh_user', secrets['common'].get('ssh_user', 'root'))

def get_target(secrets: dict, instance_name: str) -> tuple[str, int]:
    """Returns (user@domain, port) for an instance."""
    domain = secrets['instances'][instance_name]['domain']
    user = get_ssh_user(secrets, instance_name)
    port = get_ssh_port(secrets, instance_name)
    return f"{user}@{domain}", port

def ssh_opts(port: int) -> list[str]:
    """Build SSH options list."""
    return ['-e', f'ssh -p {port}']

def ssh_run(target: str, cmd: str, port: int = 22) -> None:
    result = subprocess.run(
        ['ssh', '-p', str(port), target, cmd],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"  SSH error: {result.stderr.strip()}", file=sys.stderr)


def ssh_read_file(target: str, path: str, port: int = 22) -> str:
    result = subprocess.run(
        ['ssh', '-p', str(port), target, f'cat {path} 2>/dev/null || true'],
        capture_output=True, text=True
    )
    return result.stdout


def rsync_file(local: Path, target: str, remote: str, port: int = 22) -> bool:
    """Returns True if file was changed."""
    result = subprocess.run(
        ['rsync', '-az', '--checksum', '--itemize-changes',
         '-e', f'ssh -p {port}',
         str(local), f'{target}:{remote}'],
        capture_output=True, text=True
    )
    return bool(result.stdout.strip())


def write_secret_remote(target: str, content: str, path: str, port: int = 22) -> None:
    subprocess.run(
        ['ssh', '-p', str(port), target, f'cat > {path} && chmod 600 {path}'],
        input=content, text=True, check=True
    )


# ── Template context ─────────────────────────────────

def build_context(secrets: dict, instance_name: str) -> dict:
    instance = secrets['instances'][instance_name]
    return {
        'common': secrets['common'],
        'instance': instance,
    }


# ── Commands ─────────────────────────────────────────

def cmd_list(secrets: dict) -> None:
    for name, data in secrets['instances'].items():
        print(f"  {name}\t{data['domain']}")


def cmd_render(secrets: dict, env: Environment, instance_name: str) -> None:
    if instance_name not in secrets['instances']:
        print(f"Instance '{instance_name}' not found", file=sys.stderr)
        sys.exit(1)

    ctx = build_context(secrets, instance_name)
    templates = ['traefik.yml.j2', 'dynamic1.yml.j2', 'traefik.container.j2']

    for tpl in templates:
        name = tpl.removesuffix('.j2')
        print(f"\033[1;33m═══ {name} ═══\033[0m")
        print(render_template(env, tpl, ctx))
        print()


def cmd_diff(secrets: dict, env: Environment, instance_name: str) -> None:
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
        rendered = render_template(env, tpl, ctx)
        remote_content = ssh_read_file(target, remote_path, port)

        if rendered == remote_content:
            print(f"\033[0;32m✓\033[0m {name} — no changes")
        else:
            print(f"\033[1;33m→\033[0m {name} — differs:")
            with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as local_f:
                local_f.write(rendered)
                local_f.flush()
                with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as remote_f:
                    remote_f.write(remote_content)
                    remote_f.flush()
                    subprocess.run(
                        ['diff', '--color', remote_f.name, local_f.name],
                    )
            print()


def cmd_deploy(
    secrets: dict,
    env: Environment,
    instance_name: str,
    restart: bool = True
) -> None:
    if instance_name not in secrets['instances']:
        print(f"Instance '{instance_name}' not found", file=sys.stderr)
        sys.exit(1)

    ctx = build_context(secrets, instance_name)
    target, port = get_target(secrets, instance_name)

    print(f"\033[1;33m→\033[0m deploying {instance_name} ({target}:{port})")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Render templates
        files = {
            'traefik.yml.j2': ('traefik.yml', f'{REMOTE_BASE}/settings/traefik.yml'),
            'dynamic1.yml.j2': ('dynamic1.yml', f'{REMOTE_BASE}/settings/dynamic/dynamic1.yml'),
            'traefik.container.j2': ('traefik.container', '/etc/containers/systemd/traefik.container'),
        }

        # Create remote directories
        ssh_run(target,
            f"mkdir -p {REMOTE_BASE}/settings/dynamic "
            f"{REMOTE_BASE}/google_acme {REMOTE_BASE}/logs",
            port
        )

        changed = False
        for tpl, (local_name, remote_path) in files.items():
            rendered = render_template(env, tpl, ctx)
            local_file = tmpdir / local_name
            local_file.write_text(rendered)

            if rsync_file(local_file, target, remote_path, port):
                print(f"  \033[1;33m→\033[0m {local_name} updated")
                changed = True
            else:
                print(f"  \033[0;32m✓\033[0m {local_name} unchanged")

        # Write secrets
        cf_email = secrets['common']['cf_email']
        cf_token = secrets['common']['cf_api_token']
        write_secret_remote(target, cf_email, f'{REMOTE_BASE}/cf_email', port)
        write_secret_remote(target, cf_token, f'{REMOTE_BASE}/cf_token', port)
        print(f"  \033[0;32m✓\033[0m secrets written")

        # Restart if needed
        if restart and changed:
            ssh_run(target, "systemctl daemon-reload && systemctl restart traefik", port)
            print(f"  \033[0;32m✓\033[0m traefik restarted")
        elif not changed:
            print(f"  \033[0;32m✓\033[0m no changes, skipping restart")

    print(f"\033[0;32m✓\033[0m {instance_name} done\n")


# ── Main ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Traefik config deployer',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python deploy.py list
  python deploy.py render instance1
  python deploy.py diff instance1
  python deploy.py deploy instance1
  python deploy.py deploy --all
  python deploy.py deploy --all --no-restart
        """
    )

    parser.add_argument(
        'command',
        choices=['list', 'render', 'diff', 'deploy'],
        help='Command to run'
    )
    parser.add_argument(
        'instance',
        nargs='?',
        help='Instance name'
    )
    parser.add_argument(
        '-s', '--secrets',
        default=str(SECRETS_FILE),
        help='Path to SOPS encrypted secrets'
    )
    parser.add_argument(
        '-t', '--templates',
        default=str(TEMPLATES_DIR),
        help='Templates directory'
    )
    parser.add_argument(
        '--all',
        action='store_true',
        help='Apply to all instances'
    )
    parser.add_argument(
        '--no-restart',
        action='store_true',
        help='Skip traefik restart after deploy'
    )

    args = parser.parse_args()

    secrets = decrypt_sops(Path(args.secrets))
    env = create_jinja_env(Path(args.templates))

    if args.command == 'list':
        cmd_list(secrets)
        return

    # Determine target instances
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
