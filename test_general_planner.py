import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import features


class DummyRequest:
    def __init__(self, body):
        self.body = body

    async def json(self):
        return self.body


class GeneralPlannerTest(unittest.TestCase):
    def test_general_planner_lifecycle(self):
        async def no_llm(*_args, **_kwargs):
            return ""

        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(features, "PLANNER_FILE", Path(tmp) / "general_planner.json"), \
                patch.object(features, "_call_llm", no_llm), \
                patch.object(features, "_add_affinity", lambda *_args, **_kwargs: {"delta": 4}):
            created = asyncio.run(features.planner_generate(DummyRequest({
                "goal": "七天整理完作品集初稿",
                "category": "创作",
                "days": 7,
                "daily_minutes": 60,
                "note": "周三时间少",
            })))
            self.assertEqual(created["plan"]["category"], "创作")
            self.assertEqual(len(created["plan"]["days"]), 7)
            self.assertFalse(created["plan"]["generated"])

            first_day = created["plan"]["days"][0]
            checked = asyncio.run(features.planner_check(DummyRequest({
                "date": first_day["date"], "idx": 0, "done": True,
            })))
            self.assertTrue(checked["plan"]["days"][0]["tasks"][0]["done"])

            adjusted = asyncio.run(features.planner_adjust(DummyRequest({"note": "放慢一点"})))
            self.assertTrue(adjusted["plan"]["days"][0]["tasks"][0]["done"])

            asyncio.run(features.planner_delete())
            self.assertIsNone(asyncio.run(features.planner_get())["plan"])


if __name__ == "__main__":
    unittest.main()
