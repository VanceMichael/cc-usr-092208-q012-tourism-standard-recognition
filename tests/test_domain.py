import copy
import unittest
from pathlib import Path

from src.domain import (
    affected_marks,
    load_domain,
    mark_scope,
    recognition_rank,
    supplier_gap,
    trace_mark,
    validate_domain,
)


class DomainTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.domain = load_domain(Path("fixtures/domain.json"))

    def test_fixture_matches_domain(self):
        self.assertEqual(self.domain["domain"], "tourism-standard-recognition")
        self.assertGreaterEqual(len(self.domain["constraints"]), 2)

    def test_recognition_levels_are_ordered(self):
        self.assertLess(
            recognition_rank(self.domain, "self-declaration"),
            recognition_rank(self.domain, "third-party-certification"),
        )
        self.assertLess(
            recognition_rank(self.domain, "third-party-certification"),
            recognition_rank(self.domain, "formal-mutual-recognition"),
        )

    def test_mark_scope_states_services_regions_and_validity(self):
        scope = mark_scope(self.domain, "mark-001")
        self.assertEqual(scope["services"], ["多语种接待", "应急联络"])
        self.assertEqual(scope["regions"], ["广西桂林"])
        self.assertEqual(scope["valid_from"], "2026-01-01")
        self.assertEqual(scope["valid_to"], "2026-12-31")
        self.assertEqual(scope["recognition_level"], "formal-mutual-recognition")

    def test_every_mark_traces_to_records_and_responsible_parties(self):
        for mark in self.domain["marks"]:
            trace = trace_mark(self.domain, mark["id"])
            self.assertTrue(trace["records"], mark["id"])
            self.assertTrue(trace["responsible_parties"], mark["id"])
            for record in trace["records"]:
                self.assertEqual(record["mark_id"], mark["id"])

    def test_standard_revision_flags_matching_on_sale_marks(self):
        self.assertEqual(affected_marks(self.domain, "ce-001"), ["mark-001", "mark-002"])

    def test_certification_suspension_flags_marks_backed_by_body(self):
        self.assertEqual(affected_marks(self.domain, "ce-002"), ["mark-002"])

    def test_spot_check_failure_flags_single_mark(self):
        self.assertEqual(affected_marks(self.domain, "ce-003"), ["mark-003"])

    def test_cross_border_revocation_flags_marks_in_region(self):
        self.assertEqual(affected_marks(self.domain, "ce-004"), ["mark-002"])

    def test_supplier_gap_lists_missing_evidence_and_verification(self):
        gap = supplier_gap(self.domain, "mark-003", "formal-mutual-recognition")
        self.assertEqual(gap["missing_verification"], "on-site")
        self.assertEqual(
            gap["missing_evidence"],
            ["emergency-hotline-drill", "multilingual-staff-roster", "service-terms-review"],
        )
        self.assertTrue(gap["standard_outdated"])

    def test_supplier_gap_is_empty_when_requirements_met(self):
        gap = supplier_gap(self.domain, "mark-001", "formal-mutual-recognition")
        self.assertEqual(gap["missing_evidence"], [])
        self.assertIsNone(gap["missing_verification"])
        self.assertFalse(gap["standard_outdated"])

    def test_supplier_gap_flags_partial_evidence(self):
        gap = supplier_gap(self.domain, "mark-002", "formal-mutual-recognition")
        self.assertEqual(gap["missing_evidence"], ["emergency-hotline-drill"])
        self.assertEqual(gap["missing_verification"], "on-site")

    def test_formal_level_without_on_site_pass_is_rejected(self):
        broken = copy.deepcopy(self.domain)
        for record in broken["verification_records"]:
            if record["id"] == "vr-001":
                record["result"] = "fail"
        with self.assertRaises(ValueError):
            validate_domain(broken)

    def test_unknown_region_reference_is_rejected(self):
        broken = copy.deepcopy(self.domain)
        broken["marks"][0]["regions"] = ["cn-xx-nowhere"]
        with self.assertRaises(ValueError):
            validate_domain(broken)

    def test_change_event_without_scope_is_rejected(self):
        broken = copy.deepcopy(self.domain)
        broken["change_events"][0] = {"id": "ce-001", "type": "standard-revised", "date": "2026-07-01"}
        with self.assertRaises(ValueError):
            validate_domain(broken)


if __name__ == "__main__":
    unittest.main()
