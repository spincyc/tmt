"""Claude Code SessionStart integration lifecycle against a temp HOME.

Never touches real user state: the managed settings path comes from
$TMT_CLAUDE_SETTINGS, the manifest from $XDG_STATE_HOME, and $HOME
points at a temp directory throughout.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any

from _support import SRC_DIR, TmtTestCase, run_tmt, write_executable

FOREIGN_SETTINGS: dict[str, Any] = {
    "model": "opus",
    "hooks": {
        "UserPromptSubmit": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": "/usr/bin/python3 -I -m aiq capture",
                        "timeout": 10,
                    }
                ]
            }
        ]
    },
    "theme": "dark",
}


FOREIGN_GROUP: dict[str, Any] = {
    "matcher": "startup",
    "hooks": [{"type": "command", "command": "/usr/bin/true", "timeout": 5}],
}

IS_ROOT = os.geteuid() == 0

OWNED_MATCHER = "startup|resume|clear"

UNPARSEABLE = "{ not json\n"


def matcher_group(*commands: Any, timeout: int = 10) -> dict[str, Any]:
    """A SessionStart group wearing tmt's matcher over foreign commands."""
    return {
        "matcher": OWNED_MATCHER,
        "hooks": [
            {"type": "command", "command": command, "timeout": timeout}
            for command in commands
        ],
    }


def console_script(directory: Path) -> Path:
    """An executable named ``tmt`` that runs this checkout.

    The same shape pip installs for ``tmt = tmt.cli:main``, so that
    argv[0] reaches the console-script branch of ``tmt_command()``.
    """
    script = directory / "tmt"
    write_executable(
        script,
        f"#!{sys.executable}\n"
        "import sys\n"
        "from tmt.cli import main\n"
        "sys.exit(main())\n",
    )
    return script


def script_entry(script: Path) -> dict[str, Any]:
    """The owned group as an installed console script writes it."""
    return {
        "matcher": OWNED_MATCHER,
        "hooks": [
            {
                "type": "command",
                "command": f"{shlex.quote(os.fspath(script))} context",
                "timeout": 10,
            }
        ],
    }


def run_console(
    script: Path, cwd: Path, *arguments: str, env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    """Run tmt through ``script`` rather than ``python -m tmt``."""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.fspath(SRC_DIR)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment.update(env)
    return subprocess.run(
        [os.fspath(script), *arguments],
        cwd=os.fspath(cwd),
        env=environment,
        text=True,
        input="",
        capture_output=True,
    )


def expected_entry() -> dict[str, Any]:
    return {
        "matcher": "startup|resume|clear",
        "hooks": [
            {
                "type": "command",
                "command": f"{shlex.quote(sys.executable)} -m tmt context",
                "timeout": 10,
            }
        ],
    }


def stale_entry() -> dict[str, Any]:
    """The owned group as an older tmt installation would have written it."""
    return {
        "matcher": "startup|resume|clear",
        "hooks": [
            {
                "type": "command",
                "command": "/old/bin/tmt context",
                "timeout": 10,
            }
        ],
    }


class IntegrationTestCase(TmtTestCase):
    def setUp(self) -> None:
        self.home = self.make_dir()
        self.settings = self.home / "claude" / "settings.json"
        self.state = self.home / "state"
        self.manifest = (
            self.state / "tmt" / "integration" / "claude-user.json"
        )
        self.env = {
            "HOME": os.fspath(self.home),
            "TMT_CLAUDE_SETTINGS": os.fspath(self.settings),
            "XDG_STATE_HOME": os.fspath(self.state),
        }
        self.cwd = self.make_dir()

    def run_integration(
        self, *arguments: str, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        return run_tmt(
            self.cwd, "integration", *arguments, env=env or self.env
        )

    def relocated_env(self) -> dict[str, str]:
        """The same state directory with the managed settings path moved."""
        return {
            **self.env,
            "TMT_CLAUDE_SETTINGS": os.fspath(
                self.home / "elsewhere" / "settings.json"
            ),
        }

    def write_settings(self, document: dict[str, Any]) -> None:
        self.settings.parent.mkdir(parents=True, exist_ok=True)
        self.settings.write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def read_settings(self) -> dict[str, Any]:
        return json.loads(self.settings.read_text(encoding="utf-8"))

    def read_manifest(self) -> dict[str, Any]:
        return json.loads(self.manifest.read_text(encoding="utf-8"))

    def write_manifest(self, manifest: dict[str, Any]) -> None:
        self.manifest.parent.mkdir(parents=True, exist_ok=True)
        self.manifest.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )

    def write_owned_groups(self, groups: list[Any]) -> None:
        document = self.read_settings()
        document["hooks"]["SessionStart"] = groups
        self.write_settings(document)

    def tamper_owned_entry(self) -> None:
        document = self.read_settings()
        document["hooks"]["SessionStart"][0]["hooks"][0]["timeout"] = 99
        self.write_settings(document)


class PrintHookTest(IntegrationTestCase):
    def test_json_fragment_shape(self) -> None:
        payload = self.assert_json_success(
            self.run_integration("print", "hook", "claude", "--json")
        )

        self.assertEqual(
            payload["fragment"],
            {"hooks": {"SessionStart": [expected_entry()]}},
        )

    def test_human_output_is_the_fragment_json(self) -> None:
        result = self.run_integration("print", "hook", "claude")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout),
            {"hooks": {"SessionStart": [expected_entry()]}},
        )

    def test_print_hook_without_integration_is_a_usage_error(self) -> None:
        result = self.run_integration("print", "hook", "--json")

        self.assert_json_error(result, "usage", 2)


