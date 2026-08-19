import unittest
from datetime import datetime, timedelta

from recommendation_engine import rank_recommendations, record_impressions


CATALOG = {
    "sos": {"name": "情绪急救", "kw": ["难过", "情绪急救"]},
    "planner": {"name": "许墨计划", "kw": ["计划", "工作"]},
    "words": {"name": "背单词", "kw": ["单词", "学习"]},
    "listen": {"name": "一起听", "kw": ["音乐", "听歌"]},
    "world": {"name": "世界", "kw": ["世界", "散步"]},
    "moments": {"name": "朋友圈", "kw": ["朋友圈", "动态"]},
}


class RecommendationEngineTests(unittest.TestCase):
    def test_explicit_intent_wins_and_has_reason(self):
        items = rank_recommendations(CATALOG, user_text="我今天想背单词", now=datetime(2026, 8, 20, 10))
        self.assertEqual(items[0]["key"], "words")
        self.assertIn("刚才", items[0]["reason"])

    def test_negative_feedback_suppresses_app(self):
        behavior = {"feedback": {"planner": {"dislikes": 4}}}
        items = rank_recommendations(CATALOG, behavior, user_text="我想安排工作计划", now=datetime(2026, 8, 20, 10))
        self.assertNotEqual(items[0]["key"], "planner")

    def test_results_are_diverse_by_domain(self):
        items = rank_recommendations(CATALOG, surface="recbar", limit=4, now=datetime(2026, 8, 20, 20))
        domains = [item["domain"] for item in items]
        self.assertGreaterEqual(len(set(domains)), 3)

    def test_recent_impression_adds_cooldown(self):
        now = datetime(2026, 8, 20, 20)
        behavior = {"recommendation_history": [{"app": "listen", "surface": "recbar", "time": (now - timedelta(hours=1)).isoformat()}]}
        items = rank_recommendations(CATALOG, behavior, surface="recbar", limit=4, now=now)
        self.assertNotEqual(items[0]["key"], "listen")

    def test_impressions_are_deduplicated_for_30_minutes(self):
        now = datetime(2026, 8, 20, 20)
        behavior = {}
        record_impressions(behavior, [{"app": "world"}], "recbar", now)
        record_impressions(behavior, [{"app": "world"}], "recbar", now + timedelta(minutes=10))
        self.assertEqual(len(behavior["recommendation_history"]), 1)


if __name__ == "__main__":
    unittest.main()
