"""Offline regression tests for hospital-specific search filtering."""
import unittest
from types import SimpleNamespace

from src.backend.ingestion.hospital_filter import HospitalFilter
from src.backend.ingestion.hospital_mapping import normalize_hospital_name


class HospitalFilterTests(unittest.TestCase):
    def setUp(self):
        self.first = SimpleNamespace(metadata={"hospital": "肇庆市一"})
        self.second = SimpleNamespace(metadata={"hospital": "肇庆市二"})
        self.unclassified = SimpleNamespace(metadata={})

    def test_strict_filter_excludes_other_and_unclassified_hospitals(self):
        nodes = [self.second, self.unclassified, self.first]
        self.assertEqual(
            HospitalFilter.filter_by_hospital(nodes, "肇庆市一", strict=True),
            [self.first],
        )
        self.assertEqual(nodes, [self.second, self.unclassified, self.first])

    def test_strict_filter_does_not_fall_back_when_target_is_missing(self):
        self.assertEqual(
            HospitalFilter.filter_by_hospital(
                [self.second, self.unclassified], "肇庆市一", strict=True
            ),
            [],
        )

    def test_strict_filter_normalizes_metadata_and_query_aliases(self):
        for name in ["肇庆一", "肇庆市第一人民医院", " 肇庆市一 "]:
            with self.subTest(name=name):
                alias_node = SimpleNamespace(metadata={"hospital": name})
                self.assertEqual(
                    HospitalFilter.filter_by_hospital(
                        [self.second, alias_node], name, strict=True
                    ),
                    [alias_node],
                )

    def test_second_hospital_never_returns_first_hospital(self):
        self.assertEqual(
            HospitalFilter.filter_by_hospital(
                [self.first, self.second], "肇庆二", strict=True
            ),
            [self.second],
        )

    def test_generic_query_preserves_results(self):
        nodes = [self.first, self.second, self.unclassified]
        self.assertIs(HospitalFilter.filter_by_hospital(nodes, None, strict=True), nodes)

    def test_empty_candidates_return_empty_results(self):
        self.assertEqual(
            HospitalFilter.filter_by_hospital([], "肇庆市一", strict=True), []
        )

    def test_explicit_soft_mode_remains_compatible(self):
        self.assertEqual(
            HospitalFilter.filter_by_hospital(
                [self.second, self.first], "肇庆市一", strict=False
            ),
            [self.first, self.second],
        )

    def test_full_name_not_listed_as_alias_is_normalized(self):
        self.assertEqual(normalize_hospital_name("广东省人民医院"), "省医")

    def test_blank_name_is_not_a_hospital(self):
        self.assertIsNone(normalize_hospital_name("  "))


if __name__ == "__main__":
    unittest.main()