class PrintGenericHookTest(IntegrationTestCase):
    """The host-neutral snippet: any session-start hook can run it."""

    def test_json_carries_the_command_and_the_snippet(self) -> None:
        payload = self.assert_json_success(
            self.run_integration("print", "hook", "generic", "--json")
        )

        self.assertEqual(payload["command"], "tmt context")
        self.assertIn("tmt context", payload["fragment"])
        self.assertTrue(payload["fragment"].endswith("tmt context\n"))

    def test_human_output_is_a_runnable_shell_snippet(self) -> None:
        result = self.run_integration("print", "hook", "generic")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        lines = result.stdout.splitlines()
        self.assertEqual(lines[-1], "tmt context")
        for line in lines[:-1]:
            self.assertTrue(line.startswith("#"), line)

    def test_generic_cannot_be_installed(self) -> None:
        # Only a manifest-owned integration has a lifecycle; the snippet
        # is documentation the user pastes wherever their host wants it.
        result = self.run_integration("install", "generic", "--json")

        self.assert_json_error(result, "usage", 2)

    def test_an_unknown_integration_is_still_a_usage_error(self) -> None:
        result = self.run_integration("print", "hook", "emacs", "--json")

        payload = self.assert_json_error(result, "usage", 2)
        self.assertIn("generic", payload["error"])


class PlanTest(IntegrationTestCase):
    def test_plan_previews_install_without_writing(self) -> None:
        payload = self.assert_json_success(
            self.run_integration("plan", "claude", "--user", "--json")
        )

        self.assertEqual(payload["status"], "install")
        self.assertEqual(payload["changed"], True)
        self.assertEqual(payload["entry"], expected_entry())
        self.assertEqual(payload["settings"], os.fspath(self.settings))
        self.assertFalse(self.settings.exists())
        self.assertFalse(self.manifest.exists())

    def test_plan_reports_ok_after_install(self) -> None:
        self.run_integration("install", "claude")

        payload = self.assert_json_success(
            self.run_integration("plan", "claude", "--json")
        )

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["changed"], False)

    def test_plan_reports_drift_after_tampering(self) -> None:
        self.run_integration("install", "claude")
        self.tamper_owned_entry()

        payload = self.assert_json_success(
            self.run_integration("plan", "claude", "--json")
        )

        self.assertEqual(payload["status"], "drift")
        self.assertEqual(payload["changed"], False)


