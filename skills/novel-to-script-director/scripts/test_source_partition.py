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


if __name__ == "__main__":
    unittest.main()
