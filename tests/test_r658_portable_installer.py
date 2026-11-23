"""R658 portable host installer boundary tests; no network, model or device."""
from __future__ import annotations
import argparse
import json
import os
import platform
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts import r658_install as install

@unittest.skipUnless(sys.platform=="darwin" and platform.machine()=="arm64",
                     "Apple Silicon macOS production prerequisite")
class PortableInstaller(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home=Path(self.temp.name)/"fresh profile with spaces"

    def args(self, **other):
        v=dict(dsh_home=str(self.home),python=sys.executable,
               computer_helper=str(Path(self.temp.name)/"cua-helper"),
               trusted_host=[],initialize_secrets=False,
               network=False,confirm_network=False,pinky_app=None,dsh_cli=None)
        v.update(other)
        return argparse.Namespace(**v)

    def test_doctor_separates_host_only_from_optional_phone_cua(self):
        install.prepare(self.args(initialize_secrets=True))
        checks={"macos_host":True,"pinky_proxy_script_available":True,
                "dsh_cli_available":True,"pinky_app_installed":False,
                "cua_helper_executable":False}
        fake={"profile":"web","checks":checks,
              "ready_for_local_configuration_smoke":False}
        with patch.object(install.profile,"doctor",return_value=fake):
            result=install.doctor(self.args())
        self.assertTrue(result["lock_matches_template"])
        self.assertTrue(result["ready_for_host_only_configuration_smoke"])
        self.assertFalse(result["ready_for_local_configuration_smoke"])
        checks["bridge_plugin_installed"]=False
        with patch.object(install.profile,"doctor",return_value=fake):
            result=install.doctor(self.args())
        self.assertFalse(result["ready_for_host_only_configuration_smoke"])

    def test_plan_is_readonly_and_never_authorizes_flash(self):
        r=install.plan(self.args())
        self.assertTrue(r["can_prepare"])
        self.assertFalse(self.home.exists())
        self.assertFalse(r["will_flash_esp32"])
        self.assertFalse(r["will_start_services"])
        self.assertFalse(r["will_run_phone_or_model"])

    def test_create_private_portable_lock_fails_on_second_invocation(self):
        r=install.prepare(self.args())
        self.assertEqual(r["bundles"],3)
        self.assertTrue(self.home.exists())
        self.assertEqual((self.home/"secrets").stat().st_mode&0o777,0o700)
        lock=self.home/"profiles/web/pnpm-lock.yaml"
        self.assertEqual(lock.stat().st_mode&0o777,0o600)
        self.assertEqual(lock.read_text(),install.rendered_lock(self.home.resolve()))
        self.assertEqual(lock.read_text().count(str(install.PROJECT)),0)
        self.assertNotIn("__COMPANION_",lock.read_text())
        with self.assertRaisesRegex(install.InstallFailure,
                                    "host_prerequisites_incomplete"):
            install.prepare(self.args())

    def test_optional_tokens_generated_only_with_explicit_flag(self):
        install.prepare(self.args(initialize_secrets=True))
        sec=self.home/"secrets"
        items=sorted(sec.iterdir())
        self.assertEqual(len(items),2)
        tokens=[x.read_text() for x in items]
        self.assertNotEqual(tokens[0],tokens[1])
        self.assertTrue(all(len(t)>50 and t.endswith("\n") for t in tokens))
        self.assertTrue(all(x.stat().st_mode&0o777==0o600 for x in items))

    def test_private_bridge_clone_is_separate_and_does_not_mutate_project(self):
        result=install.prepare(self.args())
        copied=self.home/"extensions/dsh-live-bridge"
        self.assertTrue(result["private_bridge_copy"])
        self.assertTrue((copied/"lib/index.js").is_file())
        self.assertTrue((copied/"package.json").is_file())
        self.assertEqual((copied/"LICENSE").read_bytes(),
                         (install.PROJECT/"plugins/dsh-live-bridge/LICENSE").read_bytes())
        self.assertEqual((copied/"LICENSE").stat().st_mode&0o777,0o600)
        self.assertTrue((copied/"pnpm-lock.yaml").is_file())
        self.assertFalse((copied/"node_modules").exists())
        self.assertEqual(copied.stat().st_mode&0o777,0o700)
        self.assertEqual((copied/"lib/index.js").stat().st_mode&0o777,0o600)
        p=self.home/"profiles/web/package.json"
        j=json.loads(p.read_text())
        self.assertEqual(j["dependencies"]["dsh-live-bridge"],
                         "link:"+str(copied.resolve()))
        self.assertNotIn(str(install.PROJECT), j["dependencies"]["dsh-live-bridge"])

    def test_private_bridge_lock_tampering_blocks_frozen_install(self):
        install.prepare(self.args())
        p=self.home/"extensions/dsh-live-bridge/pnpm-lock.yaml"
        p.write_text(p.read_text()+"# forged\n")
        with self.assertRaisesRegex(install.InstallFailure,"private_bridge_lock_changed"):
            install.deps(self.args())

    def test_deps_never_allows_network_without_explicit_consent(self):
        install.prepare(self.args())
        with self.assertRaisesRegex(install.InstallFailure,
                                    "network_requires_explicit_confirmation"):
            install.deps(self.args(network=True))

    def test_deps_rejects_modified_manifest_or_lock(self):
        install.prepare(self.args())
        pkg=self.home/"profiles/web/package.json"
        obj=json.loads(pkg.read_text())
        obj["dsh"]["profile"]["bundles"].append("dsh-ops")
        pkg.write_text(json.dumps(obj))
        with self.assertRaisesRegex(install.InstallFailure,
                                    "profile_dependency_mismatch"):
            install.deps(self.args())
        obj["dsh"]["profile"]["bundles"].pop()
        pkg.write_text(json.dumps(obj))
        lock=self.home/"profiles/web/pnpm-lock.yaml"
        lock.write_text(lock.read_text()+"# modified\n")
        with self.assertRaisesRegex(install.InstallFailure,"pinned_lock_changed"):
            install.deps(self.args())

    def test_deps_uses_frozen_offline_and_disables_scripts(self):
        install.prepare(self.args())
        cli=self.home/"profiles/web/node_modules/@deepseek-ai/dsh/lib/bin.js"
        cli.parent.mkdir(parents=True)
        cli.write_text("official CLI fixture")
        answer=argparse.Namespace(returncode=0,
            stdout=("id: dsh-live-bridge\nid: mcp-pinky-dafeiyu\n"
                    "id: computer-use\nid: cua-macos\n"),stderr="")
        with patch.object(install.subprocess,"run",return_value=answer) as run:
            obj=install.deps(self.args())
        self.assertTrue(obj["installed"])
        self.assertTrue(obj["ready_for_configuration_smoke"])
        self.assertEqual(run.call_count,5)
        command=run.call_args_list[0].args[0]
        self.assertIn("--frozen-lockfile",command)
        self.assertIn("--offline",command)
        self.assertIn("--ignore-scripts",command)
        self.assertNotIn("--prefer-offline",command)

    def test_pnpm_success_without_actual_dsh_cli_is_not_success(self):
        install.prepare(self.args())
        answer=argparse.Namespace(returncode=0,stdout="",stderr="")
        with patch.object(install.subprocess,"run",return_value=answer) as run:
            result=install.deps(self.args())
        self.assertTrue(result["installed"])
        self.assertFalse(result["ready_for_configuration_smoke"])
        self.assertEqual(result["error_code"],
                         "pinned_bridge_cli_or_config_not_verified")
        self.assertEqual(run.call_count,2)

    def test_broken_core_config_never_reports_ready(self):
        install.prepare(self.args())
        cli=self.home/"profiles/web/node_modules/@deepseek-ai/dsh/lib/bin.js"
        cli.parent.mkdir(parents=True)
        cli.write_text("official CLI fixture")
        answer=argparse.Namespace(returncode=0,stdout="id: dsh-live-bridge\n",
                                  stderr="")
        with patch.object(install.subprocess,"run",return_value=answer) as run:
            result=install.deps(self.args())
        self.assertTrue(result["installed"])
        self.assertFalse(result["ready_for_configuration_smoke"])
        self.assertFalse(result["core_rows_verified"])
        self.assertEqual(run.call_count,4)

    def test_existing_default_dsh_cannot_be_overwritten(self):
        with self.assertRaisesRegex(install.InstallFailure,"unsafe_home"):
            install.plan(self.args(dsh_home=str(Path.home()/".dsh")))

    def test_device_plan_never_flashes_and_does_not_reuse_old_receipts(self):
        if not (install.PROJECT/"firmware/esp32/unified-wifi-wake/CMakeLists.txt").is_file():
            self.skipTest("Host-only public preview intentionally excludes ESP32 firmware")
        v=install.device_plan(self.args())
        self.assertTrue(v["firmware_tree_complete"])
        self.assertFalse(v["flash_authorized"])
        self.assertEqual(v["writes"],0)
        self.assertTrue(any("release receipt" in s for s in v["ordered_steps"]))

if __name__=="__main__":
    unittest.main()