class InstallTest(IntegrationTestCase):
    def test_round_trip_preserves_foreign_settings_byte_equivalently(
        self,
    ) -> None:
        self.write_settings(FOREIGN_SETTINGS)
        original = self.settings.read_bytes()

        payload = self.assert_json_success(
            self.run_integration("install", "claude", "--user", "--json")
        )
        self.assertEqual(payload["changed"], True)
        self.assertEqual(payload["status"], "installed")

        document = self.read_settings()
        self.assertEqual(document["model"], "opus")
        self.assertEqual(document["theme"], "dark")
        self.assertEqual(
            document["hooks"]["UserPromptSubmit"],
            FOREIGN_SETTINGS["hooks"]["UserPromptSubmit"],
        )
        self.assertEqual(
            document["hooks"]["SessionStart"], [expected_entry()]
        )
        manifest = self.read_manifest()
        self.assertEqual(manifest["v"], 1)
        self.assertEqual(manifest["integration"], "claude")
        self.assertEqual(manifest["scope"], "user")
        self.assertEqual(manifest["entry"], expected_entry())
        self.assertEqual(manifest["settings"], os.fspath(self.settings))
        self.assertEqual(manifest["created_file"], False)

        uninstall = self.assert_json_success(
            self.run_integration("uninstall", "claude", "--json")
        )
        self.assertEqual(uninstall["changed"], True)
        self.assertEqual(uninstall["removed"], True)
        self.assertEqual(self.settings.read_bytes(), original)
        self.assertFalse(self.manifest.exists())

    def test_install_is_idempotent(self) -> None:
        self.write_settings(FOREIGN_SETTINGS)
        self.run_integration("install", "claude")
        after_first = self.settings.read_bytes()

        payload = self.assert_json_success(
            self.run_integration("install", "claude", "--json")
        )

        self.assertEqual(payload["changed"], False)
        self.assertEqual(payload["status"], "installed")
        self.assertEqual(self.settings.read_bytes(), after_first)

    def test_install_creates_missing_file_and_containers(self) -> None:
        payload = self.assert_json_success(
            self.run_integration("install", "claude", "--json")
        )

        self.assertEqual(payload["changed"], True)
        self.assertEqual(
            self.read_settings(),
            {"hooks": {"SessionStart": [expected_entry()]}},
        )
        manifest = self.read_manifest()
        self.assertEqual(manifest["created_file"], True)
        self.assertEqual(
            manifest["created_containers"],
            ["hooks", "hooks.SessionStart"],
        )

    def test_install_refuses_a_tampered_owned_entry(self) -> None:
        self.run_integration("install", "claude")
        self.tamper_owned_entry()
        before = self.settings.read_bytes()

        result = self.run_integration("install", "claude", "--json")

        self.assert_json_error(result, "drift", 3)
        self.assertEqual(self.settings.read_bytes(), before)
        self.assertTrue(self.manifest.exists())


class CheckTest(IntegrationTestCase):
    def test_absent_before_install(self) -> None:
        result = self.run_integration("check", "claude", "--json")

        self.assertEqual(result.returncode, 1, result.stderr)
        payload = self.parse_single_json(result.stdout)
        self.assertEqual(payload["status"], "absent")

    def test_ok_after_install(self) -> None:
        self.run_integration("install", "claude")

        result = self.run_integration("check", "claude", "--user", "--json")

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = self.parse_single_json(result.stdout)
        self.assertEqual(payload["status"], "ok")

    def test_drifted_after_tampering(self) -> None:
        self.run_integration("install", "claude")
        self.tamper_owned_entry()

        result = self.run_integration("check", "claude", "--json")

        self.assertEqual(result.returncode, 1, result.stderr)
        payload = self.parse_single_json(result.stdout)
        self.assertEqual(payload["status"], "drifted")

    def test_human_output_is_the_status_word(self) -> None:
        result = self.run_integration("check", "claude")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "absent\n")


class UninstallTest(IntegrationTestCase):
    def test_uninstall_removes_created_file_and_containers(self) -> None:
        self.run_integration("install", "claude")

        payload = self.assert_json_success(
            self.run_integration("uninstall", "claude", "--user", "--json")
        )

        self.assertEqual(payload["changed"], True)
        self.assertEqual(payload["removed"], True)
        self.assertFalse(self.settings.exists())
        self.assertFalse(self.manifest.exists())

    def test_uninstall_keeps_pre_existing_containers(self) -> None:
        self.write_settings({"hooks": {}})
        original = self.settings.read_bytes()
        self.run_integration("install", "claude")

        self.assert_json_success(
            self.run_integration("uninstall", "claude", "--json")
        )

        self.assertEqual(self.settings.read_bytes(), original)

    def test_uninstall_refuses_a_tampered_owned_entry(self) -> None:
        self.run_integration("install", "claude")
        self.tamper_owned_entry()
        before = self.settings.read_bytes()

        result = self.run_integration("uninstall", "claude", "--json")

        self.assert_json_error(result, "drift", 3)
        self.assertEqual(self.settings.read_bytes(), before)
        self.assertTrue(self.manifest.exists())

    def test_uninstall_without_install_is_a_no_op(self) -> None:
        payload = self.assert_json_success(
            self.run_integration("uninstall", "claude", "--json")
        )

        self.assertEqual(payload["changed"], False)
        self.assertEqual(payload["removed"], False)

    def test_uninstall_after_external_removal_deletes_the_manifest(
        self,
    ) -> None:
        self.write_settings(FOREIGN_SETTINGS)
        self.run_integration("install", "claude")
        document = self.read_settings()
        del document["hooks"]["SessionStart"]
        self.write_settings(document)

        payload = self.assert_json_success(
            self.run_integration("uninstall", "claude", "--json")
        )

        self.assertEqual(payload["removed"], False)
        self.assertFalse(self.manifest.exists())


