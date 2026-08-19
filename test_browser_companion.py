import asyncio
import unittest

import features


class FakeRequest:
    def __init__(self, body):
        self.body = body

    async def json(self):
        return self.body


class BrowserCompanionTests(unittest.TestCase):
    def setUp(self):
        self.original_llm = features._call_llm
        self.original_affinity = features._add_affinity
        self.calls = []

        async def fake_llm(messages, max_tokens=None):
            self.calls.append((messages, max_tokens))
            return "这篇研究提到的记忆窗口很有意思。慢慢看，我在这里。"

        features._call_llm = fake_llm
        features._add_affinity = lambda action, detail="": {"action": action, "detail": detail}

    def tearDown(self):
        features._call_llm = self.original_llm
        features._add_affinity = self.original_affinity

    def run_async(self, coroutine):
        return asyncio.run(coroutine)

    def test_open_page_passes_visible_context_and_adds_affinity(self):
        result = self.run_async(features.browser_companion(FakeRequest({
            "event": "open",
            "title": "记忆编码机制",
            "section": "科学版",
            "summary": "研究讨论了海马体与长期记忆形成。",
        })))

        self.assertIn("慢慢看", result["reply"])
        self.assertEqual(result["affinity"]["action"], "watch")
        user_context = self.calls[0][0][-1]["content"]
        self.assertIn("记忆编码机制", user_context)
        self.assertIn("海马体", user_context)
        self.assertIn("刚打开这个页面", user_context)

    def test_message_keeps_recent_valid_history_only(self):
        history = [
            {"role": "user", "content": f"消息{i}"} for i in range(8)
        ] + [{"role": "system", "content": "不应透传"}]
        self.run_async(features.browser_companion(FakeRequest({
            "event": "message",
            "title": "论文库",
            "message": "你觉得这段可信吗？",
            "history": history,
        })))

        messages = self.calls[0][0]
        history_messages = messages[1:-1]
        self.assertEqual(len(history_messages), 5)
        self.assertNotIn("不应透传", str(messages))
        self.assertIn("你觉得这段可信吗", messages[-1]["content"])


if __name__ == "__main__":
    unittest.main()
