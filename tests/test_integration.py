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
        self, *arguments: str
    ) -> subprocess.CompletedProcess[str]:
        return run_tmt(self.cwd, "integration", *arguments, env=self.env)

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


if __name__ == "__main__":
    unittest.main()