class SettingsFileTest(IntegrationTestCase):
    @unittest.skipIf(IS_ROOT, "file modes are unenforced for root")
    def test_install_preserves_a_restrictive_settings_mode(self) -> None:
        self.write_settings({"env": {"MY_API_KEY": "s3cret"}})
        self.settings.chmod(0o600)

        self.assert_json_success(
            self.run_integration("install", "claude", "--user", "--json")
        )

        self.assertEqual(self.settings.stat().st_mode & 0o777, 0o600)
        document = self.read_settings()
        self.assertEqual(document["env"], {"MY_API_KEY": "s3cret"})
        self.assertEqual(
            document["hooks"]["SessionStart"], [expected_entry()]
        )

    @unittest.skipIf(IS_ROOT, "file modes are unenforced for root")
    def test_install_creates_private_settings_and_manifest(self) -> None:
        self.assert_json_success(
            self.run_integration("install", "claude", "--json")
        )

        self.assertEqual(self.settings.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.manifest.stat().st_mode & 0o777, 0o600)

    @unittest.skipIf(IS_ROOT, "file modes are unenforced for root")
    def test_install_leaves_a_permissive_mode_alone(self) -> None:
        self.write_settings(FOREIGN_SETTINGS)
        self.settings.chmod(0o644)

        self.run_integration("install", "claude")

        self.assertEqual(self.settings.stat().st_mode & 0o777, 0o644)

    def test_install_writes_through_a_symlinked_settings_file(self) -> None:
        target = self.home / "dotfiles" / "claude-settings.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(FOREIGN_SETTINGS, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        original = target.read_bytes()
        self.settings.parent.mkdir(parents=True, exist_ok=True)
        self.settings.symlink_to(target)

        self.assert_json_success(
            self.run_integration("install", "claude", "--json")
        )

        self.assertTrue(self.settings.is_symlink())
        self.assertEqual(os.readlink(self.settings), os.fspath(target))
        document = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(document["model"], "opus")
        self.assertEqual(
            document["hooks"]["SessionStart"], [expected_entry()]
        )
        self.assertEqual(self.read_settings(), document)

        self.assert_json_success(
            self.run_integration("uninstall", "claude", "--json")
        )

        self.assertTrue(self.settings.is_symlink())
        self.assertEqual(target.read_bytes(), original)


class RelocatedSettingsTest(IntegrationTestCase):
    def test_uninstall_with_a_relocated_path_refuses_and_keeps_state(
        self,
    ) -> None:
        self.run_integration("install", "claude")
        before = self.settings.read_bytes()

        result = self.run_integration(
            "uninstall", "claude", "--json", env=self.relocated_env()
        )

        self.assert_json_error(result, "drift", 3)
        self.assertTrue(self.manifest.exists())
        self.assertEqual(self.settings.read_bytes(), before)
        self.assertEqual(self.read_manifest()["entry"], expected_entry())

    def test_install_with_a_relocated_path_refuses(self) -> None:
        self.run_integration("install", "claude")
        relocated = self.relocated_env()

        result = self.run_integration(
            "install", "claude", "--json", env=relocated
        )

        self.assert_json_error(result, "drift", 3)
        self.assertFalse(
            os.path.exists(relocated["TMT_CLAUDE_SETTINGS"]),
            "install must not fork the managed file",
        )
        self.assertTrue(self.manifest.exists())

    def test_check_with_a_relocated_path_is_drifted(self) -> None:
        self.run_integration("install", "claude")

        result = self.run_integration(
            "check", "claude", "--json", env=self.relocated_env()
        )

        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(result.stderr, "")
        payload = self.parse_single_json(result.stdout)
        self.assertEqual(payload["status"], "drifted")
        self.assertEqual(payload["settings"], os.fspath(self.settings))

    def test_plan_with_a_relocated_path_reports_drift(self) -> None:
        self.run_integration("install", "claude")

        payload = self.assert_json_success(
            self.run_integration(
                "plan", "claude", "--json", env=self.relocated_env()
            )
        )

        self.assertEqual(payload["status"], "drift")
        self.assertEqual(payload["changed"], False)


