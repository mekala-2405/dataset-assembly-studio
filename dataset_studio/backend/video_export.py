from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Callable, Protocol, TypeAlias


class CancellationEvent(Protocol):
    def is_set(self) -> bool: ...


CancelHook: TypeAlias = Callable[[], bool] | CancellationEvent
ProgressHook: TypeAlias = Callable[[int, int], None]


class VideoExportError(RuntimeError):
    """Raised when a source segment cannot be normalized."""


class VideoExportCancelled(VideoExportError):
    """Raised when cooperative cancellation interrupts normalization."""


@dataclass(frozen=True)
class VideoExportResult:
    destination: Path
    frame_count: int
    fps: int
    width: int
    height: int
    duration: float


def _is_cancelled(cancel: CancelHook | None) -> bool:
    if cancel is None:
        return False
    is_set = getattr(cancel, "is_set", None)
    if callable(is_set):
        return bool(is_set())
    if callable(cancel):
        return bool(cancel())
    raise TypeError("cancel must be callable or provide is_set()")


def _raise_if_cancelled(cancel: CancelHook | None) -> None:
    if _is_cancelled(cancel):
        raise VideoExportCancelled("video normalization cancelled")


def _letterbox(frame, size: tuple[int, int]):
    import av
    import numpy as np

    output_width, output_height = size
    scale = min(output_width / frame.width, output_height / frame.height)
    scaled_width = max(1, min(output_width, round(frame.width * scale)))
    scaled_height = max(1, min(output_height, round(frame.height * scale)))
    resized = frame.reformat(width=scaled_width, height=scaled_height, format="rgb24")

    canvas = np.zeros((output_height, output_width, 3), dtype=np.uint8)
    left = (output_width - scaled_width) // 2
    top = (output_height - scaled_height) // 2
    canvas[top : top + scaled_height, left : left + scaled_width] = resized.to_ndarray()
    return av.VideoFrame.from_ndarray(canvas, format="rgb24")


def normalize_episode_video(
    source: str | Path,
    start: float,
    duration: float,
    destination: str | Path,
    fps: int = 30,
    size: tuple[int, int] = (640, 480),
    cancel: CancelHook | None = None,
    progress: ProgressHook | None = None,
    preset: str = "veryfast",
    crf: int = 20,
) -> VideoExportResult:
    """Normalize one source-video interval to a fixed LeRobot camera stream.

    ``cancel`` may be a zero-argument predicate or a threading-style event.
    ``progress`` receives ``(completed_frames, total_frames)`` after each frame
    is accepted by the encoder.
    """

    import av

    source_path = Path(source)
    destination_path = Path(destination)
    width, height = size
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    if duration <= 0:
        raise ValueError("duration must be greater than zero")
    if start < 0:
        raise ValueError("start must not be negative")
    if fps <= 0:
        raise ValueError("fps must be greater than zero")
    if width <= 0 or height <= 0:
        raise ValueError("size dimensions must be greater than zero")
    if not preset:
        raise ValueError("preset must not be empty")
    if not 0 <= crf <= 51:
        raise ValueError("crf must be between 0 and 51")
    if source_path.resolve() == destination_path.resolve():
        raise ValueError("source and destination must be different files")

    total_frames = max(1, round(duration * fps))
    output_time_base = Fraction(1, fps)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    _raise_if_cancelled(cancel)

    completed = 0
    try:
        with av.open(str(source_path)) as input_container:
            if not input_container.streams.video:
                raise VideoExportError(f"source has no video stream: {source_path}")
            input_stream = input_container.streams.video[0]
            if input_stream.time_base:
                seek_pts = int(start / float(input_stream.time_base))
                input_container.seek(max(0, seek_pts), stream=input_stream, backward=True)

            with av.open(str(destination_path), mode="w") as output_container:
                output_stream = output_container.add_stream("libx264", rate=fps)
                output_stream.width = width
                output_stream.height = height
                output_stream.pix_fmt = "yuv420p"
                output_stream.options = {"preset": preset, "crf": str(crf)}

                previous_frame = None
                previous_time = None
                output_index = 0

                for current_frame in input_container.decode(input_stream):
                    _raise_if_cancelled(cancel)
                    if current_frame.time is None:
                        continue
                    current_time = float(current_frame.time)
                    target_time = start + output_index / fps

                    if previous_frame is None:
                        previous_frame = current_frame
                        previous_time = current_time

                    if current_time < target_time:
                        previous_frame = current_frame
                        previous_time = current_time
                        continue

                    while output_index < total_frames:
                        target_time = start + output_index / fps
                        if target_time > current_time:
                            break
                        _raise_if_cancelled(cancel)
                        if (
                            previous_time is not None
                            and abs(target_time - previous_time) <= abs(current_time - target_time)
                        ):
                            selected_frame = previous_frame
                        else:
                            selected_frame = current_frame
                        output_frame = _letterbox(selected_frame, size)
                        output_frame.pts = output_index
                        output_frame.time_base = output_time_base
                        for packet in output_stream.encode(output_frame):
                            output_container.mux(packet)
                        output_index += 1
                        completed = output_index
                        if progress is not None:
                            progress(completed, total_frames)

                    previous_frame = current_frame
                    previous_time = current_time
                    if output_index >= total_frames:
                        break

                if previous_frame is None:
                    raise VideoExportError(f"source contains no decodable video frames: {source_path}")

                while output_index < total_frames:
                    _raise_if_cancelled(cancel)
                    output_frame = _letterbox(previous_frame, size)
                    output_frame.pts = output_index
                    output_frame.time_base = output_time_base
                    for packet in output_stream.encode(output_frame):
                        output_container.mux(packet)
                    output_index += 1
                    completed = output_index
                    if progress is not None:
                        progress(completed, total_frames)

                for packet in output_stream.encode():
                    output_container.mux(packet)
    except Exception:
        destination_path.unlink(missing_ok=True)
        raise

    return VideoExportResult(
        destination=destination_path,
        frame_count=completed,
        fps=fps,
        width=width,
        height=height,
        duration=completed / fps,
    )
