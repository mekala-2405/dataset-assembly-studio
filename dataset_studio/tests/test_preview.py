import unittest

from backend.preview import choose_thumbnail_camera


class PreviewTests(unittest.TestCase):
    def test_prefers_external_view_and_never_uses_wrist(self):
        cameras = ["observation.images.wrist_left", "observation.images.front", "observation.images.desk_view"]
        selected = choose_thumbnail_camera(cameras, set(cameras))
        self.assertEqual(selected, "observation.images.desk_view")

    def test_returns_none_when_only_wrist_is_available(self):
        self.assertIsNone(choose_thumbnail_camera(["observation.images.wrist"], {"observation.images.wrist"}))


if __name__ == "__main__":
    unittest.main()
