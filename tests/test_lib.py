"""Tests for lib/ — pure logic + mocked externals."""

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ═══════════════════════════════════════════════════
# lib/jinja.py
# ═══════════════════════════════════════════════════


class TestJinja:
    def test_renders_variables(self, tmp_path):
        (tmp_path / "t.j2").write_text("server={{ host }}:{{ port }}")
        from lib.jinja import create_jinja_env
        env = create_jinja_env(tmp_path)
        assert env.get_template("t.j2").render(host="1.2.3.4", port=8080) == "server=1.2.3.4:8080"

    def test_trim_blocks(self, tmp_path):
        (tmp_path / "t.j2").write_text("{% if true %}\nyes\n{% endif %}\n")
        from lib.jinja import create_jinja_env
        env = create_jinja_env(tmp_path)
        assert env.get_template("t.j2").render() == "yes\n"

    def test_lstrip_blocks(self, tmp_path):
        (tmp_path / "t.j2").write_text("  {% if true %}\nindented\n  {% endif %}\n")
        from lib.jinja import create_jinja_env
        env = create_jinja_env(tmp_path)
        assert env.get_template("t.j2").render() == "indented\n"

    def test_keep_trailing_newline(self, tmp_path):
        (tmp_path / "t.j2").write_text("content\n")
        from lib.jinja import create_jinja_env
        env = create_jinja_env(tmp_path)
        assert env.get_template("t.j2").render().endswith("\n")

    def test_missing_template_raises(self, tmp_path):
        from jinja2 import TemplateNotFound
        from lib.jinja import create_jinja_env
        env = create_jinja_env(tmp_path)
        with pytest.raises(TemplateNotFound):
            env.get_template("nonexistent.j2")

    def test_loop(self, tmp_path):
        (tmp_path / "t.j2").write_text("{% for p in ports %}{{ p }}\n{% endfor %}")
        from lib.jinja import create_jinja_env
        env = create_jinja_env(tmp_path)
        assert env.get_template("t.j2").render(ports=[80, 443]) == "80\n443\n"

    def test_nested_dict(self, tmp_path):
        (tmp_path / "t.j2").write_text("{{ db.host }}:{{ db.port }}")
        from lib.jinja import create_jinja_env
        env = create_jinja_env(tmp_path)
        result = env.get_template("t.j2").render(db={"host": "localhost", "port": 5432})
        assert result == "localhost:5432"


# ═══════════════════════════════════════════════════
# lib/sops.py
# ═══════════════════════════════════════════════════


class TestSops:
    @patch("subprocess.run")
    def test_decrypt_success(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout="key: value\nlist:\n  - a\n  - b\n", returncode=0
        )
        from lib.sops import decrypt_sops
        result = decrypt_sops(Path("/fake/secrets.enc.yaml"))
        assert result == {"key": "value", "list": ["a", "b"]}
        mock_run.assert_called_once_with(
            ["sops", "-d", "/fake/secrets.enc.yaml"],
            capture_output=True, text=True, check=True,
        )

    @patch("subprocess.run")
    def test_decrypt_nested_yaml(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout="db:\n  host: localhost\n  port: 5432\n", returncode=0
        )
        from lib.sops import decrypt_sops
        result = decrypt_sops(Path("/fake/s.yaml"))
        assert result["db"]["host"] == "localhost"
        assert result["db"]["port"] == 5432

    @patch(
        "subprocess.run",
        side_effect=subprocess.CalledProcessError(1, "sops", stderr="bad"),
    )
    def test_decrypt_failure_exits(self, mock_run):
        from lib.sops import decrypt_sops
        with pytest.raises(SystemExit):
            decrypt_sops(Path("/fake/secrets.enc.yaml"))

    @patch("subprocess.run", side_effect=FileNotFoundError)
    def test_sops_not_found_exits(self, mock_run):
        from lib.sops import decrypt_sops
        with pytest.raises(SystemExit):
            decrypt_sops(Path("/fake/secrets.enc.yaml"))


# ═══════════════════════════════════════════════════
# lib/remote.py
# ═══════════════════════════════════════════════════


