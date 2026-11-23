"""R659 plugin manager: inventory and market plans never mutate the Host."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import r659_plugin_manager as manager

class CompanionPlugins(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name)
        self.home=self.base/"my-companion"
        p=self.home/"profiles/web"
        for folder in (self.home,self.home/"profiles",p,
                       p/"node_modules",p/"node_modules/dsh-better-sidebar"):
            folder.mkdir(mode=0o700,exist_ok=True)
        doc={"private":True,"name":"dsh-profile-web",
             "dependencies":{"dsh-live-bridge":"link:"+str(
                 manager.PROJECT/"plugins/dsh-live-bridge"),
                 "dsh-better-sidebar":"0.28.2"},
             "dsh":{"profile":{"bundles":[
                 "@deepseek-ai/dsh-base","@deepseek-ai/dsh-web-app",
                 "dsh-live-bridge"]}}}
        (p/"package.json").write_text(json.dumps(doc))
        (p/"cordis.patch.yml").write_text(
            "\n".join(f"- id: {name}" for name in sorted(manager.CORE_TOOL_IDS)))
        (p/"node_modules/dsh-better-sidebar/package.json").write_text(
            json.dumps({"name":"dsh-better-sidebar","version":"0.28.2"}))
        (p/"node_modules/dsh-live-bridge").symlink_to(
            manager.PROJECT/"plugins/dsh-live-bridge",target_is_directory=True)
        self.patcher=patch.object(manager,"ALLOWED_BASE",self.base)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_scope_never_includes_outside_directory(self):
        self.assertEqual(manager.home_path(self.home),self.home.resolve())
        with self.assertRaisesRegex(ValueError,"NOT_IN_COMPANION"):
            manager.home_path(self.base.parent/"outside")

    def test_inventory_has_core_and_installed_unloaded(self):
        info=manager.status(self.home)
        self.assertEqual(info["bundle_count"],3)
        self.assertEqual(info["declared_package_count"],2)
        self.assertTrue(all(x["declared"] for x in info["essential_tools"]))
        sidebar=next(x for x in info["packages"]
                     if x["name"]=="dsh-better-sidebar")
        self.assertTrue(sidebar["installed"])
        self.assertFalse(sidebar["is_bundle"],
                         "A dependency without a DSH bundle patch is not a plugin")
        self.assertFalse(sidebar["enabled_bundle"])

    def test_real_optional_bundle_is_manageable_after_metadata_validation(self):
        folder=self.home/"profiles/web/node_modules/dsh-better-sidebar"
        (folder/"cordis.patch.yml").write_text("- id: sidebar\n")
        (folder/"package.json").write_text(json.dumps({
            "name":"dsh-better-sidebar","version":"0.28.2",
            "dsh":{"bundle":{"patch":"./cordis.patch.yml"}}}))
        row=next(x for x in manager.status(self.home)["packages"]
                 if x["name"]=="dsh-better-sidebar")
        self.assertTrue(row["is_bundle"])
        # A path traversal in package metadata must never turn a library
        # or host file into a manageable plugin.
        (folder/"package.json").write_text(json.dumps({
            "name":"dsh-better-sidebar","version":"0.28.2",
            "dsh":{"bundle":{"patch":"../../../../../../etc/passwd"}}}))
        row=next(x for x in manager.status(self.home)["packages"]
                 if x["name"]=="dsh-better-sidebar")
        self.assertFalse(row["is_bundle"])

    def test_catalog_is_curated_and_offline(self):
        info=manager.marketplace(self.home,"侧栏")
        self.assertEqual(info["count"],1)
        self.assertEqual(info["items"][0]["id"],"dsh-better-sidebar")
        self.assertFalse(info["online_checked"])

    def test_enable_plan_has_no_mutations(self):
        p=self.home/"profiles/web/package.json"
        before=p.read_bytes()
        info=manager.proposal(self.home,"enable","dsh-better-sidebar")
        self.assertTrue(info["requires_user_approval"])
        self.assertTrue(info["requires_idle_host"])
        self.assertFalse(info["will_apply_now"])
        self.assertFalse(info["other_profile_affected"])
        self.assertEqual(before,p.read_bytes())

    def test_cannot_disable_core_or_pinky(self):
        for name in ("dsh-live-bridge","computer-use","mcp-pinky-dafeiyu"):
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError,"PROTECTED_CORE"):
                    manager.proposal(self.home,"disable",name)

    def test_disable_requires_enabled_optional(self):
        with self.assertRaisesRegex(ValueError,"DISABLE_REQUIRES_ENABLED"):
            manager.proposal(self.home,"disable","dsh-better-sidebar")

    def test_requires_reviewed_exact_market_name(self):
        with self.assertRaisesRegex(ValueError,"NOT_IN_REVIEWED_CATALOG"):
            manager.proposal(self.home,"install","some-unreviewed-npm")
        with self.assertRaisesRegex(ValueError,"INVALID_PACKAGE"):
            manager.proposal(self.home,"install","../../.dsh")

    def test_local_only_market_item_not_public_installable(self):
        with self.assertRaisesRegex(ValueError,"INSTALL_NEEDS_REGISTRY_PACKAGE"):
            manager.proposal(self.home,"install","dsh-ops-console")

    def test_symlink_to_outside_owner_is_never_trusted(self):
        node=self.home/"profiles/web/node_modules"
        item=node/"dsh-better-sidebar"
        # Non-destructive: the test tree is throwaway, not a real Home.
        import shutil
        shutil.rmtree(item)
        item.symlink_to("/etc")
        info=manager.status(self.home)
        value=next(x for x in info["packages"]
                   if x["name"]=="dsh-better-sidebar")
        self.assertFalse(value["installed"])

if __name__=="__main__":
    unittest.main()
