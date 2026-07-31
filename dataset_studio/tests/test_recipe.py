import unittest

from backend.catalog import Dataset, Episode, Task
from backend.recipe import EpisodeChoice, validate_and_balance


def catalog():
    return [
        Dataset(
            path="/datasets/a",
            name="a",
            version="v2.1",
            fps=30,
            cameras=["observation.images.wrist", "observation.images.top"],
            tasks=[Task(0, "Original")],
            episodes=[Episode(0, 0, 3.0), Episode(1, 0, 1.5, "shorter than 2 seconds")],
        )
    ]


class RecipeTests(unittest.TestCase):
    def test_rejects_short_episode_and_missing_required_camera_mapping(self):
        choices = [EpisodeChoice("/datasets/a", 1, "Edited task")]

        result = validate_and_balance(
            catalog(), choices, {"/datasets/a": {"observation.images.wrist": "wrist"}}, ["wrist", "top"], None
        )

        self.assertFalse(result.ok)
        self.assertIn("shorter than 2 seconds", result.errors[0])
        self.assertTrue(any("top" in error for error in result.errors))

    def test_uses_edited_prompts_and_deterministically_balances_tasks(self):
        choices = [
            EpisodeChoice("/datasets/a", 0, "Task A"),
            EpisodeChoice("/datasets/a", 0, "Task A"),
            EpisodeChoice("/datasets/a", 0, "Task B"),
        ]

        result = validate_and_balance(
            catalog(), choices,
            {"/datasets/a": {"observation.images.wrist": "wrist", "observation.images.top": "top"}},
            ["wrist", "top"], 1,
        )

        self.assertTrue(result.ok)
        self.assertEqual([choice.final_prompt for choice in result.choices], ["Task A", "Task B"])
        self.assertEqual(result.task_counts, {"Task A": 1, "Task B": 1})


if __name__ == "__main__":
    unittest.main()
