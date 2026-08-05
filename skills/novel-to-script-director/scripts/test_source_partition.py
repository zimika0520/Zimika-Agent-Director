#!/usr/bin/env python3
from __future__ import annotations

import unittest

import source_partition


class SourcePartitionTests(unittest.TestCase):
    def source_corpus(self) -> dict:
        return {
            "schema_version": 1,
            "source_units": [
                {
                    "source_unit_id": "SU001",
                    "ordinal": 1,
                    "estimated_tokens": 3000,
                    "complexity_points": 10,
                },
                {
                    "source_unit_id": "SU002",
                    "ordinal": 2,
                    "estimated_tokens": 2000,
                    "complexity_points": 8,
                },
                {
                    "source_unit_id": "SU003",
                    "ordinal": 3,
                    "estimated_tokens": 4000,
                    "complexity_points": 12,
                },
            ],
        }

    def policy(self) -> dict:
        return {
            "max_input_tokens": 8000,
            "reserved_output_tokens": 2000,
            "chars_per_token_estimate": 1.8,
            "max_complexity_points": 30,
            "concurrency_mode": "bounded",
            "max_parallel_tasks": "auto",
            "single_state_writer": True,
        }

    def test_build_partition_plan_merges_adjacent_units_without_splitting(self) -> None:
        plan = source_partition.build_partition_plan(self.source_corpus(), self.policy())
        self.assertEqual(
            [item["source_unit_ids"] for item in plan["partitions"]],
            [["SU001", "SU002"], ["SU003"]],
        )
        self.assertEqual(plan["partitions"][0]["next_partition_id"], "SP002")
        self.assertEqual(plan["partitions"][1]["previous_partition_id"], "SP001")

    def test_validate_partition_plan_rejects_overlap_and_omission(self) -> None:
        plan = source_partition.build_partition_plan(self.source_corpus(), self.policy())
        plan["partitions"][1]["source_unit_ids"] = ["SU002"]
        codes = {
            item["code"]
            for item in source_partition.validate_partition_plan(
                plan, self.source_corpus()
            )
        }
        self.assertIn("partition_source_unit_duplicate", codes)
        self.assertIn("partition_source_unit_missing", codes)

    def test_oversized_semantic_unit_is_rejected_not_arbitrarily_split(self) -> None:
        corpus = self.source_corpus()
        corpus["source_units"][0]["estimated_tokens"] = 7000
        with self.assertRaisesRegex(
            source_partition.PartitionError, "partition_unit_over_budget"
        ):
            source_partition.build_partition_plan(corpus, self.policy())

    def test_missing_metrics_are_rejected(self) -> None:
        corpus = self.source_corpus()
        corpus["source_units"][0].pop("estimated_tokens")
        with self.assertRaisesRegex(
            source_partition.PartitionError, "partition_unit_metrics_missing"
        ):
            source_partition.build_partition_plan(corpus, self.policy())

    def test_merge_rejects_missing_partition_and_duplicate_event_id(self) -> None:
        plan = source_partition.build_partition_plan(self.source_corpus(), self.policy())
        shards = [
            {
                "schema_version": 1,
                "partition_id": "SP001",
                "source_unit_ids": ["SU001", "SU002"],
                "units": [
                    {
                        "source_unit_id": "SU001",
                        "status": "ready",
                        "events": [{"event_id": "EV001"}],
                    },
                    {
                        "source_unit_id": "SU002",
                        "status": "ready",
                        "events": [{"event_id": "EV001"}],
                    },
                ],
            }
        ]
        codes = {
            item["code"]
            for item in source_partition.validate_analysis_shards(plan, shards)
        }
        self.assertIn("analysis_shard_partition_missing", codes)
        self.assertIn("analysis_shard_event_duplicate", codes)

    def test_merge_orders_units_by_partition_and_source_order(self) -> None:
        plan = source_partition.build_partition_plan(self.source_corpus(), self.policy())
        shards = [
            {
                "schema_version": 1,
                "partition_id": "SP002",
                "source_unit_ids": ["SU003"],
                "units": [
                    {"source_unit_id": "SU003", "status": "ready", "events": []}
                ],
            },
            {
                "schema_version": 1,
                "partition_id": "SP001",
                "source_unit_ids": ["SU001", "SU002"],
                "units": [
                    {"source_unit_id": "SU001", "status": "ready", "events": []},
                    {"source_unit_id": "SU002", "status": "ready", "events": []},
                ],
            },
        ]
        merged = source_partition.merge_analysis_shards(plan, shards)
        self.assertEqual(
            [unit["source_unit_id"] for unit in merged["units"]],
            ["SU001", "SU002", "SU003"],
        )

    def rolling_corpus(self) -> dict:
        corpus = self.source_corpus()
        for index, unit in enumerate(corpus["source_units"], 1):
            unit["content_sha256"] = f"hash-{index}"
        return corpus

    def test_rolling_plan_reuses_carryover_and_only_schedules_unanalyzed_units(self) -> None:
        registry = {
            "schema_version": 1,
            "records": [
                {
                    "source_unit_id": "SU001",
                    "content_sha256": "hash-1",
                    "analysis_contract_version": 1,
                    "analysis_status": "analyzed",
                    "analysis_path": "tmp/SU001.json",
                    "analysis_sha256": "analysis-1",
                    "idempotency_key": "SU001:hash-1:v1",
                }
            ],
        }
        progress = {
            "schema_version": 2,
            "current_batch_id": "B02",
            "completed_window_count": 1,
            "batch_readiness": "needs_more_source",
            "source_gap_reasons": ["B02仍缺少后续冲突结果"],
            "carryover_event_ids": ["EV-OLD-1"],
            "event_consumption": {"EV-OLD-1": "unconsumed"},
            "next_read_start": "SU002",
        }
        plan = source_partition.build_rolling_source_plan(
            self.rolling_corpus(), registry, progress, window_size=2
        )
        self.assertEqual(plan["carryover_event_ids"], ["EV-OLD-1"])
        self.assertEqual(plan["reusable_analyzed_source_unit_ids"], ["SU001"])
        self.assertEqual(plan["new_analysis_source_unit_ids"], ["SU002", "SU003"])

    def test_rolling_plan_rejects_analyzed_units_before_initial_checkpoint(self) -> None:
        registry = {
            "schema_version": 1,
            "records": [
                {
                    "source_unit_id": "SU001",
                    "content_sha256": "hash-1",
                    "analysis_contract_version": 1,
                    "analysis_status": "analyzed",
                    "analysis_path": "tmp/SU001.json",
                    "analysis_sha256": "analysis-1",
                    "idempotency_key": "SU001:hash-1:v1",
                }
            ],
        }
        progress = {
            "schema_version": 2,
            "current_batch_id": "B01",
            "completed_window_count": 0,
            "batch_readiness": "initial_window",
            "source_gap_reasons": [],
            "carryover_event_ids": [],
            "event_consumption": {},
            "next_read_start": "SU001",
        }
        with self.assertRaisesRegex(
            source_partition.PartitionError, "rolling_window_checkpoint_required"
        ):
            source_partition.build_rolling_source_plan(
                self.rolling_corpus(), registry, progress, window_size=2
            )

    def test_rolling_progress_rejects_analysis_window_id_as_batch_id(self) -> None:
        errors = source_partition.validate_rolling_source_progress(
            {
                "schema_version": 2,
                "current_batch_id": "SA02",
                "completed_window_count": 1,
                "batch_readiness": "needs_more_source",
                "source_gap_reasons": ["当前事件尚未形成B01所需的完整转折"],
                "carryover_event_ids": [],
                "event_consumption": {},
                "next_read_start": "SU002",
            }
        )
        self.assertIn(
            "rolling_progress_batch_invalid",
            {item["code"] for item in errors},
        )

    def test_rolling_progress_v2_enforces_batch_readiness_invariants(self) -> None:
        cases = (
            (
                {
                    "schema_version": 2,
                    "current_batch_id": "B01",
                    "completed_window_count": 0,
                    "batch_readiness": "needs_more_source",
                    "source_gap_reasons": [],
                    "carryover_event_ids": [],
                    "event_consumption": {},
                    "next_read_start": "SU001",
                },
                "rolling_progress_readiness_invalid",
            ),
            (
                {
                    "schema_version": 2,
                    "current_batch_id": "B01",
                    "completed_window_count": 1,
                    "batch_readiness": "ready_for_batch",
                    "source_gap_reasons": [],
                    "carryover_event_ids": [],
                    "event_consumption": {},
                    "next_read_start": "SU002",
                },
                "rolling_progress_ready_next_read_conflict",
            ),
            (
                {
                    "schema_version": 2,
                    "current_batch_id": "B01",
                    "completed_window_count": 1,
                    "batch_readiness": "needs_more_source",
                    "source_gap_reasons": [],
                    "carryover_event_ids": [],
                    "event_consumption": {},
                    "next_read_start": "SU002",
                },
                "rolling_progress_source_gap_missing",
            ),
        )
        for payload, expected_code in cases:
            with self.subTest(expected_code=expected_code):
                errors = source_partition.validate_rolling_source_progress(payload)
                self.assertIn(expected_code, {item["code"] for item in errors})

    def test_rolling_plan_stops_when_current_batch_is_ready(self) -> None:
        registry = {
            "schema_version": 1,
            "records": [
                {
                    "source_unit_id": "SU001",
                    "content_sha256": "hash-1",
                    "analysis_contract_version": 1,
                    "analysis_status": "analyzed",
                    "analysis_path": "tmp/SU001.json",
                    "analysis_sha256": "analysis-1",
                    "idempotency_key": "SU001:hash-1:v1",
                }
            ],
        }
        progress = {
            "schema_version": 2,
            "current_batch_id": "B01",
            "completed_window_count": 1,
            "batch_readiness": "ready_for_batch",
            "source_gap_reasons": [],
            "carryover_event_ids": [],
            "event_consumption": {},
            "next_read_start": None,
        }
        with self.assertRaisesRegex(
            source_partition.PartitionError, "rolling_batch_ready_for_delivery"
        ):
            source_partition.build_rolling_source_plan(
                self.rolling_corpus(), registry, progress, window_size=2
            )

    def test_rolling_plan_allows_next_window_only_with_source_gap(self) -> None:
        registry = {
            "schema_version": 1,
            "records": [
                {
                    "source_unit_id": "SU001",
                    "content_sha256": "hash-1",
                    "analysis_contract_version": 1,
                    "analysis_status": "analyzed",
                    "analysis_path": "tmp/SU001.json",
                    "analysis_sha256": "analysis-1",
                    "idempotency_key": "SU001:hash-1:v1",
                }
            ],
        }
        progress = {
            "schema_version": 2,
            "current_batch_id": "B01",
            "completed_window_count": 1,
            "batch_readiness": "needs_more_source",
            "source_gap_reasons": ["现有事件只够支撑E001，E002-E003仍缺少完整冲突结果"],
            "carryover_event_ids": ["EV-OLD-1"],
            "event_consumption": {"EV-OLD-1": "partially_consumed"},
            "next_read_start": "SU002",
        }
        plan = source_partition.build_rolling_source_plan(
            self.rolling_corpus(), registry, progress, window_size=2
        )
        self.assertEqual(plan["new_analysis_source_unit_ids"], ["SU002", "SU003"])
        self.assertEqual(plan["planned_window_number"], 2)
        self.assertTrue(plan["checkpoint_required_after_window"])
        self.assertEqual(plan["source_gap_reasons"], progress["source_gap_reasons"])

    def test_record_chapter_analysis_rejects_same_unit_hash_and_contract_twice(self) -> None:
        registry = {"schema_version": 1, "records": []}
        first = source_partition.record_chapter_analysis(
            registry,
            source_unit_id="SU001",
            content_sha256="hash-1",
            analysis_contract_version=1,
            analysis_path="tmp/SU001.json",
            analysis_sha256="analysis-1",
        )
        with self.assertRaisesRegex(
            source_partition.PartitionError, "source_unit_reanalysis_forbidden"
        ):
            source_partition.record_chapter_analysis(
                first,
                source_unit_id="SU001",
                content_sha256="hash-1",
                analysis_contract_version=1,
                analysis_path="tmp/SU001-retry.json",
                analysis_sha256="analysis-2",
            )

    def test_registry_validation_detects_hash_and_idempotency_conflicts(self) -> None:
        registry = {
            "schema_version": 1,
            "records": [
                {
                    "source_unit_id": "SU001",
                    "content_sha256": "hash-1",
                    "analysis_contract_version": 1,
                    "analysis_status": "analyzed",
                    "analysis_path": "tmp/SU001.json",
                    "analysis_sha256": "analysis-1",
                    "idempotency_key": "wrong",
                },
                {
                    "source_unit_id": "SU001",
                    "content_sha256": "hash-1",
                    "analysis_contract_version": 1,
                    "analysis_status": "analyzed",
                    "analysis_path": "tmp/SU001-duplicate.json",
                    "analysis_sha256": "analysis-2",
                    "idempotency_key": "SU001:hash-1:v1",
                },
            ],
        }
        codes = {
            item["code"]
            for item in source_partition.validate_chapter_analysis_registry(registry)
        }
        self.assertIn("analysis_registry_hash_mismatch", codes)
        self.assertIn("source_analysis_idempotency_conflict", codes)

    def test_rolling_progress_rejects_unknown_consumption_status(self) -> None:
        errors = source_partition.validate_rolling_source_progress(
            {
                "schema_version": 1,
                "current_batch_id": "B01",
                "carryover_event_ids": ["EV001"],
                "event_consumption": {"EV001": "mystery"},
                "next_read_start": "SU002",
            }
        )
        self.assertIn(
            "rolling_progress_consumption_status_invalid",
            {item["code"] for item in errors},
        )


if __name__ == "__main__":
    unittest.main()
