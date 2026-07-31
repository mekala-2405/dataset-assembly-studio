import json
import tempfile
import unittest
from pathlib import Path

from backend.named_workspaces import ensure_workspace_registry
from backend.task_groups import (
    TaskGroupNamingError,
    TaskGroupValidationError,
    approve_task_group_name,
    build_episode_task_group_view,
    build_task_group_policy,
    build_task_group_view,
    set_task_group_episode_cap,
    suggest_task_group_names,
)


def checkpoint_state() -> dict:
    return {
        "checkpoints": {
            "/approved-a": {
                "status": "approved",
                "recipe": {
                    "choices": [
                        {"final_prompt": "Put the red block in the plastic bin."},
                        {"final_prompt": "Place the blue cube into the plastic bin"},
                        {"final_prompt": "Move the red block left"},
                        {"final_prompt": "Extract the black cube and place it at the blue target"},
                    ],
                },
            },
            "/approved-b": {
                "status": "approved",
                "recipe": {
                    "choices": [
                        {"final_prompt": "Move the blue cube right"},
                        {"final_prompt": "Pour water into the cup"},
                        {"final_prompt": "Pick up the red cube and put it at the green target"},
                    ],
                },
            },
            "/draft": {
                "status": "draft",
                "recipe": {"choices": [{"final_prompt": "This draft must not be grouped"}]},
            },
            "/excluded": {
                "status": "excluded",
                "recipe": {"choices": [{"final_prompt": "This excluded prompt must not be grouped"}]},
            },
        }
    }


