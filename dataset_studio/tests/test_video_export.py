from __future__ import annotations

import tempfile
import unittest
import inspect
from fractions import Fraction
from pathlib import Path
from threading import Event

import av
import numpy as np

from backend.video_export import VideoExportCancelled, normalize_episode_video


def _write_source_video(path: Path, *, fps: int = 15, seconds: int = 2) -> None:
    with av.open(str(path), mode="w") as container:
        stream = container.add_stream("libx264", rate=fps)
        stream.width = 320
        stream.height = 180
        stream.pix_fmt = "yuv420p"

        for index in range(fps * seconds):
            pixels = np.zeros((180, 320, 3), dtype=np.uint8)
            pixels[:, :, 0] = 220
            pixels[:, :, 1] = 40 + (index % 20)
            frame = av.VideoFrame.from_ndarray(pixels, format="rgb24")
            frame.pts = index
            frame.time_base = Fraction(1, fps)
            for packet in stream.encode(frame):
                container.mux(packet)

        for packet in stream.encode():
            container.mux(packet)


class VideoExportTests(unittest.TestCase):
    def test_uses_fast_balanced_encoder_defaults(self):
        parameters = inspect.signature(normalize_episode_video).parameters
        self.assertEqual(parameters["preset"].default, "veryfast")
        self.assertEqual(parameters["crf"].default, 20)

    def test_normalizes_timing_geometry_pixel_format_and_letterboxes(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.mp4"
            destination = Path(tmp) / "normalized.mp4"
            _write_source_video(source)

            result = normalize_episode_video(
                source,
                start=0.4,
                duration=1.0,
                destination=destination,
            )

            self.assertTrue(destination.exists())
            with av.open(str(destination)) as container:
                stream = container.streams.video[0]
                frames = list(container.decode(stream))

            self.assertEqual(Fraction(stream.average_rate), Fraction(30, 1))
            self.assertEqual((stream.width, stream.height), (640, 480))
            self.assertEqual(frames[0].format.name, "yuv420p")
            self.assertEqual(len(frames), 30)
            self.assertAlmostEqual(len(frames) / float(stream.average_rate), 1.0, places=3)

            pixels = frames[0].to_ndarray(format="rgb24")
            self.assertLess(float(pixels[20:40].mean()), 15.0)
            self.assertGreater(float(pixels[220:260, 200:440, 0].mean()), 150.0)
            self.assertGreater(float(pixels[220:260, 200:440, 1].mean()), 43.0)

            self.assertEqual(result.frame_count, 30)
            self.assertEqual(result.destination, destination)

    def test_reports_completed_and_total_frames_during_encoding(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.mp4"
            destination = Path(tmp) / "normalized.mp4"
            _write_source_video(source)
            updates: list[tuple[int, int]] = []

            normalize_episode_video(
                source,
                start=0,
                duration=0.2,
                destination=destination,
                progress=lambda completed, total: updates.append((completed, total)),
            )

            self.assertEqual(updates, [(1, 6), (2, 6), (3, 6), (4, 6), (5, 6), (6, 6)])

    def test_cancellation_stops_encoding_and_removes_partial_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.mp4"
            destination = Path(tmp) / "normalized.mp4"
            _write_source_video(source)
            cancelled = Event()

            def request_cancel(completed: int, _total: int) -> None:
                if completed == 3:
                    cancelled.set()

            with self.assertRaises(VideoExportCancelled):
                normalize_episode_video(
                    source,
                    start=0,
                    duration=1.0,
                    destination=destination,
                    cancel=cancelled,
                    progress=request_cancel,
                )

            self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
