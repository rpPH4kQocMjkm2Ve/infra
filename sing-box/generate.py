#!/usr/bin/env python3
"""Client/router config generator with Cloudflare Workers KV."""

import sys
import json
import secrets as secrets_module
import argparse
from pathlib import Path
from datetime import datetime

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib.sops import decrypt_sops
from lib.jinja import create_jinja_env

BASE = Path(__file__).parent
TEMPLATES_DIR = BASE / 'templates'
SECRETS_FILE = BASE / 'secrets' / 'secrets.enc.yaml'
OUTPUT_DIR = BASE / 'output'


def get_jinja_env():
    env = create_jinja_env(TEMPLATES_DIR)
    env.filters['to_json'] = lambda x: json.dumps(x, ensure_ascii=False)
    return env


def render_json(env, template_name, context):
    """Render template and validate JSON."""
    rendered = env.get_template(template_name).render(**context)
    try:
        parsed = json.loads(rendered)
        return json.dumps(parsed, indent=2, ensure_ascii=False)
    except json.JSONDecodeError as e:
        print(f"Invalid JSON in {template_name}: {e}", file=sys.stderr)
        print(f"Near: {rendered[max(0, e.pos - 50):e.pos + 50]}", file=sys.stderr)
        sys.exit(1)


def get_user_by_name(secrets, name):
    return next(
        (u for u in secrets.get('users', []) if u['name'] == name),
        None
    )


class CFKVUploader:
    def __init__(self, account_id, api_token, namespace_id, worker_domain):
        self.base_url = (
            f"https://api.cloudflare.com/client/v4/accounts"
            f"/{account_id}/storage/kv/namespaces/{namespace_id}"
        )
        self.headers = {"Authorization": f"Bearer {api_token}"}
        self.worker_domain = worker_domain.rstrip('/')

    def upload(self, key, content):
        response = requests.put(
            f"{self.base_url}/values/{key}",
            headers={**self.headers, "Content-Type": "text/plain"},
            data=content.encode('utf-8')
        )
        if not response.ok:
            print(f"KV upload error: {response.status_code} {response.text}",
                  file=sys.stderr)
            response.raise_for_status()
        return f"https://{self.worker_domain}/{key}"

    def delete(self, key):
        requests.delete(
            f"{self.base_url}/values/{key}", headers=self.headers
        ).raise_for_status()

    def list_keys(self, prefix='', cursor=None):
        params = {}
        if prefix:
            params['prefix'] = prefix
        if cursor:
            params['cursor'] = cursor
        response = requests.get(
            f"{self.base_url}/keys", headers=self.headers, params=params
        )
        response.raise_for_status()
        data = response.json()
        return data.get('result', []), data.get('result_info', {}).get('cursor', '')

    def list_all_keys(self, prefix=''):
        all_keys = []
        cursor = None
        while True:
            keys, cursor = self.list_keys(prefix=prefix, cursor=cursor)
            all_keys.extend(keys)
            if not cursor:
                break
        return all_keys

    def delete_by_prefix(self, prefix):
        keys = self.list_all_keys(prefix=prefix)
        deleted = []
        for key_info in keys:
            key_name = key_info['name']
            self.delete(key_name)
            deleted.append(key_name)
        return deleted


def create_uploader(secrets):
    cf = secrets.get('cloudflare', {})
    required = [cf.get('account_id'), cf.get('api_token'),
                cf.get('kv_namespace_id'), cf.get('worker_domain')]
    if not all(required):
        return None
    return CFKVUploader(
        cf['account_id'], cf['api_token'],
        cf['kv_namespace_id'], cf['worker_domain']
    )


def get_user_token(user):
    token = user.get('token')
    if not token:
        token = secrets_module.token_urlsafe(24)
        print(f"  ⚠ User '{user['name']}' has no token! "
              f"Add to secrets.yaml:", file=sys.stderr)
        print(f"    token: \"{token}\"", file=sys.stderr)
    return token


# --- Token generation ---

def cmd_gen_token(args):
    count = args.count or 1
    length = args.token_length

    if args.user:
        users = args.user if isinstance(args.user, list) else [args.user]
        print("# Add these to your secrets.enc.yaml under the user entry:\n")
        for user in users:
            token = secrets_module.token_urlsafe(length)
            print(f"  - name: {user}")
            print(f"    token: \"{token}\"")
            print()
    else:
        print(f"# {count} generated token(s) ({length} bytes → "
              f"{len(secrets_module.token_urlsafe(length))} chars):\n")
        for _ in range(count):
            print(f"  {secrets_module.token_urlsafe(length)}")


# --- KV management ---

