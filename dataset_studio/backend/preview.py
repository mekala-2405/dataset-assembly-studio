from __future__ import annotations

from functools import lru_cache
from io import BytesIO


def choose_thumbnail_camera(cameras: list[str], available: set[str]) -> str | None:
    candidates = [camera for camera in cameras if camera in available and "wrist" not in camera.lower()]
    for marker in ("desk_view", "top", "front"):
        match = next((camera for camera in candidates if marker in camera.lower()), None)
        if match:
            return match
    return candidates[0] if candidates else None


@lru_cache(maxsize=512)
def thumbnail_jpeg(video_path: str, timestamp: float) -> bytes:
    import av

    with av.open(video_path) as container:
        stream = container.streams.video[0]
        if stream.time_base:
            container.seek(int(max(timestamp, 0) / float(stream.time_base)), stream=stream, backward=True)
        frame = next(container.decode(stream))
        image = frame.to_image()
        image.thumbnail((360, 240))
        output = BytesIO()
        image.save(output, format="JPEG", quality=78)
        return output.getvalue()