class CorruptManifestTest(IntegrationTestCase):
    def test_check_reports_drifted_for_an_unparseable_manifest(self) -> None:
        self.run_integration("install", "claude")
        self.manifest.write_text("{ not json", encoding="utf-8")

        result = self.run_integration("check", "claude", "--json")

        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(result.stderr, "")
        payload = self.parse_single_json(result.stdout)
        self.assertEqual(payload["status"], "drifted")

    def test_check_reports_drifted_for_an_unsupported_manifest_version(
        self,
    ) -> None:
        self.run_integration("install", "claude")
        manifest = self.read_manifest()
        manifest["v"] = 99
        self.write_manifest(manifest)

        result = self.run_integration("check", "claude")

        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual(result.stdout, "drifted\n")


class ReinstallTest(IntegrationTestCase):
    def test_reinstall_updates_a_changed_command_in_place(self) -> None:
        self.write_settings(FOREIGN_SETTINGS)
        self.run_integration("install", "claude")
        manifest = self.read_manifest()
        manifest["entry"] = stale_entry()
        self.write_manifest(manifest)
        self.write_owned_groups([stale_entry()])

        preview = self.assert_json_success(
            self.run_integration("plan", "claude", "--json")
        )
        self.assertEqual(preview["status"], "update")
        self.assertEqual(preview["changed"], True)

        payload = self.assert_json_success(
            self.run_integration("install", "claude", "--json")
        )

        self.assertEqual(payload["changed"], True)
        document = self.read_settings()
        self.assertEqual(
            document["hooks"]["SessionStart"], [expected_entry()]
        )
        self.assertEqual(
            document["hooks"]["UserPromptSubmit"],
            FOREIGN_SETTINGS["hooks"]["UserPromptSubmit"],
        )
        self.assertEqual(self.read_manifest()["entry"], expected_entry())

    def test_install_supersedes_a_stale_entry_without_a_manifest(
        self,
    ) -> None:
        self.write_settings(FOREIGN_SETTINGS)
        self.run_integration("install", "claude")
        self.write_owned_groups([FOREIGN_GROUP, stale_entry()])
        self.manifest.unlink()

        payload = self.assert_json_success(
            self.run_integration("install", "claude", "--json")
        )

        self.assertEqual(payload["changed"], True)
        self.assertEqual(
            self.read_settings()["hooks"]["SessionStart"],
            [FOREIGN_GROUP, expected_entry()],
        )
        manifest = self.read_manifest()
        self.assertEqual(manifest["entry"], expected_entry())
        self.assertEqual(manifest["created_file"], False)
        self.assertEqual(manifest["created_containers"], [])

        result = self.run_integration("check", "claude", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)


