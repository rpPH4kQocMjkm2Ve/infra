import subprocess
import sys
import tempfile
import argparse
from pathlib import Path

from lib.sops import decrypt_sops
from lib.remote import ssh_run, ssh_read_file, rsync_file
from lib.jinja import create_jinja_env

HOSTS_FILE = Path(__file__).resolve().parent.parent / 'secrets' / 'hosts.enc.yaml'


def load_hosts() -> dict:
    return decrypt_sops(HOSTS_FILE)


def resolve_target(hosts: dict, host_ref: str) -> tuple[str, int]:
    if host_ref not in hosts:
        print(f"Host '{host_ref}' not found in hosts.enc.yaml", file=sys.stderr)
        print(f"Available: {', '.join(hosts.keys())}", file=sys.stderr)
        sys.exit(1)
    h = hosts[host_ref]
    user = h.get('ssh_user', 'root')
    port = h.get('ssh_port', 22)
    return f"{user}@{h['address']}", port


def _fmt_opts(opts: dict) -> str:
    if not opts:
        return ''
    parts = []
    if 'owner' in opts:
        parts.append(opts['owner'])
    if 'mode' in opts:
        parts.append(opts['mode'])
    return f' ({", ".join(parts)})' if parts else ''


def _apply_opts(opts: dict, rp: str, target: str, port: int):
    if not opts:
        return
    cmds = []
    if 'owner' in opts:
        cmds.append(f'chown {opts["owner"]} {rp}')
    if 'mode' in opts:
        cmds.append(f'chmod {opts["mode"]} {rp}')
    if cmds:
        ssh_run(target, ' && '.join(cmds), port)


