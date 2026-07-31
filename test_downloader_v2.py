import importlib.util
import sys
import types
import unittest
from pathlib import Path


SOURCE = Path(__file__).with_name("downloader_v2.py")


def load_downloader():
    hub = types.ModuleType("huggingface_hub")
    hub.HfApi = object
    hub.snapshot_download = lambda **_kwargs: None
    previous = sys.modules.get("huggingface_hub")
    sys.modules["huggingface_hub"] = hub
    try:
        spec = importlib.util.spec_from_file_location("downloader_v2_under_test", SOURCE)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        if previous is None:
            sys.modules.pop("huggingface_hub", None)
        else:
            sys.modules["huggingface_hub"] = previous


class FakeResponse:
    def __init__(self, status_code, headers=None):
        self.status_code = status_code
        self.headers = headers or {}


class FakeHttpError(Exception):
    def __init__(self, status_code, headers=None):
        self.response = FakeResponse(status_code, headers)


class DownloaderRetryTests(unittest.TestCase):
    def test_429_honors_retry_after_and_adds_jitter(self):
        downloader = load_downloader()

        delay = downloader.retry_delay_seconds(
            FakeHttpError(429, {"Retry-After": "120"}),
            attempt=1,
            jitter_seconds=lambda _upper: 5.0,
        )

        self.assertEqual(delay, 125.0)

    def test_429_without_header_waits_for_full_quota_window(self):
        downloader = load_downloader()

        delay = downloader.retry_delay_seconds(
            FakeHttpError(429),
            attempt=1,
            jitter_seconds=lambda _upper: 0.0,
        )

        self.assertEqual(delay, 300.0)

    def test_downloads_are_single_flight(self):
        downloader = load_downloader()

        self.assertEqual(downloader.DATASET_WORKERS, 1)
        self.assertEqual(downloader.FILE_WORKERS, 1)

    def test_explicit_repositories_allow_resuming_only_failed_downloads(self):
        downloader = load_downloader()

        selected = downloader.select_datasets(["5hadytru/so101_IF_6"])

        self.assertEqual(selected, ["5hadytru/so101_IF_6"])


if __name__ == "__main__":
    unittest.main()
