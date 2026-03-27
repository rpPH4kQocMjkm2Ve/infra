#!/usr/bin/env python3
"""Client/router config generator with Cloudflare Workers KV."""

import sys
import json
import secrets as secrets_module
import argparse
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib.sops import decrypt_sops
from lib.jinja import create_jinja_env
from lib.cloudflare import CFKVUploader, create_uploader

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


def get_user_token(user):
    token = user.get('token')
    if not token:
        token = secrets_module.token_urlsafe(24)
        print(f"  ⚠ User '{user['name']}' has no token! "
              f"Add to secrets.yaml:", file=sys.stderr)
        print(f"    token: \"{token}\"", file=sys.stderr)
    return token


def filter_users(secrets, user_names=None, user_type=None):
    """Return users filtered by names and/or type.

    Args:
        secrets: decrypted secrets dict
        user_names: list of usernames to include, or None for all
        user_type: 'client' or 'router', or None for any
    """
    users = secrets.get('users', [])
    if user_names:
        unknown = [n for n in user_names if not get_user_by_name(secrets, n)]
        if unknown:
            all_names = [u['name'] for u in users]
            print(f"Unknown user(s): {', '.join(unknown)}. "
                  f"Available: {', '.join(all_names)}", file=sys.stderr)
            sys.exit(1)
        users = [u for u in users if u['name'] in user_names]
    if user_type:
        users = [u for u in users if u.get('type', 'client') == user_type]
    return users


# --- URLs persistence with merge ---

