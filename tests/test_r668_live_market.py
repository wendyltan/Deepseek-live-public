"""R668 remote DSH plugin index tests. No network or production writes."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts import r668_live_market as market

def make_index():
    return {"format":1,"title":"fixture","plugins":[
     {"name":"dsh-test-remote",
      "title":{"en":"Remote A","zh":"远程A"},
      "description":{"zh":"远程索引里的新插件"},
      "metadata":{"category":"tools"},
      "homepage":"https://example.org/a",
      "versions":[{"version":"0.1.0","publishTimestamp":100,
        "source":{"type":"npm"}},{"version":"0.2.0",
        "publishTimestamp":200,"source":{"type":"npm"},
        "engines":{"dsh":">=0.2.1"}}]},
     {"name":"dsh-test-local","title":"Locally installed",
      "description":"present","metadata":{},
      "versions":[{"version":"1.0.0","publishTimestamp":100,
                   "source":{"type":"git","url":"https://example.org/r"}}]},
    ]}

class LiveDiscovery(unittest.TestCase):
    def setUp(self):
        self.f=tempfile.TemporaryDirectory()
        self.addCleanup(self.f.cleanup)
        self.home=Path(self.f.name)
        self.read_patch=patch.object(market.manager,"read_profile",
              return_value=({"dependencies":{"dsh-test-local":"1.0.0"}},b""))
        self.read_patch.start()
        self.addCleanup(self.read_patch.stop)
    def test_live_search_not_bounded_by_local_installs(self):
        x=market.discover(self.home,"远程",fetcher=make_index)
        self.assertEqual(x["catalog_type"],"live_dsh_format1")
        self.assertEqual(x["total_matches"],1)
        self.assertEqual(x["items"][0]["id"],"dsh-test-remote")
        self.assertEqual(x["items"][0]["version"],"0.2.0")
        self.assertFalse(x["items"][0]["declared_locally"])
        self.assertFalse(x["items"][0]["published_version_verified_online"])
    def test_marks_installed_and_accepts_git_entries(self):
        x=market.discover(self.home,"",fetcher=make_index)
        self.assertEqual(x["total_matches"],2)
        self.assertTrue(x["items"][1]["declared_locally"])
        self.assertEqual(x["items"][1]["source"],"git")
    def test_invalid_index_or_query_fail_closed(self):
        with self.assertRaisesRegex(ValueError,"market_format1_required"):
            market.discover(self.home,fetcher=lambda:{"plugins":[]})
        with self.assertRaisesRegex(ValueError,"market_invalid_query"):
            market.discover(self.home,"a"*76,fetcher=make_index)
    def test_never_fetches_per_plugin_or_installs(self):
        with patch.object(market.urllib.request,"urlopen",
                          side_effect=AssertionError("must not be called")):
            x=market.discover(self.home,"remote",fetcher=make_index)
        self.assertEqual(x["packages_installed"],0)
        self.assertTrue(x["needs_human_install_approval"])

if __name__=="__main__":
    unittest.main()