class ServiceDeployer:
    def __init__(self, config: dict):
        self.files = config['files']
        self.setup_dirs = config.get('setup_dirs', [])
        self.restart_cmd = config.get('restart_cmd')
        self.secrets_hooks = config.get('secrets_hooks', [])
        self.context_builder = config.get('context_builder')
        self.templates_dir = config['templates_dir']
        self.secrets_file = config['secrets_file']
        self.multi_instance = config.get('multi_instance', False)
        self.instances_key = config.get('instances_key', 'instances')

    def _get_env(self):
        return create_jinja_env(self.templates_dir)

    def _get_host_ref(self, secrets, instance_name=None):
        if self.multi_instance:
            return secrets[self.instances_key][instance_name]['host']
        return secrets['host']

    def _get_target(self, hosts, secrets, instance_name=None):
        host_ref = self._get_host_ref(secrets, instance_name)
        return resolve_target(hosts, host_ref)

    def _build_context(self, secrets, instance_name=None):
        if self.context_builder:
            return self.context_builder(secrets, instance_name)
        if self.multi_instance:
            return {
                'common': secrets.get('common', {}),
                'instance': secrets[self.instances_key][instance_name],
                'instance_name': instance_name,
            }
        return secrets

    def _parse_file_entry(self, entry, secrets):
        tpl = entry[0]
        remote_path = entry[1]
        opts = entry[2] if len(entry) == 3 else {}
        if callable(remote_path):
            remote_path = remote_path(secrets)
        return tpl, remote_path, opts

    def render(self, secrets, env, instance_name=None):
        ctx = self._build_context(secrets, instance_name)
        label = instance_name or self._get_host_ref(secrets)
        print(f"\033[1;36m── {label} ──\033[0m")
        files = self.files(secrets, instance_name) if callable(self.files) else self.files
        for entry in files:
            tpl, rp, opts = self._parse_file_entry(entry, secrets)
            name = tpl.removesuffix('.j2')
            print(f"\033[1;33m═══ {name} → {rp}{_fmt_opts(opts)} ═══\033[0m")
            print(env.get_template(tpl).render(**ctx))
            print()

    def diff(self, hosts, secrets, env, instance_name=None):
        ctx = self._build_context(secrets, instance_name)
        target, port = self._get_target(hosts, secrets, instance_name)
        label = instance_name or self._get_host_ref(secrets)
        print(f"\033[1;36m── {label} ({target}) ──\033[0m")
        files = self.files(secrets, instance_name) if callable(self.files) else self.files
        for entry in files:
            tpl, rp, opts = self._parse_file_entry(entry, secrets)
            name = tpl.removesuffix('.j2')
            rendered = env.get_template(tpl).render(**ctx)
            remote_content = ssh_read_file(target, rp, port)
            if rendered == remote_content:
                print(f"  \033[0;32m✓\033[0m {name}{_fmt_opts(opts)}")
            else:
                print(f"  \033[1;33m→\033[0m {name} differs{_fmt_opts(opts)}")
                with tempfile.NamedTemporaryFile(mode='w', suffix='.txt') as lf, \
                     tempfile.NamedTemporaryFile(mode='w', suffix='.txt') as rf:
                    lf.write(rendered); lf.flush()
                    rf.write(remote_content); rf.flush()
                    subprocess.run(['diff', '--color', '-u', rf.name, lf.name])
                print()

    def deploy(self, hosts, secrets, env, instance_name=None, no_restart=False):
        ctx = self._build_context(secrets, instance_name)
        target, port = self._get_target(hosts, secrets, instance_name)
        label = instance_name or self._get_host_ref(secrets)
        print(f"\033[1;33m→\033[0m deploying {label} to {target}")

        files = self.files(secrets, instance_name) if callable(self.files) else self.files
        setup_dirs = self.setup_dirs(secrets, instance_name) if callable(self.setup_dirs) else self.setup_dirs

        if setup_dirs:
            ssh_run(target, f"mkdir -p {' '.join(setup_dirs)}", port)

        changed = False
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            for entry in files:
                tpl, rp, opts = self._parse_file_entry(entry, secrets)
                rendered = env.get_template(tpl).render(**ctx)
                local_file = tmpdir / tpl.removesuffix('.j2')
                local_file.write_text(rendered)
                if rsync_file(local_file, target, rp, port):
                    print(f"  \033[1;33m→\033[0m {tpl.removesuffix('.j2')} updated")
                    changed = True
                else:
                    print(f"  \033[0;32m✓\033[0m {tpl.removesuffix('.j2')} unchanged")
                _apply_opts(opts, rp, target, port)

        for hook in self.secrets_hooks:
            hook(secrets, target, port)

        if not no_restart and changed and self.restart_cmd:
            if callable(self.restart_cmd):
                cmd = self.restart_cmd(secrets, instance_name)
            else:
                cmd = self.restart_cmd
            ssh_run(target, cmd, port)
            print(f"  \033[0;32m✓\033[0m restarted")
        elif not changed:
            print(f"  \033[0;32m✓\033[0m no changes")

        print(f"\033[0;32m✓\033[0m {label} done\n")

    def run_cli(self):
        parser = argparse.ArgumentParser()
        parser.add_argument('command', choices=['list', 'render', 'diff', 'deploy'])
        parser.add_argument('instance', nargs='*')
        parser.add_argument('-s', '--secrets', default=str(self.secrets_file))
        parser.add_argument('--all', action='store_true')
        parser.add_argument('--no-restart', action='store_true')
        args = parser.parse_args()

        secrets = decrypt_sops(Path(args.secrets))
        env = self._get_env()
        hosts = load_hosts()

        if self.multi_instance:
            if args.command == 'list':
                for name, data in secrets[self.instances_key].items():
                    host_ref = data['host']
                    addr = hosts.get(host_ref, {}).get('address', '?')
                    print(f"  {name}\t{addr}")
                return

            if args.all:
                instances = list(secrets[self.instances_key].keys())
            elif args.instance:
                unknown = [i for i in args.instance if i not in secrets[self.instances_key]]
                if unknown:
                    print(f"Unknown: {', '.join(unknown)}. "
                          f"Available: {', '.join(secrets[self.instances_key].keys())}",
                          file=sys.stderr)
                    sys.exit(1)
                instances = args.instance
            else:
                parser.error(f"'{args.command}' requires instance name(s) or --all")

            for inst in instances:
                if args.command == 'render':
                    self.render(secrets, env, inst)
                elif args.command == 'diff':
                    self.diff(hosts, secrets, env, inst)
                elif args.command == 'deploy':
                    self.deploy(hosts, secrets, env, inst, no_restart=args.no_restart)
        else:
            if args.command == 'list':
                host_ref = secrets['host']
                addr = hosts.get(host_ref, {}).get('address', '?')
                print(f"  {host_ref}\t{addr}")
                return
            if args.command == 'render':
                self.render(secrets, env)
            elif args.command == 'diff':
                self.diff(hosts, secrets, env)
            elif args.command == 'deploy':
                self.deploy(hosts, secrets, env, no_restart=args.no_restart)