def load_existing_urls():
    """Load previously saved urls.json, return empty structure if missing."""
    urls_file = OUTPUT_DIR / 'urls.json'
    if urls_file.exists():
        try:
            return json.loads(urls_file.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {'clients': {}, 'routers': {}}


def save_urls(urls):
    """Merge new URLs into existing urls.json and regenerate urls.md."""
    if not urls.get('clients') and not urls.get('routers'):
        return

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Merge with existing data so single-user uploads don't erase others
    existing = load_existing_urls()
    existing.setdefault('clients', {}).update(urls.get('clients', {}))
    existing.setdefault('routers', {}).update(urls.get('routers', {}))

    urls_file = OUTPUT_DIR / 'urls.json'
    urls_file.write_text(json.dumps(existing, indent=2, ensure_ascii=False))
    print(f"\n📋 URLs saved to: {urls_file}")

    # Regenerate full .md from merged data
    readme_file = OUTPUT_DIR / 'urls.md'
    with open(readme_file, 'w') as f:
        f.write("# Config URLs\n\n")
        f.write(f"Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write("⚠️ **Keep these URLs private!**\n\n")
        if existing.get('clients'):
            f.write("## Clients\n\n")
            for name in sorted(existing['clients']):
                url = existing['clients'][name]
                f.write(f"### {name}\n```\n{url}\n```\n\n")
        if existing.get('routers'):
            f.write("## Routers\n\n")
            for router_name in sorted(existing['routers']):
                router_urls = existing['routers'][router_name]
                f.write(f"### {router_name}\n\n")
                for config_type in sorted(router_urls):
                    url = router_urls[config_type]
                    f.write(f"**{config_type}:**\n```\n{url}\n```\n\n")
    print(f"📋 URLs readme: {readme_file}")


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

    user = get_user_by_name(secrets, args.username)
    if not user:
        print(f"User '{args.username}' not found in secrets", file=sys.stderr)
        sys.exit(1)

    token = user.get('token')
    if not token:
        print(f"User '{args.username}' has no token", file=sys.stderr)
        sys.exit(1)

    if not args.yes:
        print(f"This will delete ALL configs for '{args.username}' from KV.")
        if input("Continue? [y/N] ").strip().lower() != 'y':
            print("Aborted")
            return

    deleted = uploader.delete_by_prefix(token)
    if deleted:
        for key in deleted:
            print(f"  ✗ Deleted: {key}")
        print(f"\n✓ Revoked {len(deleted)} config(s) for '{args.username}'")
    else:
        print(f"No configs found for '{args.username}'")


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

def generate_client_configs(secrets, env, users, uploader=None):
    """Generate configs for client-type users.

    Args:
        users: pre-filtered list of client users
    """
    clients_dir = OUTPUT_DIR / 'clients'
    clients_dir.mkdir(parents=True, exist_ok=True)
    urls = {}

    for user in users:
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


def generate_router_configs(secrets, env, users, uploader=None):
    """Generate configs for router-type users.

    Args:
        users: pre-filtered list of router users
    """
    if not users:
        print("⚠ No router users to generate", file=sys.stderr)
        return {}

    vless_transports = [
        ('grpc', 'vless-grpc', 'sing-box_vless_grpc.json'),
        ('ws', 'vless-ws', 'sing-box_vless_ws.json'),
        ('http-upgrade', 'vless-http-upgrade', 'sing-box_vless_httpupgrade.json'),
    ]

    urls = {}
    for router_user in users:
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

        # VLESS transports
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


# --- Subcommand handlers ---

def cmd_generate(args):
    """Handle 'generate' subcommand."""
    secrets = decrypt_sops(SECRETS_FILE)
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
        client_users = filter_users(secrets, args.user, user_type='client')
        all_urls['clients'] = generate_client_configs(
            secrets, env, client_users, uploader)

    if 'all' in targets or 'router' in targets:
        router_users = filter_users(secrets, args.user, user_type='router')
        all_urls['routers'] = generate_router_configs(
            secrets, env, router_users, uploader)

    if uploader:
        save_urls(all_urls)


def cmd_kv_list(args):
    """Handle 'kv-list' subcommand."""
    secrets = decrypt_sops(SECRETS_FILE)
    cmd_list_kv(secrets, args)


def cmd_kv_revoke(args):
    """Handle 'kv-revoke' subcommand."""
    secrets = decrypt_sops(SECRETS_FILE)
    cmd_revoke(secrets, args)


def cmd_kv_purge(args):
    """Handle 'kv-purge' subcommand."""
    secrets = decrypt_sops(SECRETS_FILE)
    cmd_purge_kv(secrets, args)


def main():
    parser = argparse.ArgumentParser(
        description='sing-box client/router config generator',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest='command', required=True)

    # -- generate --
    p_gen = sub.add_parser('generate', help='Generate configs (local + optional upload)',
                           formatter_class=argparse.RawDescriptionHelpFormatter,
                           epilog="""examples:
  python generate.py generate                        Generate all locally
  python generate.py generate --upload               Generate + upload to KV
  python generate.py generate --user alice bob       Only these users
  python generate.py generate --target clients       Only client configs
  python generate.py generate --upload --user alice  Upload only alice""")
    p_gen.add_argument('--upload', action='store_true',
                       help='Upload configs to Cloudflare Workers KV')
    p_gen.add_argument('--target', choices=['all', 'clients', 'router'],
                       nargs='+', default=['all'],
                       help='What to generate (default: all)')
    p_gen.add_argument('--user', nargs='+', metavar='NAME',
                       help='Generate only for these user(s)')
    p_gen.set_defaults(func=cmd_generate)

    # -- gen-token --
    p_tok = sub.add_parser('gen-token', help='Generate secure token(s)',
                           formatter_class=argparse.RawDescriptionHelpFormatter,
                           epilog="""examples:
  python generate.py gen-token                   Generate 1 random token
  python generate.py gen-token --user bob alice  Tokens formatted for secrets.yaml
  python generate.py gen-token -n 5              Generate 5 tokens""")
    p_tok.add_argument('--user', nargs='+', metavar='NAME',
                       help='Format tokens as secrets.yaml entries for these users')
    p_tok.add_argument('-n', '--count', type=int,
                       help='Number of tokens to generate')
    p_tok.add_argument('--token-length', type=int, default=24,
                       help='Token byte length (default: 24)')
    p_tok.set_defaults(func=cmd_gen_token)

    # -- kv-list --
    p_kv_list = sub.add_parser('kv-list', help='List all keys in KV store')
    p_kv_list.add_argument('--prefix',
                           help='Filter keys by prefix')
    p_kv_list.set_defaults(func=cmd_kv_list)

    # -- kv-revoke --
    p_kv_rev = sub.add_parser('kv-revoke',
                              help='Delete all configs for a user from KV')
    p_kv_rev.add_argument('username', help='User whose configs to delete')
    p_kv_rev.add_argument('-y', '--yes', action='store_true',
                          help='Skip confirmation prompt')
    p_kv_rev.set_defaults(func=cmd_kv_revoke)

    # -- kv-purge --
    p_kv_purge = sub.add_parser('kv-purge',
                                help='Delete ALL keys from KV store')
    p_kv_purge.add_argument('-y', '--yes', action='store_true',
                            help='Skip confirmation prompt')
    p_kv_purge.set_defaults(func=cmd_kv_purge)

    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