class MalformedSettingsTest(IntegrationTestCase):
    """A settings.json tmt cannot read is never rewritten or guessed at.

    plan, install, and uninstall refuse with ``check-failed``; check
    reports ``drifted`` on stdout with no error envelope; and the
    unreadable file keeps its exact bytes so the user can repair it.
    """

    def corrupt(self, text: str) -> bytes:
        """Replace the settings file wholesale; return its exact bytes."""
        self.settings.parent.mkdir(parents=True, exist_ok=True)
        self.settings.write_text(text, encoding="utf-8")
        return self.settings.read_bytes()

    def installed_then_corrupt(self, text: str) -> bytes:
        """Install cleanly (so a manifest exists), then corrupt settings."""
        self.run_integration("install", "claude")
        return self.corrupt(text)

    def assert_check_is_drifted(self) -> None:
        result = self.run_integration("check", "claude", "--json")

        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(result.stderr, "")
        payload = self.parse_single_json(result.stdout)
        self.assertEqual(payload["status"], "drifted")
        self.assertEqual(payload["settings"], os.fspath(self.settings))

    def test_plan_refuses_an_unparseable_settings_file(self) -> None:
        before = self.corrupt(UNPARSEABLE)

        result = self.run_integration("plan", "claude", "--json")

        payload = self.assert_json_error(result, "check-failed", 3)
        self.assertIn("does not parse", payload["error"])
        self.assertEqual(self.settings.read_bytes(), before)
        self.assertFalse(self.manifest.exists())

    def test_install_refuses_an_unparseable_settings_file(self) -> None:
        before = self.corrupt(UNPARSEABLE)

        result = self.run_integration("install", "claude", "--json")

        self.assert_json_error(result, "check-failed", 3)
        self.assertEqual(self.settings.read_bytes(), before)
        self.assertFalse(
            self.manifest.exists(), "a refused install claims nothing"
        )

    def test_check_drifts_for_an_unparseable_settings_file(self) -> None:
        before = self.installed_then_corrupt(UNPARSEABLE)

        self.assert_check_is_drifted()

        plain = self.run_integration("check", "claude")
        self.assertEqual(plain.returncode, 1)
        self.assertEqual(plain.stdout, "drifted\n")
        self.assertEqual(plain.stderr, "")
        self.assertEqual(self.settings.read_bytes(), before)
        self.assertTrue(self.manifest.exists(), "check never mutates")

    def test_uninstall_refuses_an_unparseable_settings_file(self) -> None:
        before = self.installed_then_corrupt(UNPARSEABLE)
        manifest = self.manifest.read_bytes()

        result = self.run_integration("uninstall", "claude", "--json")

        self.assert_json_error(result, "check-failed", 3)
        self.assertEqual(self.settings.read_bytes(), before)
        self.assertEqual(self.manifest.read_bytes(), manifest)

    def test_uninstall_without_a_manifest_never_reads_settings(self) -> None:
        before = self.corrupt(UNPARSEABLE)

        payload = self.assert_json_success(
            self.run_integration("uninstall", "claude", "--json")
        )

        self.assertEqual(payload["changed"], False)
        self.assertEqual(payload["removed"], False)
        self.assertEqual(self.settings.read_bytes(), before)

    def test_refuses_a_settings_file_that_is_not_an_object(self) -> None:
        before = self.corrupt("[]\n")

        plan = self.run_integration("plan", "claude", "--json")
        install = self.run_integration("install", "claude", "--json")

        payload = self.assert_json_error(plan, "check-failed", 3)
        self.assertIn("is not a JSON object", payload["error"])
        self.assert_json_error(install, "check-failed", 3)
        self.assertEqual(self.settings.read_bytes(), before)
        self.assertFalse(self.manifest.exists())

    def test_check_drifts_for_a_bare_json_string_settings_file(self) -> None:
        before = self.installed_then_corrupt('"text"\n')

        self.assert_check_is_drifted()

        self.assertEqual(self.settings.read_bytes(), before)

    def test_install_refuses_hooks_that_are_not_an_object(self) -> None:
        before = self.corrupt('{"hooks": ["SessionStart"]}\n')

        result = self.run_integration("install", "claude", "--json")

        payload = self.assert_json_error(result, "check-failed", 3)
        self.assertIn("'hooks' is not an object", payload["error"])
        self.assertEqual(self.settings.read_bytes(), before)
        self.assertFalse(self.manifest.exists())

    def test_check_drifts_for_hooks_that_are_not_an_object(self) -> None:
        before = self.installed_then_corrupt('{"hooks": "off"}\n')

        self.assert_check_is_drifted()

        self.assertEqual(self.settings.read_bytes(), before)

    def test_install_refuses_session_start_that_is_not_an_array(self) -> None:
        before = self.corrupt(
            '{"hooks": {"SessionStart": {"matcher": "startup"}}}\n'
        )

        result = self.run_integration("install", "claude", "--json")

        payload = self.assert_json_error(result, "check-failed", 3)
        self.assertIn("hooks.SessionStart is not an array", payload["error"])
        self.assertEqual(self.settings.read_bytes(), before)
        self.assertFalse(self.manifest.exists())

    def test_uninstall_refuses_session_start_that_is_not_an_array(
        self,
    ) -> None:
        before = self.installed_then_corrupt(
            '{"hooks": {"SessionStart": "on"}}\n'
        )
        manifest = self.manifest.read_bytes()

        result = self.run_integration("uninstall", "claude", "--json")

        self.assert_json_error(result, "check-failed", 3)
        self.assertEqual(self.settings.read_bytes(), before)
        self.assertEqual(self.manifest.read_bytes(), manifest)

    def test_check_drifts_for_session_start_that_is_not_an_array(self) -> None:
        # A number, not an object: an object or string would iterate as
        # zero matching groups and read as drift even unguarded, so it
        # would not prove the guard is what reports it.
        before = self.installed_then_corrupt(
            '{"hooks": {"SessionStart": 5}}\n'
        )

        self.assert_check_is_drifted()

        self.assertEqual(self.settings.read_bytes(), before)


