import asyncio
import unittest

import psyche_apps


class FakeRequest:
    def __init__(self, body):
        self.body = body

    async def json(self):
        return self.body


class CowriteArticleTests(unittest.TestCase):
    def setUp(self):
        self.store = {"articles": []}
        self.originals = {
            "load": psyche_apps._load,
            "save": psyche_apps._save,
            "llm": psyche_apps._llm_json,
            "relation": psyche_apps._touch_relation,
            "affinity": psyche_apps._affinity,
        }
        psyche_apps._load = lambda _path, _default: self.store
        psyche_apps._save = lambda _path, data: setattr(self, "store", data)
        psyche_apps._touch_relation = lambda *_args, **_kwargs: None
        psyche_apps._affinity = lambda *_args, **_kwargs: {}

        async def fake_llm(prompt, _user, max_tokens=700):
            if '"opening"' in prompt:
                return {
                    "title": "雨天的观察",
                    "outline": ["雨落下来", "城市慢下来", "重新看见彼此"],
                    "opening": "雨落下来的时候，城市像被调低了音量。我们站在屋檐下，第一次认真听见彼此没有说完的话。",
                    "note": "我先从一个能被看见的瞬间开始，下一段交给你来决定方向。",
                }
            if '"suggestions"' in prompt:
                return {"suggestions": ["补一处气味细节", "让第二段回应标题", "结尾回到屋檐下"], "note": "最亮的是开头的声音感。"}
            if '"addition"' in prompt:
                return {"addition": "雨水沿着伞骨缓慢聚拢，落在脚边。我们没有急着离开，只让安静替这座城补完另一种答案。", "note": "我把镜头推近了一点。"}
            return {"draft": "雨落下来的时候，整座城市都慢了下来。我们站在屋檐下，听见彼此尚未说完的话。", "note": "我理顺了句子的节奏。"}

        psyche_apps._llm_json = fake_llm

    def tearDown(self):
        psyche_apps._load = self.originals["load"]
        psyche_apps._save = self.originals["save"]
        psyche_apps._llm_json = self.originals["llm"]
        psyche_apps._touch_relation = self.originals["relation"]
        psyche_apps._affinity = self.originals["affinity"]

    def run_async(self, coroutine):
        return asyncio.run(coroutine)

    def test_create_continue_suggest_save_and_finish(self):
        created = self.run_async(psyche_apps.article_create(FakeRequest({
            "topic": "写一场雨里的相遇", "kind": "essay", "tone": "warm"
        })))
        article = created["article"]
        self.assertEqual(article["title"], "雨天的观察")
        self.assertEqual(len(article["outline"]), 3)

        continued = self.run_async(psyche_apps.article_assist(article["id"], FakeRequest({
            "action": "continue", "draft": article["draft"]
        })))
        self.assertTrue(continued["changed"])
        self.assertIn("伞骨", continued["article"]["draft"])

        suggested = self.run_async(psyche_apps.article_assist(article["id"], FakeRequest({
            "action": "suggest", "draft": continued["article"]["draft"]
        })))
        self.assertFalse(suggested["changed"])
        self.assertEqual(len(suggested["article"]["suggestions"]), 3)

        saved = self.run_async(psyche_apps.article_save(article["id"], FakeRequest({
            "title": "新的标题", "draft": suggested["article"]["draft"] + "\n\n这是我补写的一段。"
        })))
        self.assertEqual(saved["article"]["title"], "新的标题")

        finished = self.run_async(psyche_apps.article_finish(article["id"], FakeRequest({
            "draft": saved["article"]["draft"]
        })))
        self.assertEqual(finished["article"]["status"], "finished")

        listing = self.run_async(psyche_apps.article_list())
        self.assertEqual(listing["articles"][0]["title"], "新的标题")
        self.assertGreater(listing["articles"][0]["word_count"], 40)


if __name__ == "__main__":
    unittest.main()
