"""R656 public companion profile: deterministic, private, exact tools, no secrets."""
from __future__ import annotations

import argparse
import json
import stat
import tempfile
import unittest
from pathlib import Path

from scripts.r656_companion_profile import BUNDLES, PACKAGES, doctor, generate, inspect


class MinimalCompanionProfile(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.base = Path(self.work.name)
        self.project = self.base / "my companion test"
        self.project.mkdir()
        for filename in (
            "plugins/dsh-live-bridge/package.json",
            "plugins/dsh-live-bridge/cordis.patch.yml",
            "scripts/pinky_mcp_named_proxy.py",
            "app/companion_persona.txt",
        ):
            p = self.project / filename
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("fixture\n")
        self.home = self.base / "companion home"

    def opts(self, **changed):
        args = {
            "dsh_home": str(self.home),
            "project_root": str(self.project),
            "python": "/opt/homebrew/bin/python3.12",
            "pinky_proxy": None,
            "computer_helper": str(self.base / "macOS helper"),
            "bridge_token": None,
            "memory_token": None,
            "session_dir": None,
            "manual_memory_dir": None,
            "growth_dir": None,
            "trusted_host": [],
        }
        args.update(changed)
        return argparse.Namespace(**args)

    def test_minimal_includes_computer_pinky_memory_and_no_optional_bundles(self):
        result = generate(self.opts())
        self.assertEqual(result["bundles"], 3)
        self.assertFalse(result["contains_secrets"])
        manifest = json.loads((self.home / "profiles/web/package.json").read_text())
        self.assertEqual(manifest["dsh"]["profile"]["bundles"], list(BUNDLES))
        self.assertEqual(set(manifest["dependencies"]),
                         {*PACKAGES, "dsh-live-bridge"})
        self.assertTrue(inspect(argparse.Namespace(dsh_home=str(self.home)))
                        ["computer_control_declared"])
        p = (self.home / "profiles/web/cordis.patch.yml").read_text()
        for s in ("mcp-pinky-dafeiyu", "computer-use", "cua-macos",
                  "toolMode: native", "sessionRecovery: true",
                  "manualMemory: true", "personaGrowth: true",
                  "approval"):
            self.assertIn(s, p)
        for path in ("", "profiles", "profiles/web", "secrets",
                     "companion-state"):
            self.assertEqual(
                stat.S_IMODE((self.home / path).stat().st_mode), 0o700)
        self.assertFalse(list((self.home / "secrets").iterdir()))

    def test_no_overwrite_live_profile_or_other_owners_data(self):
        generate(self.opts())
        sentinel = self.home / "secrets/keep-user-token"
        sentinel.write_text("DO-NOT-TOUCH")
        with self.assertRaisesRegex(ValueError, "destination_already_exists"):
            generate(self.opts())
        self.assertEqual(sentinel.read_text(), "DO-NOT-TOUCH")

    def test_preserves_approved_existing_paths_and_trusted_hosts(self):
        data = generate(self.opts(
            trusted_host=["example.tailnet.net"],
            bridge_token=str(self.base / "bridge token"),
            memory_token=str(self.base / "memory admin token"),
            session_dir=str(self.base / "existing session"),
            manual_memory_dir=str(self.base / "existing facts"),
            growth_dir=str(self.base / "existing growth")))
        p = (self.home / "profiles/web/cordis.patch.yml").read_text()
        self.assertIn('- id: connection\n  config:\n    trustedHosts:\n',
                      p)
        self.assertIn("- id: web-runtime\n", p)
        for name in ("existing session", "existing facts", "existing growth",
                     "bridge token", "memory admin token"):
            self.assertIn(name, p)
        self.assertIn("example.tailnet.net", p)
        self.assertEqual(data["contains_secrets"], False)

    def test_untrusted_host_is_rejected_without_creating_output(self):
        with self.assertRaisesRegex(ValueError, "trusted_host_invalid"):
            generate(self.opts(trusted_host=["example.com/foo"]))
        self.assertFalse(self.home.exists())

    def test_profile_must_be_separate_from_project(self):
        with self.assertRaisesRegex(ValueError,
                                    "home_must_be_a_separate_durable_location"):
            generate(self.opts(dsh_home=str(self.project / "dsh-home")))
        self.assertFalse((self.project / "dsh-home").exists())

    def test_doctor_reports_prerequisites_without_secret_material(self):
        generate(self.opts())
        for name in ("bridge", "memory-admin"):
            file = self.home / ("secrets/" + name + ".token")
            file.write_text("MY_SUPER_SECRET_" + name)
            file.chmod(0o600)
        app = self.base / "Pinky.app"
        app.mkdir()
        cli = self.base / "official-dsh-cli.js"
        cli.write_text("test")
        result = doctor(argparse.Namespace(
            dsh_home=str(self.home),
            dsh_cli=str(cli), pinky_app=str(app)))
        report=json.dumps(result)
        self.assertIn("dsh_cli_available", report)
        self.assertTrue(result["checks"]["bridge_token_private"])
        self.assertTrue(result["checks"]["memory_admin_token_private"])
        self.assertNotIn("MY_SUPER_SECRET", report)
        self.assertEqual(result["provider_authenticated"], "not_checked")
        self.assertEqual(result["phone_or_computer_action_verified"], "not_run")
        self.assertFalse(result["ready_for_local_configuration_smoke"])

    def test_tampered_bundle_manifest_fails_verification(self):
        generate(self.opts())
        p = self.home / "profiles/web/package.json"
        obj = json.loads(p.read_text())
        obj["dsh"]["profile"]["bundles"].append("dsh-better-sidebar")
        p.write_text(json.dumps(obj))
        with self.assertRaisesRegex(ValueError, "bundle_allowlist_wrong"):
            inspect(argparse.Namespace(dsh_home=str(self.home)))


if __name__ == "__main__":
    unittest.main()