class MalformedManifestTest(IntegrationTestCase):
    """A manifest tmt cannot verify is drift, and it survives.

    Ownership is decided by the manifest alone, so an unreadable one is
    reported (``drifted`` from check, ``check-failed`` from install and
    uninstall) and never deleted: the state stays recoverable by hand.
    """

    def install_and_read_manifest(self) -> dict[str, Any]:
        self.run_integration("install", "claude")
        return self.read_manifest()

    def assert_check_is_drifted(self) -> None:
        result = self.run_integration("check", "claude", "--json")

        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(result.stderr, "")
        payload = self.parse_single_json(result.stdout)
        self.assertEqual(payload["status"], "drifted")

    def test_check_drifts_for_each_missing_required_key(self) -> None:
        pristine = self.install_and_read_manifest()
        self.assertEqual(
            sorted(pristine),
            [
                "created_containers",
                "created_file",
                "entry",
                "integration",
                "scope",
                "settings",
                "v",
            ],
        )

        for key in sorted(pristine):
            with self.subTest(missing=key):
                self.write_manifest(
                    {
                        name: value
                        for name, value in pristine.items()
                        if name != key
                    }
                )

                self.assert_check_is_drifted()

    def test_check_drifts_for_wrong_manifest_field_types(self) -> None:
        pristine = self.install_and_read_manifest()

        for key, value in (
            ("created_containers", "hooks"),
            ("created_file", "yes"),
            ("entry", []),
            ("settings", 42),
        ):
            with self.subTest(field=key):
                self.write_manifest({**pristine, key: value})

                self.assert_check_is_drifted()

    def test_install_refuses_an_unverifiable_manifest_and_keeps_it(
        self,
    ) -> None:
        pristine = self.install_and_read_manifest()
        self.write_manifest({**pristine, "settings": 42})
        settings = self.settings.read_bytes()
        manifest = self.manifest.read_bytes()

        result = self.run_integration("install", "claude", "--json")

        payload = self.assert_json_error(result, "check-failed", 3)
        self.assertIn(os.fspath(self.manifest), payload["error"])
        self.assertEqual(self.manifest.read_bytes(), manifest)
        self.assertEqual(self.settings.read_bytes(), settings)

    def test_uninstall_refuses_a_manifest_missing_a_key_and_keeps_it(
        self,
    ) -> None:
        pristine = self.install_and_read_manifest()
        del pristine["entry"]
        self.write_manifest(pristine)
        settings = self.settings.read_bytes()
        manifest = self.manifest.read_bytes()

        result = self.run_integration("uninstall", "claude", "--json")

        self.assert_json_error(result, "check-failed", 3)
        self.assertEqual(self.manifest.read_bytes(), manifest)
        self.assertEqual(self.settings.read_bytes(), settings)

    def test_lifecycle_refuses_an_unsupported_manifest_version(self) -> None:
        pristine = self.install_and_read_manifest()
        self.write_manifest({**pristine, "v": 99})
        settings = self.settings.read_bytes()
        manifest = self.manifest.read_bytes()

        install = self.run_integration("install", "claude", "--json")
        uninstall = self.run_integration("uninstall", "claude", "--json")

        payload = self.assert_json_error(install, "check-failed", 3)
        self.assertIn("unsupported version", payload["error"])
        self.assert_json_error(uninstall, "check-failed", 3)
        self.assertEqual(self.manifest.read_bytes(), manifest)
        self.assertEqual(self.settings.read_bytes(), settings)


