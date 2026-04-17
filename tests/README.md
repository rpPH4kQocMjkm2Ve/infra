# Tests

## Overview

| File | Framework | What it tests |
|------|-----------|---------------|
| `test_lib.py` | pytest | `lib/` — Jinja2 environment setup, SOPS decryption, SSH/rsync remote operations, Cloudflare KV client, `ServiceDeployer` config rendering/diffing/deployment logic |

## Running

```bash
# All tests
pip install jinja2 pyyaml requests pytest
pytest tests/ -v
```

## How they work

### `test_lib.py`

Standard pytest suite. No network access, no SSH, no real secrets — all subprocess calls and HTTP requests are mocked via `unittest.mock.patch`.

**`TestJinja`** — tests `create_jinja_env()` output: variable interpolation, `trim_blocks`/`lstrip_blocks` whitespace control, trailing newline preservation, missing template error, loops, nested dict access.

**`TestSops`** — tests `decrypt_sops()`: successful YAML parsing from mocked `sops -d` stdout, nested structure handling, `SystemExit` on decryption failure (`CalledProcessError`), `SystemExit` when `sops` binary is missing (`FileNotFoundError`).

**`TestRemote`** — tests SSH and rsync wrappers with mocked `subprocess.run`:
- `ssh_run`: correct command construction, default port (22), `SystemExit` on non-zero return code
- `ssh_read_file`: returns stdout content, empty string for missing files
- `rsync_file`: detects changes via itemize flags (`c`=checksum, `s`=size, `+`=new file), returns `False` for unchanged files and timestamp-only diffs (dots-only flags)
- `write_secret_remote`: passes content via stdin, sets `check=True`

**`TestCloudflare`** — tests `create_uploader()` factory and `CFKVUploader` methods:
- Factory: returns uploader when all fields present, strips trailing slash from worker domain, returns `None` when fields are missing or `cloudflare` key absent
- `upload`: returns correct URL, sends UTF-8 encoded data, raises on HTTP error
- `delete`: hits correct KV endpoint
- `list_keys`: single-page result, prefix parameter forwarding
- `list_all_keys`: cursor-based pagination across multiple pages
- `delete_by_prefix`: lists then deletes each key, returns deleted key names

**`TestDeployHelpers`** — tests standalone functions:
- `resolve_target`: builds `user@address` string with custom/default user and port, `SystemExit` for unknown host
- `_fmt_opts`: formats owner/mode combinations, handles empty/`None` input

**`TestServiceDeployer`** — tests the deployer class with mocked `ssh_run`, `rsync_file`, `_apply_opts`:
- `_parse_file_entry`: two-element and three-element tuples, callable remote path resolution
- `_build_context`: passthrough for single-instance, structured context for multi-instance (common/instance/instance_name), custom builder override, missing `common` key fallback, custom `instances_key` for non-standard instance groups (e.g., `relay_instances`)
- `_get_host_ref`: single vs multi-instance host resolution
- `render`: outputs rendered template content with variables and file options for both single and multi-instance modes, supports callable `files`
- `deploy`: triggers restart command on file change, skips restart when unchanged, respects `--no-restart` flag, creates setup directories via `mkdir -p`, applies owner/mode options, calls secrets hooks with correct arguments, supports callable `restart_cmd` with instance-specific parameters, supports callable `files` and `setup_dirs` with static fallback

## Test environment

- No root privileges required
- No real servers, SSH connections, or Cloudflare API calls
- All filesystem operations use pytest's `tmp_path` fixture
- CI runs on push/PR when `lib/`, `tests/test_lib.py`, or `.github/workflows/ci.yml` change (see `.github/workflows/ci.yml`)
