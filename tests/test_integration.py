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
from typing import Any

from _support import TmtTestCase, run_tmt

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


if __name__ == "__main__":
    unittest.main()
