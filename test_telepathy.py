import asyncio
import unittest
from unittest.mock import patch

import nova_apps2


class JsonRequest:
    def __init__(self, payload):
        self.payload = payload

    async def json(self):
        return self.payload


class TelepathyTests(unittest.TestCase):
    def test_start_has_five_fallback_questions(self):
        saved = {}

        async def no_model_result(*_args, **_kwargs):
            return {}

        with patch.multiple(
            nova_apps2,
            _llm_json=no_model_result,
            _load=lambda *_args: {"rounds": [], "total_score": 0, "total_rounds": 0},
            _save=lambda _path, data: saved.update(data),
            _agg_memories=lambda *_args: [],
            _agg_player=lambda: {},
            _agg_affinity_value=lambda: 0,
        ):
            result = asyncio.run(nova_apps2.telepathy_start())

        self.assertEqual(len(result["round"]["questions"]), 5)
        self.assertEqual(saved["rounds"][0]["id"], result["round"]["id"])

    def test_guess_normalizes_invalid_model_guesses(self):
        questions = [
            {"q": f"Q{i}", "options": ["A", "B", "C", "D"]}
            for i in range(5)
        ]
        round_data = {
            "id": "round-1",
            "questions": questions,
            "answers": [],
            "guesses": [],
            "finished": False,
        }
        data = {"rounds": [round_data], "total_score": 0, "total_rounds": 0}

        async def invalid_guesses(*_args, **_kwargs):
            return {"guesses": ["1", 9, None], "comment": "测试"}

        with patch.multiple(
            nova_apps2,
            _llm_json=invalid_guesses,
            _load=lambda *_args: data,
            _save=lambda *_args: None,
            _agg_memories=lambda *_args: [],
            _agg_player=lambda: {},
            _agg_affinity_value=lambda: 0,
            _affinity=lambda *_args: None,
        ):
            result = asyncio.run(
                nova_apps2.telepathy_guess(
                    JsonRequest({"id": "round-1", "answers": [1, 0, 0, 0, 0]})
                )
            )

        self.assertEqual(result["round"]["guesses"], [1, 0, 0, 0, 0])
        self.assertEqual(result["round"]["score"], 100)


if __name__ == "__main__":
    unittest.main()