class TestRemote:
    @patch("subprocess.run")
    def test_ssh_run_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        from lib.remote import ssh_run
        ssh_run("user@host", "echo hi", port=2222)
        mock_run.assert_called_once_with(
            ["ssh", "-p", "2222", "user@host", "echo hi"],
            capture_output=True, text=True,
        )

    @patch("subprocess.run")
    def test_ssh_run_default_port(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        from lib.remote import ssh_run
        ssh_run("user@host", "ls")
        args = mock_run.call_args[0][0]
        assert args[2] == "22"

    @patch("subprocess.run")
    def test_ssh_run_failure_exits(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stderr="refused")
        from lib.remote import ssh_run
        with pytest.raises(SystemExit):
            ssh_run("user@host", "fail")

    @patch("subprocess.run")
    def test_ssh_read_file(self, mock_run):
        mock_run.return_value = MagicMock(stdout="file content\n")
        from lib.remote import ssh_read_file
        assert ssh_read_file("user@host", "/etc/conf", port=22) == "file content\n"

    @patch("subprocess.run")
    def test_ssh_read_file_missing_returns_empty(self, mock_run):
        mock_run.return_value = MagicMock(stdout="")
        from lib.remote import ssh_read_file
        assert ssh_read_file("user@host", "/nonexistent") == ""

    @patch("subprocess.run")
    def test_rsync_checksum_changed(self, mock_run):
        mock_run.return_value = MagicMock(stdout="<fc.st...... file.conf\n", returncode=0)
        from lib.remote import rsync_file
        assert rsync_file(Path("/tmp/f"), "user@host", "/etc/f", 22) is True

    @patch("subprocess.run")
    def test_rsync_size_changed(self, mock_run):
        mock_run.return_value = MagicMock(stdout="<f..s....... file.conf\n", returncode=0)
        from lib.remote import rsync_file
        assert rsync_file(Path("/tmp/f"), "user@host", "/etc/f", 22) is True

    @patch("subprocess.run")
    def test_rsync_unchanged(self, mock_run):
        mock_run.return_value = MagicMock(stdout="", returncode=0)
        from lib.remote import rsync_file
        assert rsync_file(Path("/tmp/f"), "user@host", "/etc/f", 22) is False

    @patch("subprocess.run")
    def test_rsync_dots_only_unchanged(self, mock_run):
        # rsync emits dots-only flags for timestamp-only diffs — not a real change
        mock_run.return_value = MagicMock(stdout=".f..t...... file.conf\n", returncode=0)
        from lib.remote import rsync_file
        assert rsync_file(Path("/tmp/f"), "user@host", "/etc/f", 22) is False

    @patch("subprocess.run")
    def test_write_secret_remote(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        from lib.remote import write_secret_remote
        write_secret_remote("user@host", "secret_data", "/etc/key", 22)
        call_kw = mock_run.call_args
        assert call_kw.kwargs["input"] == "secret_data"
        assert call_kw.kwargs["check"] is True


# ═══════════════════════════════════════════════════
# lib/cloudflare.py
# ═══════════════════════════════════════════════════


class TestCloudflare:
    def test_create_uploader_valid(self):
        from lib.cloudflare import create_uploader
        secrets = {
            "cloudflare": {
                "account_id": "acc", "api_token": "tok",
                "kv_namespace_id": "ns", "worker_domain": "w.example.com",
            }
        }
        u = create_uploader(secrets)
        assert u is not None
        assert u.worker_domain == "w.example.com"

    def test_create_uploader_strips_trailing_slash(self):
        from lib.cloudflare import create_uploader
        secrets = {
            "cloudflare": {
                "account_id": "a", "api_token": "t",
                "kv_namespace_id": "n", "worker_domain": "w.example.com/",
            }
        }
        assert not create_uploader(secrets).worker_domain.endswith("/")

    @pytest.mark.parametrize("cf", [
        {"account_id": "acc"},
        {"account_id": "a", "api_token": "t"},
        {},
    ])
    def test_create_uploader_missing_fields(self, cf):
        from lib.cloudflare import create_uploader
        assert create_uploader({"cloudflare": cf}) is None

    def test_create_uploader_no_cloudflare_key(self):
        from lib.cloudflare import create_uploader
        assert create_uploader({}) is None

    @patch("requests.put")
    def test_upload_returns_url(self, mock_put):
        mock_put.return_value = MagicMock(ok=True)
        from lib.cloudflare import CFKVUploader
        kv = CFKVUploader("acc", "tok", "ns", "w.example.com")
        assert kv.upload("key1", "content") == "https://w.example.com/key1"

    @patch("requests.put")
    def test_upload_sends_utf8(self, mock_put):
        mock_put.return_value = MagicMock(ok=True)
        from lib.cloudflare import CFKVUploader
        kv = CFKVUploader("acc", "tok", "ns", "w.example.com")
        kv.upload("k", "данные")
        call_kw = mock_put.call_args
        assert call_kw.kwargs["data"] == "данные".encode("utf-8")

    @patch("requests.put")
    def test_upload_failure_raises(self, mock_put):
        resp = MagicMock(ok=False, status_code=403, text="forbidden")
        resp.raise_for_status.side_effect = Exception("403")
        mock_put.return_value = resp
        from lib.cloudflare import CFKVUploader
        kv = CFKVUploader("acc", "tok", "ns", "w.example.com")
        with pytest.raises(Exception):
            kv.upload("key1", "content")

    @patch("requests.delete")
    def test_delete(self, mock_del):
        mock_del.return_value = MagicMock()
        mock_del.return_value.raise_for_status = MagicMock()
        from lib.cloudflare import CFKVUploader
        kv = CFKVUploader("acc", "tok", "ns", "w.example.com")
        kv.delete("key1")
        assert "/values/key1" in mock_del.call_args[0][0]

    @patch("requests.get")
    def test_list_keys_single_page(self, mock_get):
        mock_get.return_value = MagicMock()
        mock_get.return_value.raise_for_status = MagicMock()
        mock_get.return_value.json.return_value = {
            "result": [{"name": "k1"}, {"name": "k2"}],
            "result_info": {"cursor": ""},
        }
        from lib.cloudflare import CFKVUploader
        kv = CFKVUploader("acc", "tok", "ns", "w.example.com")
        keys, cursor = kv.list_keys()
        assert len(keys) == 2
        assert cursor == ""

    @patch("requests.get")
    def test_list_keys_with_prefix(self, mock_get):
        mock_get.return_value = MagicMock()
        mock_get.return_value.raise_for_status = MagicMock()
        mock_get.return_value.json.return_value = {
            "result": [], "result_info": {"cursor": ""},
        }
        from lib.cloudflare import CFKVUploader
        kv = CFKVUploader("acc", "tok", "ns", "w.example.com")
        kv.list_keys(prefix="phone-")
        assert mock_get.call_args.kwargs["params"]["prefix"] == "phone-"

    @patch("requests.get")
    def test_list_all_keys_pagination(self, mock_get):
        page1 = MagicMock()
        page1.raise_for_status = MagicMock()
        page1.json.return_value = {
            "result": [{"name": "k1"}], "result_info": {"cursor": "cur1"},
        }
        page2 = MagicMock()
        page2.raise_for_status = MagicMock()
        page2.json.return_value = {
            "result": [{"name": "k2"}], "result_info": {"cursor": ""},
        }
        mock_get.side_effect = [page1, page2]
        from lib.cloudflare import CFKVUploader
        kv = CFKVUploader("acc", "tok", "ns", "w.example.com")
        assert len(kv.list_all_keys()) == 2
        assert mock_get.call_count == 2

    @patch("requests.delete")
    @patch("requests.get")
    def test_delete_by_prefix(self, mock_get, mock_del):
        mock_get.return_value = MagicMock()
        mock_get.return_value.raise_for_status = MagicMock()
        mock_get.return_value.json.return_value = {
            "result": [{"name": "pfx/a"}, {"name": "pfx/b"}],
            "result_info": {"cursor": ""},
        }
        mock_del.return_value = MagicMock()
        mock_del.return_value.raise_for_status = MagicMock()
        from lib.cloudflare import CFKVUploader
        kv = CFKVUploader("acc", "tok", "ns", "w.example.com")
        deleted = kv.delete_by_prefix("pfx/")
        assert deleted == ["pfx/a", "pfx/b"]
        assert mock_del.call_count == 2


# ═══════════════════════════════════════════════════
# lib/deploy.py
# ═══════════════════════════════════════════════════


class TestDeployHelpers:
    def test_resolve_target(self):
        from lib.deploy import resolve_target
        hosts = {
            "srv1": {"address": "s1.example.com", "ssh_port": 2222, "ssh_user": "admin"},
        }
        target, port = resolve_target(hosts, "srv1")
        assert target == "admin@s1.example.com"
        assert port == 2222

    def test_resolve_target_defaults(self):
        from lib.deploy import resolve_target
        target, port = resolve_target({"srv": {"address": "srv.example.com"}}, "srv")
        assert target == "root@srv.example.com"
        assert port == 22

    def test_resolve_target_missing_exits(self):
        from lib.deploy import resolve_target
        with pytest.raises(SystemExit):
            resolve_target({"srv": {}}, "nonexistent")

    @pytest.mark.parametrize("opts,expected", [
        ({"owner": "root:root", "mode": "600"}, " (root:root, 600)"),
        ({"owner": "33:33"}, " (33:33)"),
        ({"mode": "755"}, " (755)"),
        ({}, ""),
        (None, ""),
    ])
    def test_fmt_opts(self, opts, expected):
        from lib.deploy import _fmt_opts
        assert _fmt_opts(opts) == expected


class TestServiceDeployer:
    def _make_deployer(self, tmp_path, **overrides):
        from lib.deploy import ServiceDeployer
        config = {
            "templates_dir": tmp_path,
            "secrets_file": Path("/tmp/s"),
            "files": [],
            **overrides,
        }
        return ServiceDeployer(config)

    # ── _parse_file_entry ──

    def test_parse_two_element_entry(self, tmp_path):
        d = self._make_deployer(tmp_path)
        tpl, rp, opts = d._parse_file_entry(("c.yml.j2", "/opt/c.yml"), {})
        assert tpl == "c.yml.j2"
        assert rp == "/opt/c.yml"
        assert opts == {}

    def test_parse_three_element_entry(self, tmp_path):
        d = self._make_deployer(tmp_path)
        _, _, opts = d._parse_file_entry(
            ("wg.j2", "/etc/wg0.conf", {"owner": "root:root", "mode": "600"}), {}
        )
        assert opts == {"owner": "root:root", "mode": "600"}

    def test_parse_callable_path(self, tmp_path):
        d = self._make_deployer(tmp_path)
        _, rp, _ = d._parse_file_entry(
            ("t.j2", lambda s: f"/opt/{s['name']}/conf"), {"name": "myapp"}
        )
        assert rp == "/opt/myapp/conf"

    # ── _build_context ──

    def test_context_single_instance(self, tmp_path):
        d = self._make_deployer(tmp_path)
        secrets = {"host": "srv1", "db_pass": "x"}
        assert d._build_context(secrets) is secrets

    def test_context_multi_instance(self, tmp_path):
        d = self._make_deployer(tmp_path, multi_instance=True)
        secrets = {
            "common": {"cert": "example.com"},
            "instances": {"i1": {"host": "srv1", "domain": "d1.example.com"}},
        }
        ctx = d._build_context(secrets, "i1")
        assert ctx["common"]["cert"] == "example.com"
        assert ctx["instance"]["domain"] == "d1.example.com"
        assert ctx["instance_name"] == "i1"

    def test_context_multi_instance_missing_common(self, tmp_path):
        d = self._make_deployer(tmp_path, multi_instance=True)
        secrets = {"instances": {"i1": {"host": "srv1"}}}
        ctx = d._build_context(secrets, "i1")
        assert ctx["common"] == {}

    def test_context_custom_builder(self, tmp_path):
        d = self._make_deployer(
            tmp_path,
            context_builder=lambda s, i: {"custom": True, "inst": i},
        )
        assert d._build_context({}, "x") == {"custom": True, "inst": "x"}

    # ── _get_host_ref ──

    def test_host_ref_single(self, tmp_path):
        d = self._make_deployer(tmp_path)
        assert d._get_host_ref({"host": "srv1"}) == "srv1"

    def test_host_ref_multi(self, tmp_path):
        d = self._make_deployer(tmp_path, multi_instance=True)
        secrets = {"instances": {"i1": {"host": "srv2"}}}
        assert d._get_host_ref(secrets, "i1") == "srv2"

    # ── render ──

    def test_render_single(self, tmp_path, capsys):
        (tmp_path / "app.conf.j2").write_text("host={{ host }}\npass={{ db_pass }}\n")
        d = self._make_deployer(tmp_path, files=[("app.conf.j2", "/opt/app/conf")])
        from lib.jinja import create_jinja_env
        d.render({"host": "srv1", "db_pass": "p@ss"}, create_jinja_env(tmp_path))
        out = capsys.readouterr().out
        assert "host=srv1" in out
        assert "pass=p@ss" in out

    def test_render_multi(self, tmp_path, capsys):
        (tmp_path / "svc.j2").write_text("d={{ instance.domain }} c={{ common.cert }}\n")
        d = self._make_deployer(
            tmp_path,
            files=[("svc.j2", "/opt/svc/conf")],
            multi_instance=True,
        )
        from lib.jinja import create_jinja_env
        secrets = {
            "common": {"cert": "example.com"},
            "instances": {"i1": {"host": "srv1", "domain": "d1.example.com"}},
        }
        d.render(secrets, create_jinja_env(tmp_path), "i1")
        out = capsys.readouterr().out
        assert "d=d1.example.com" in out
        assert "c=example.com" in out

    def test_render_shows_opts(self, tmp_path, capsys):
        (tmp_path / "t.j2").write_text("x\n")
        d = self._make_deployer(
            tmp_path,
            files=[("t.j2", "/etc/conf", {"owner": "root:root", "mode": "600"})],
        )
        from lib.jinja import create_jinja_env
        d.render({"host": "srv1"}, create_jinja_env(tmp_path))
        out = capsys.readouterr().out
        assert "root:root" in out
        assert "600" in out

    # ── deploy ──

    @patch("lib.deploy.rsync_file", return_value=True)
    @patch("lib.deploy._apply_opts")
    @patch("lib.deploy.ssh_run")
    def test_deploy_restarts_on_change(self, mock_ssh, mock_opts, mock_rsync, tmp_path, capsys):
        (tmp_path / "t.j2").write_text("content\n")
        d = self._make_deployer(
            tmp_path,
            files=[("t.j2", "/opt/conf")],
            restart_cmd="systemctl restart svc",
        )
        from lib.jinja import create_jinja_env
        hosts = {"srv1": {"address": "s.example.com"}}
        secrets = {"host": "srv1"}
        d.deploy(hosts, secrets, create_jinja_env(tmp_path))
        # restart_cmd was executed
        restart_calls = [c for c in mock_ssh.call_args_list if "restart" in str(c)]
        assert len(restart_calls) == 1

    @patch("lib.deploy.rsync_file", return_value=False)
    @patch("lib.deploy._apply_opts")
    @patch("lib.deploy.ssh_run")
    def test_deploy_no_restart_when_unchanged(self, mock_ssh, mock_opts, mock_rsync, tmp_path, capsys):
        (tmp_path / "t.j2").write_text("content\n")
        d = self._make_deployer(
            tmp_path,
            files=[("t.j2", "/opt/conf")],
            restart_cmd="systemctl restart svc",
        )
        from lib.jinja import create_jinja_env
        hosts = {"srv1": {"address": "s.example.com"}}
        secrets = {"host": "srv1"}
        d.deploy(hosts, secrets, create_jinja_env(tmp_path))
        restart_calls = [c for c in mock_ssh.call_args_list if "restart" in str(c)]
        assert len(restart_calls) == 0
        assert "no changes" in capsys.readouterr().out

    @patch("lib.deploy.rsync_file", return_value=True)
    @patch("lib.deploy._apply_opts")
    @patch("lib.deploy.ssh_run")
    def test_deploy_no_restart_flag(self, mock_ssh, mock_opts, mock_rsync, tmp_path, capsys):
        (tmp_path / "t.j2").write_text("content\n")
        d = self._make_deployer(
            tmp_path,
            files=[("t.j2", "/opt/conf")],
            restart_cmd="systemctl restart svc",
        )
        from lib.jinja import create_jinja_env
        hosts = {"srv1": {"address": "s.example.com"}}
        secrets = {"host": "srv1"}
        d.deploy(hosts, secrets, create_jinja_env(tmp_path), no_restart=True)
        restart_calls = [c for c in mock_ssh.call_args_list if "restart" in str(c)]
        assert len(restart_calls) == 0

    @patch("lib.deploy.rsync_file", return_value=False)
    @patch("lib.deploy._apply_opts")
    @patch("lib.deploy.ssh_run")
    def test_deploy_creates_setup_dirs(self, mock_ssh, mock_opts, mock_rsync, tmp_path):
        (tmp_path / "t.j2").write_text("x\n")
        d = self._make_deployer(
            tmp_path,
            files=[("t.j2", "/opt/conf")],
            setup_dirs=["/opt/svc", "/opt/svc/data"],
        )
        from lib.jinja import create_jinja_env
        hosts = {"srv1": {"address": "s.example.com"}}
        secrets = {"host": "srv1"}
        d.deploy(hosts, secrets, create_jinja_env(tmp_path))
        mkdir_calls = [c for c in mock_ssh.call_args_list if "mkdir" in str(c)]
        assert len(mkdir_calls) == 1
        assert "/opt/svc" in str(mkdir_calls[0])

    @patch("lib.deploy.rsync_file", return_value=True)
    @patch("lib.deploy.ssh_run")
    def test_deploy_applies_opts(self, mock_ssh, mock_rsync, tmp_path):
        (tmp_path / "t.j2").write_text("x\n")
        d = self._make_deployer(
            tmp_path,
            files=[("t.j2", "/etc/wg0.conf", {"owner": "root:root", "mode": "600"})],
        )
        from lib.jinja import create_jinja_env
        hosts = {"srv1": {"address": "s.example.com"}}
        secrets = {"host": "srv1"}
        d.deploy(hosts, secrets, create_jinja_env(tmp_path))
        chown_chmod = [c for c in mock_ssh.call_args_list if "chown" in str(c) or "chmod" in str(c)]
        assert len(chown_chmod) >= 1

    @patch("lib.deploy.rsync_file", return_value=True)
    @patch("lib.deploy._apply_opts")
    @patch("lib.deploy.ssh_run")
    def test_deploy_calls_secrets_hooks(self, mock_ssh, mock_opts, mock_rsync, tmp_path):
        (tmp_path / "t.j2").write_text("x\n")
        hook = MagicMock()
        d = self._make_deployer(
            tmp_path,
            files=[("t.j2", "/opt/conf")],
            secrets_hooks=[hook],
        )
        from lib.jinja import create_jinja_env
        hosts = {"srv1": {"address": "s.example.com"}}
        secrets = {"host": "srv1"}
        d.deploy(hosts, secrets, create_jinja_env(tmp_path))
        hook.assert_called_once()
        # hook receives (secrets, target, port)
        assert hook.call_args[0][0] is secrets

    @patch("lib.deploy.rsync_file", return_value=True)
    @patch("lib.deploy._apply_opts")
    @patch("lib.deploy.ssh_run")
    def test_deploy_callable_restart_cmd(self, mock_ssh, mock_opts, mock_rsync, tmp_path, capsys):
        (tmp_path / "t.j2").write_text("content\n")
        d = self._make_deployer(
            tmp_path,
            files=[("t.j2", "/opt/conf")],
            multi_instance=True,
            restart_cmd=lambda secrets, instance_name: f"podman pull {secrets['instances'][instance_name]['image']} && systemctl restart svc",
        )
        from lib.jinja import create_jinja_env
        hosts = {"srv1": {"address": "s.example.com"}}
        secrets = {
            "instances": {"i1": {"host": "srv1", "image": "ghcr.io/app:latest"}},
        }
        d.deploy(hosts, secrets, create_jinja_env(tmp_path), instance_name="i1")
        restart_calls = [c for c in mock_ssh.call_args_list if "podman pull" in str(c)]
        assert len(restart_calls) == 1
        assert "ghcr.io/app:latest" in str(restart_calls[0])