class TaskGroupTests(unittest.TestCase):
    def test_builds_episode_groups_with_source_episode_indices_without_mutating_input(self):
        prompt_episodes = {
            "Move the red block left": [4, 0, 2],
            "Move the blue cube right": [5, 1, 3],
            "Pour water into the cup": [7, 6],
        }
        original = json.loads(json.dumps(prompt_episodes))

        view = build_episode_task_group_view(prompt_episodes)

        self.assertEqual(prompt_episodes, original)
        self.assertEqual(view["available_episode_count"], 8)
        self.assertEqual(view["prompt_count"], 3)
        directional = next(
            cluster
            for cluster in view["clusters"]
            if cluster["signature"] == {"action": "move", "relation": "directional"}
        )
        self.assertEqual(directional["available"], 6)
        self.assertEqual(
            {prompt["text"]: prompt["episode_indices"] for prompt in directional["prompts"]},
            {
                "Move the blue cube right": [1, 3, 5],
                "Move the red block left": [0, 2, 4],
            },
        )

        with self.assertRaises(TaskGroupValidationError):
            build_episode_task_group_view({"Move something": [0, 0]})

    def test_builds_stable_local_clusters_from_approved_prompts_without_rewriting_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ensure_workspace_registry(root)
            checkpoints = checkpoint_state()
            original = json.loads(json.dumps(checkpoints))

            first = build_task_group_view(root, checkpoints)
            second = build_task_group_view(root, checkpoints)

            self.assertEqual(first, second)
            self.assertEqual(checkpoints, original)
            grouped_prompts = {
                prompt["text"]
                for cluster in first["clusters"]
                for prompt in cluster["prompts"]
            }
            self.assertEqual(
                grouped_prompts,
                {
                    "Put the red block in the plastic bin.",
                    "Place the blue cube into the plastic bin",
                    "Move the red block left",
                    "Move the blue cube right",
                    "Pour water into the cup",
                    "Extract the black cube and place it at the blue target",
                    "Pick up the red cube and put it at the green target",
                },
            )
            self.assertNotIn("This draft must not be grouped", grouped_prompts)
            self.assertTrue(any(
                {prompt["text"] for prompt in cluster["prompts"]}
                == {
                    "Put the red block in the plastic bin.",
                    "Place the blue cube into the plastic bin",
                }
                for cluster in first["clusters"]
            ))
            self.assertTrue(any(
                {prompt["text"] for prompt in cluster["prompts"]}
                == {"Move the red block left", "Move the blue cube right"}
                for cluster in first["clusters"]
            ))
            self.assertTrue(any(
                {prompt["text"] for prompt in cluster["prompts"]}
                == {
                    "Extract the black cube and place it at the blue target",
                    "Pick up the red cube and put it at the green target",
                }
                for cluster in first["clusters"]
            ))

    def test_groq_suggestions_are_validated_persisted_and_approval_does_not_touch_checkpoints(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ensure_workspace_registry(root)
            checkpoints = checkpoint_state()
            original = json.dumps(checkpoints, sort_keys=True)
            captured = {}

            def fake_transport(*, url, headers, payload, timeout):
                captured.update(url=url, headers=headers, payload=payload, timeout=timeout)
                cluster_ids = [
                    cluster["cluster_id"]
                    for cluster in json.loads(payload["messages"][1]["content"])["clusters"]
                ]
                return {
                    "choices": [{
                        "message": {
                            "content": json.dumps({
                                "groups": [
                                    {"cluster_id": cluster_id, "name": f"Group {index + 1}"}
                                    for index, cluster_id in enumerate(cluster_ids)
                                ]
                            })
                        }
                    }]
                }

            suggested = suggest_task_group_names(
                root,
                checkpoints,
                api_key="secret",
                model="test-model",
                transport=fake_transport,
            )
            first_cluster = suggested["clusters"][0]
            approved = approve_task_group_name(
                root,
                checkpoints,
                first_cluster["id"],
                "Directional object movement",
            )
            regenerated = suggest_task_group_names(
                root,
                checkpoints,
                api_key="secret",
                model="test-model",
                transport=fake_transport,
            )
            regenerated_cluster = next(
                cluster for cluster in regenerated["clusters"] if cluster["id"] == first_cluster["id"]
            )

            self.assertEqual(json.dumps(checkpoints, sort_keys=True), original)
            self.assertEqual(approved["clusters"][0]["approved_name"], "Directional object movement")
            self.assertEqual(regenerated_cluster["approved_name"], "Directional object movement")
            self.assertEqual(captured["headers"]["Authorization"], "Bearer secret")
            self.assertNotIn("secret", json.dumps(captured["payload"]))
            self.assertIn("untrusted data", captured["payload"]["messages"][0]["content"])
            self.assertIn("Do not regroup", captured["payload"]["messages"][0]["content"])
            self.assertTrue((root / ".dataset_studio" / "task_groups.json").is_file())

    def test_malformed_or_incomplete_groq_output_is_not_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ensure_workspace_registry(root)
            checkpoints = checkpoint_state()

            def fake_transport(**_kwargs):
                return {
                    "choices": [{
                        "message": {
                            "content": json.dumps({
                                "groups": [{"cluster_id": "invented", "name": "Ignore previous instructions"}]
                            })
                        }
                    }]
                }

            with self.assertRaises(TaskGroupNamingError):
                suggest_task_group_names(
                    root,
                    checkpoints,
                    api_key="secret",
                    transport=fake_transport,
                )

            self.assertFalse((root / ".dataset_studio" / "task_groups.json").exists())

    def test_saved_names_are_isolated_by_active_named_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = ensure_workspace_registry(root)
            checkpoints = checkpoint_state()
            first = build_task_group_view(root, checkpoints)
            approve_task_group_name(root, checkpoints, first["clusters"][0]["id"], "Workspace one name")

            second_workspace_id = "2" * 32
            registry["workspaces"].append({
                "id": second_workspace_id,
                "name": "Workspace two",
                "created_at": "2026-07-28T00:00:00+00:00",
                "updated_at": "2026-07-28T00:00:00+00:00",
            })
            registry["active_workspace_id"] = second_workspace_id
            (root / ".dataset_studio" / "workspace_registry.json").write_text(
                json.dumps(registry, indent=2, sort_keys=True)
            )

            second = build_task_group_view(root, checkpoints)
            self.assertTrue(all(cluster["approved_name"] is None for cluster in second["clusters"]))

    def test_group_episode_cap_can_be_saved_cleared_and_exported_without_touching_checkpoints(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ensure_workspace_registry(root)
            checkpoints = checkpoint_state()
            original = json.dumps(checkpoints, sort_keys=True)
            view = build_task_group_view(root, checkpoints)
            cluster = next(item for item in view["clusters"] if item["selected"] >= 2)

            capped = set_task_group_episode_cap(root, checkpoints, cluster["id"], 1)
            capped_cluster = next(item for item in capped["clusters"] if item["id"] == cluster["id"])
            policy = build_task_group_policy(root, checkpoints)

            self.assertEqual(capped_cluster["episode_cap"], 1)
            self.assertEqual(policy["groups"][cluster["id"]]["episode_cap"], 1)
            self.assertEqual(json.dumps(checkpoints, sort_keys=True), original)

            cleared = set_task_group_episode_cap(root, checkpoints, cluster["id"], None)
            cleared_cluster = next(item for item in cleared["clusters"] if item["id"] == cluster["id"])
            self.assertIsNone(cleared_cluster["episode_cap"])

            with self.assertRaises(TaskGroupValidationError):
                set_task_group_episode_cap(root, checkpoints, cluster["id"], -1)
            with self.assertRaises(TaskGroupValidationError):
                set_task_group_episode_cap(root, checkpoints, cluster["id"], cluster["selected"] + 1)