class UnownedMatcherGroupTest(IntegrationTestCase):
    """Someone else's group is never superseded, matcher notwithstanding.

    In-place supersession is only for a group that really is one
    ``tmt context`` command; every other shape is preserved and the owned
    entry is appended beside it.
    """

    def install_over(self, groups: list[Any]) -> list[Any]:
        self.write_settings({"hooks": {"SessionStart": groups}})

        payload = self.assert_json_success(
            self.run_integration("install", "claude", "--json")
        )

        self.assertEqual(payload["changed"], True)
        return self.read_settings()["hooks"]["SessionStart"]

    def test_an_unrelated_command_is_preserved(self) -> None:
        foreign = matcher_group("/usr/bin/true", timeout=5)

        groups = self.install_over([foreign])

        self.assertEqual(groups, [foreign, expected_entry()])
        self.assertEqual(self.read_manifest()["entry"], expected_entry())
        check = self.run_integration("check", "claude")
        self.assertEqual(check.returncode, 0, check.stderr)

    def test_a_group_of_several_commands_is_preserved(self) -> None:
        # The tmt command is in there, but rewriting the group in place
        # would delete its sibling, so the group is left alone.
        crowded = matcher_group(
            f"{shlex.quote(sys.executable)} -m tmt context",
            "/usr/bin/notify-send hello",
        )

        groups = self.install_over([crowded])

        self.assertEqual(groups, [crowded, expected_entry()])

    def test_near_miss_tmt_commands_are_preserved(self) -> None:
        near_misses: list[Any] = [
            matcher_group("/opt/pipx/bin/tmt check"),
            matcher_group("/usr/bin/python3 -m tmtlab context"),
            matcher_group('/usr/local/bin/tmt "context'),
            matcher_group(42),
        ]

        groups = self.install_over(list(near_misses))

        self.assertEqual(groups, [*near_misses, expected_entry()])

    def test_malformed_groups_are_preserved(self) -> None:
        junk: list[Any] = [
            "not-a-group",
            {"matcher": OWNED_MATCHER, "hooks": "off"},
            {"matcher": OWNED_MATCHER, "hooks": []},
            {"matcher": OWNED_MATCHER, "hooks": ["not-a-hook"]},
            {"matcher": OWNED_MATCHER},
        ]

        groups = self.install_over(list(junk))

        self.assertEqual(groups, [*junk, expected_entry()])

    def test_an_equivalent_module_command_is_superseded_in_place(self) -> None:
        # The acceptance arm: same matcher, one hook, an equivalent
        # `<python> -m tmt context` command under a stale timeout.
        stale = matcher_group(
            f"{shlex.quote(sys.executable)} -m tmt context", timeout=30
        )

        groups = self.install_over([FOREIGN_GROUP, stale])

        self.assertEqual(groups, [FOREIGN_GROUP, expected_entry()])


class ConsoleScriptCommandTest(IntegrationTestCase):
    """The console-script resolution branch of ``tmt_command()``.

    Every other test drives ``python -m tmt``, which takes the documented
    fallback; only an argv[0] naming an executable ``tmt`` file reaches
    the branch that writes a bare ``/abs/path/to/tmt context``, so this
    test builds such a file rather than installing a wheel.
    """

    def setUp(self) -> None:
        super().setUp()
        self.script = console_script(self.make_dir())

    def test_print_hook_uses_the_console_script_path(self) -> None:
        result = run_console(
            self.script,
            self.cwd,
            "integration",
            "print",
            "hook",
            "claude",
            "--json",
            env=self.env,
        )

        payload = self.assert_json_success(result)
        self.assertEqual(
            payload["fragment"],
            {"hooks": {"SessionStart": [script_entry(self.script)]}},
        )

    def test_install_writes_a_runnable_console_script_command(self) -> None:
        result = run_console(
            self.script,
            self.cwd,
            "integration",
            "install",
            "claude",
            "--json",
            env=self.env,
        )

        self.assert_json_success(result)
        self.assertEqual(
            self.read_settings()["hooks"]["SessionStart"],
            [script_entry(self.script)],
        )
        self.assertEqual(
            self.read_manifest()["entry"], script_entry(self.script)
        )

        command = script_entry(self.script)["hooks"][0]["command"]
        words = shlex.split(command)
        self.assertEqual(words, [os.fspath(self.script), "context"])
        hook = run_console(
            Path(words[0]), self.cwd, *words[1:], env=self.env
        )
        self.assertEqual(hook.returncode, 0, hook.stderr)

        check = run_console(
            self.script, self.cwd, "integration", "check", "claude",
            env=self.env,
        )
        self.assertEqual(check.returncode, 0, check.stderr)
        self.assertEqual(check.stdout, "ok\n")


if __name__ == "__main__":
    unittest.main()