def cmd_list_kv(secrets, args):
    uploader = create_uploader(secrets)
    if not uploader:
        print("Cloudflare not configured in secrets", file=sys.stderr)
        sys.exit(1)

    token_map = {}
    for user in secrets.get('users', []):
        token = user.get('token')
        if token:
            token_map[token] = user['name']

    keys = uploader.list_all_keys(prefix=args.prefix or '')
    if not keys:
        print("No keys found in KV")
        return

    print(f"Keys in KV ({len(keys)} total):\n")

    grouped = {}
    for key_info in keys:
        key_name = key_info['name']
        parts = key_name.split('/', 1)
        grouped.setdefault(parts[0], []).append(parts[1] if len(parts) > 1 else '')

    for token_prefix, files in grouped.items():
        username = token_map.get(token_prefix, '???')
        print(f"  [{username}] ({token_prefix[:12]}...)")
        for f in sorted(files):
            print(f"    └── {f}")
        print()


def cmd_revoke(secrets, args):
    uploader = create_uploader(secrets)
    if not uploader:
        print("Cloudflare not configured in secrets", file=sys.stderr)
        sys.exit(1)

    user = get_user_by_name(secrets, args.revoke)
    if not user:
        print(f"User '{args.revoke}' not found in secrets", file=sys.stderr)
        sys.exit(1)

    token = user.get('token')
    if not token:
        print(f"User '{args.revoke}' has no token", file=sys.stderr)
        sys.exit(1)

    if not args.yes:
        print(f"This will delete ALL configs for '{args.revoke}' from KV.")
        if input("Continue? [y/N] ").strip().lower() != 'y':
            print("Aborted")
            return

    deleted = uploader.delete_by_prefix(token)
    if deleted:
        for key in deleted:
            print(f"  ✗ Deleted: {key}")
        print(f"\n✓ Revoked {len(deleted)} config(s) for '{args.revoke}'")
    else:
        print(f"No configs found for '{args.revoke}'")


def cmd_purge_kv(secrets, args):
    uploader = create_uploader(secrets)
    if not uploader:
        print("Cloudflare not configured in secrets", file=sys.stderr)
        sys.exit(1)

    keys = uploader.list_all_keys()
    if not keys:
        print("KV is already empty")
        return

    if not args.yes:
        print(f"This will delete ALL {len(keys)} key(s) from KV.")
        if input("Type 'yes' to confirm: ").strip().lower() != 'yes':
            print("Aborted")
            return

    for key_info in keys:
        uploader.delete(key_info['name'])
        print(f"  ✗ Deleted: {key_info['name']}")
    print(f"\n✓ Purged {len(keys)} key(s) from KV")


# --- Config generation ---

def generate_client_configs(secrets, env, uploader=None):
    clients_dir = OUTPUT_DIR / 'clients'
    clients_dir.mkdir(parents=True, exist_ok=True)
    urls = {}

    for user in secrets.get('users', []):
        if user.get('type', 'client') != 'client':
            continue

        config = render_json(env, 'client.json.j2', {**secrets, 'current_user': user})

        output_file = clients_dir / f"client_{user['name']}.json"
        output_file.write_text(config)
        print(f"✓ Created: {output_file}")

        if uploader:
            token = get_user_token(user)
            url = uploader.upload(f"{token}/config.json", config)
            urls[user['name']] = url
            print(f"  ↳ URL: {url}")

    return urls


def generate_router_configs(secrets, env, uploader=None):
    router_users = [u for u in secrets.get('users', []) if u.get('type') == 'router']
    if not router_users:
        print("⚠ No router users found, skipping", file=sys.stderr)
        return {}

    vless_transports = [
        ('grpc', 'vless-grpc', 'sing-box_vless_grpc.json'),
        ('ws', 'vless-ws', 'sing-box_vless_ws.json'),
        ('http-upgrade', 'vless-http-upgrade', 'sing-box_vless_httpupgrade.json'),
    ]

    urls = {}
    for router_user in router_users:
        router_name = router_user['name']
        router_dir = OUTPUT_DIR / 'router' / router_name
        router_dir.mkdir(parents=True, exist_ok=True)

        context = {**secrets, 'current_user': router_user}
        router_urls = {}
        token = get_user_token(router_user) if uploader else None

        # Main config
        main_config = render_json(env, 'router_main.json.j2', context)
        (router_dir / 'sing-box.json').write_text(main_config)
        print(f"✓ Created: {router_dir / 'sing-box.json'}")

        if uploader and token:
            url = uploader.upload(f"{token}/main.json", main_config)
            router_urls['main'] = url
            print(f"  ↳ URL: {url}")

        # AnyTLS outbounds
        anytls_filename = 'sing-box_anytls.json'
        anytls_config = render_json(env, 'router_anytls.json.j2', context)
        (router_dir / anytls_filename).write_text(anytls_config)
        print(f"✓ Created: {router_dir / anytls_filename}")

        if uploader and token:
            url = uploader.upload(f"{token}/{anytls_filename}", anytls_config)
            router_urls['anytls'] = url
            print(f"  ↳ URL: {url}")

        # VLESS transports (grpc, ws, http-upgrade)
        for transport, tag_prefix, filename in vless_transports:
            config = render_json(env, 'router_vless.json.j2', {
                **context, 'transport': transport, 'tag_prefix': tag_prefix
            })
            (router_dir / filename).write_text(config)
            print(f"✓ Created: {router_dir / filename}")

            if uploader and token:
                url = uploader.upload(f"{token}/{filename}", config)
                router_urls[transport] = url
                print(f"  ↳ URL: {url}")

        if router_urls:
            urls[router_name] = router_urls

    return urls


