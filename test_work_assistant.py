import asyncio
import unittest

import life_apps


class FakeRequest:
    def __init__(self, body):
        self.body = body

    async def json(self):
        return self.body


class WorkAssistantTests(unittest.TestCase):
    def setUp(self):
        self.work = {
            "sessions": [{
                "id": "session-1",
                "title": "测试资料批次",
                "created_ts": "2026-08-20 10:00",
                "finished": False,
                "thanks": "",
                "docs": [
                    {"id": "doc-1", "title": "实验数据", "type": "data", "note": "A", "status": "unsorted", "category": "", "summary": ""},
                    {"id": "doc-2", "title": "会议纪要", "type": "meeting", "note": "B", "status": "unsorted", "category": "", "summary": ""},
                ],
            }]
        }
        self.stats = {"total_sorted": 3, "total_sessions": 0}
        self.originals = {
            "load": life_apps._load,
            "save": life_apps._save,
            "affinity": life_apps._add_affinity,
        }

        def fake_load(path, _default):
            return self.stats if path == life_apps.WORK_STATS_FILE else self.work

        def fake_save(path, data):
            if path == life_apps.WORK_STATS_FILE:
                self.stats = data
            else:
                self.work = data

        life_apps._load = fake_load
        life_apps._save = fake_save
        life_apps._add_affinity = lambda *_args, **_kwargs: {"delta": 2, "level_name": "默契"}

    def tearDown(self):
        life_apps._load = self.originals["load"]
        life_apps._save = self.originals["save"]
        life_apps._add_affinity = self.originals["affinity"]

    def run_async(self, coroutine):
        return asyncio.run(coroutine)

    def test_auto_sort_uses_suggested_categories_and_updates_stats(self):
        result = self.run_async(life_apps.work_auto_sort())

        self.assertEqual(result["sorted_count"], 2)
        self.assertEqual(self.stats["total_sorted"], 5)
        self.assertEqual(self.work["sessions"][0]["docs"][0]["category"], "data")
        self.assertEqual(self.work["sessions"][0]["docs"][1]["category"], "meeting")

    def test_stats_endpoint_exposes_dashboard_total(self):
        result = self.run_async(life_apps.work_stats())

        self.assertEqual(result["total_sorted"], 3)
        self.assertEqual(result["total_docs"], 3)
        self.assertEqual(result["total_sessions"], 0)

    def test_reclassifying_does_not_double_count(self):
        self.run_async(life_apps.work_doc_sort("doc-1", FakeRequest({"category": "data"})))
        first_total = self.stats["total_sorted"]
        result = self.run_async(life_apps.work_doc_sort("doc-1", FakeRequest({"category": "paper"})))

        self.assertTrue(result["reclassified"])
        self.assertEqual(self.work["sessions"][0]["docs"][0]["category"], "paper")
        self.assertEqual(self.stats["total_sorted"], first_total)

    def test_same_category_is_idempotent(self):
        self.run_async(life_apps.work_doc_sort("doc-1", FakeRequest({"category": "data"})))
        first_total = self.stats["total_sorted"]
        result = self.run_async(life_apps.work_doc_sort("doc-1", FakeRequest({"category": "data"})))

        self.assertTrue(result["unchanged"])
        self.assertEqual(self.stats["total_sorted"], first_total)


if __name__ == "__main__":
    unittest.main()
