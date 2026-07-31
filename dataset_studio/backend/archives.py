from __future__ import annotations

import os
import tarfile
from pathlib import Path
from typing import Callable


def create_export_archive(
    source: Path,
    destination: Path,
    cancel: Callable[[], bool] | None = None,
) -> Path:
    source = Path(source)
    destination = Path(destination)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    if not source.is_dir():
        raise FileNotFoundError(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary.unlink(missing_ok=True)
    try:
        if cancel and cancel():
            raise RuntimeError("archive creation cancelled")
        with tarfile.open(temporary, "w:gz") as archive:
            archive.add(
                source,
                arcname=source.name,
                recursive=True,
                filter=(lambda info: None if cancel and cancel() else info),
            )
        if cancel and cancel():
            raise RuntimeError("archive creation cancelled")
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return destination