def save_urls(urls):
    if not urls.get('clients') and not urls.get('routers'):
        return

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    urls_file = OUTPUT_DIR / 'urls.json'
    urls_file.write_text(json.dumps(urls, indent=2, ensure_ascii=False))
    print(f"\n📋 URLs saved to: {urls_file}")

    readme_file = OUTPUT_DIR / 'urls.md'
    with open(readme_file, 'w') as f:
        f.write("# Config URLs\n\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write("⚠️ **Keep these URLs private!**\n\n")
        if urls.get('clients'):
            f.write("## Clients\n\n")
            for name, url in urls['clients'].items():
                f.write(f"### {name}\n```\n{url}\n```\n\n")
        if urls.get('routers'):
            f.write("## Routers\n\n")
            for router_name, router_urls in urls['routers'].items():
                f.write(f"### {router_name}\n\n")
                for config_type, url in router_urls.items():
                    f.write(f"**{config_type}:**\n```\n{url}\n```\n\n")
    print(f"📋 URLs readme: {readme_file}")


def main():
    parser = argparse.ArgumentParser(
        description='sing-box client/router config generator',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python generate.py                          Generate locally
  python generate.py --upload                 Generate + upload to KV
  python generate.py --target clients         Only clients
  python generate.py --gen-token              Generate 1 token
  python generate.py --gen-token --user bob   Generate token for user 'bob'
  python generate.py --list-kv                List all KV keys
  python generate.py --revoke phone-m         Delete phone-m configs from KV
  python generate.py --purge-kv               Delete everything from KV
        """
    )

    parser.add_argument('--upload', action='store_true', help='Upload to Cloudflare Workers KV')
    parser.add_argument('--target', choices=['all', 'clients', 'router'],
                        nargs='+', default=['all'], help='What to generate')

    parser.add_argument('--gen-token', action='store_true', help='Generate secure token(s)')
    parser.add_argument('--user', nargs='*', help='User name(s)')
    parser.add_argument('-n', '--count', type=int, help='Number of tokens')
    parser.add_argument('--token-length', type=int, default=24)

    parser.add_argument('--list-kv', action='store_true', help='List all KV keys')
    parser.add_argument('--prefix', help='Filter KV keys by prefix')
    parser.add_argument('--revoke', metavar='USERNAME', help='Delete user configs from KV')
    parser.add_argument('--purge-kv', action='store_true', help='Delete ALL from KV')
    parser.add_argument('-y', '--yes', action='store_true', help='Skip confirmation')

    args = parser.parse_args()

    if args.gen_token:
        cmd_gen_token(args)
        return

    secrets = decrypt_sops(SECRETS_FILE)

    if args.list_kv:
        cmd_list_kv(secrets, args)
        return
    if args.revoke:
        cmd_revoke(secrets, args)
        return
    if args.purge_kv:
        cmd_purge_kv(secrets, args)
        return

    # Config generation
    env = get_jinja_env()
    uploader = None
    if args.upload:
        uploader = create_uploader(secrets)
        if not uploader:
            print("⚠ Cloudflare not configured. Continuing without upload...",
                  file=sys.stderr)

    all_urls = {'clients': {}, 'routers': {}}
    targets = args.target

    if 'all' in targets or 'clients' in targets:
        all_urls['clients'] = generate_client_configs(secrets, env, uploader)

    if 'all' in targets or 'router' in targets:
        all_urls['routers'] = generate_router_configs(secrets, env, uploader)

    if uploader:
        save_urls(all_urls)


if __name__ == '__main__':
    main()
