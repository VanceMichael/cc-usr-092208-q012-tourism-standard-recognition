import unittest
from pathlib import Path
from src.domain import load_domain

class DomainTest(unittest.TestCase):
    def test_fixture_matches_domain(self):
        value = load_domain(Path("fixtures/domain.json"))
        self.assertEqual(value["domain"], "tourism-standard-recognition")
        self.assertGreaterEqual(len(value["constraints"]), 2)

    def test_services_cover_mark_commitments(self):
        value = load_domain(Path("fixtures/domain.json"))
        for service in ("多语种接待", "支付帮助", "应急联络"):
            self.assertIn(service, value["services"])

    def test_recognition_levels_distinguishable(self):
        value = load_domain(Path("fixtures/domain.json"))
        for level in ("自我声明", "第三方认证", "正式互认"):
            self.assertIn(level, value["recognition_levels"])

    def test_change_triggers_cover_listed_events(self):
        value = load_domain(Path("fixtures/domain.json"))
        for trigger in ("标准修订", "认证暂停", "抽查不合格", "机构退出", "跨境关系撤销"):
            self.assertIn(trigger, value["change_triggers"])

if __name__ == "__main__":
    unittest.main()
