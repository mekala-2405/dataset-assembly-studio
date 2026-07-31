"""Rate-limit-safe Hugging Face dataset downloader.

Run every configured dataset:
    python3 downloader_v2.py

Resume only failed datasets or download new repositories:
    python3 downloader_v2.py 5hadytru/so101_IF_6 Project-IRA/TPSoSe2026_Dataset_Collection_LeRobot_SO101
"""

import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from random import uniform
from typing import Callable, Sequence

from huggingface_hub import HfApi, snapshot_download


DATASETS = [
    # "youliangtan/so101-table-cleanup",
    # "whosricky/so101-megamix-v1",
    # "Cornito/so101_tea2",
    # "observabot/so101_cloth_folding1",
    # "Cornito/so101_test3",
    # "kangkb7701/so101-vla-datasets",
    # "sreetz-nv/so101-clean-up-vials-into-rack-50_20260628_131121",
    # "sreetz-nv/so101_teleop_vials_rack_left_cosmos_70",
    # "5hadytru/so101_IF_6",
    # "Project-IRA/TPSoSe2026_Dataset_Collection_LeRobot_SO101",
    "UniDataPro/lerobot-so-101-manipulations",
    "ShubhamK32/so101_declutter_v1",
    "Cache-SCA/Isaaclab-so101_11task_baseCaP_3300epi",
    "LeRobot-worldwide-hackathon/241-Sushi_Shinkansen_So101-pick_sushi",
    "Project-IRA/TPSoSe2026_Dataset_Lego_LeRobot_SO101",
    "Project-IRA/TPSoSe2026_Dataset_Dice_Throw_LeRobot_SO101",
    "Qiu-Xinchuan/so101_Selective_color_sorting-long",
    "kogeek/so101_grape_ext",
    "ammiellewb/so101_liquid_pouring",
    "cueng/so101_demo_bowl",
    "Qiu-Xinchuan/so101_box_multi-object-packing",
    "littledragon/so101_sock_stowing2",
    "Qiu-Xinchuan/so101_Selective_color_sorting-long",
    "Project-IRA/TPSoSe2026_Dataset_Fetch_Ball_LeRobot_SO101",
    "yen-0/so101-write-5-kadokawa",
    "kaiserbuffle/hanoi",
    "roboticshack/team16-water-pouring"
]

OUTPUT_DIR = Path("/home/ubuntu/harsha/datasets")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Keep every Hub request single-flight. Concurrent datasets and file workers
# multiply API calls and make a 429 recover much more slowly.
DATASET_WORKERS = 1
FILE_WORKERS = 3
MAX_ATTEMPTS = 4
RATE_LIMIT_WINDOW_SECONDS = 5 * 60
MAX_BACKOFF_SECONDS = 60


def _jitter(upper_bound: float) -> float:
    return uniform(0, upper_bound)


def _retry_after_seconds(response: object) -> float | None:
    """Read a Retry-After header expressed as seconds or an HTTP date."""
    headers = getattr(response, "headers", {}) or {}
    value = headers.get("Retry-After")
    if value is None:
        return None

    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        pass

    try:
        retry_at = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None

    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=timezone.utc)
    return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())


def retry_delay_seconds(
    exc: Exception,
    attempt: int,
    jitter_seconds: Callable[[float], float] | None = None,
) -> float:
    """Return an appropriate delay for a failed Hub request.

    HTTP 429 pauses for the server-provided window, or five minutes when the
    response has no Retry-After header. Other failures use capped exponential
    backoff. A small jitter prevents synchronized retries.
    """
    jitter = jitter_seconds or _jitter
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)

    if status_code == 429:
        server_delay = _retry_after_seconds(response)
        base_delay = server_delay if server_delay is not None else RATE_LIMIT_WINDOW_SECONDS
        return base_delay + jitter(min(30.0, max(1.0, base_delay * 0.1)))

    base_delay = min(MAX_BACKOFF_SECONDS, 2**attempt)
    return base_delay + jitter(min(5.0, base_delay * 0.1))


def validate_dataset(repo: str, local_dir: Path) -> None:
    """Raise unless all files in the remote manifest exist with the right size."""
    info = HfApi().dataset_info(repo, files_metadata=True)
    problems = []

    for sibling in info.siblings or []:
        relative_path = sibling.rfilename
        local_path = local_dir / relative_path
        expected_size = sibling.size

        if not local_path.is_file():
            problems.append(f"missing: {relative_path}")
        elif expected_size is not None and local_path.stat().st_size != expected_size:
            actual_size = local_path.stat().st_size
            problems.append(
                f"wrong size: {relative_path} "
                f"(expected {expected_size}, got {actual_size})"
            )
            # A later snapshot_download run can re-fetch this corrupt file.
            local_path.unlink()

        if len(problems) >= 20:
            problems.append("additional errors omitted")
            break

    if problems:
        raise RuntimeError("dataset validation failed:\n      " + "\n      ".join(problems))


def download_dataset(repo: str) -> str:
    """Download and validate one repository without accepting partial results."""
    local_dir = OUTPUT_DIR / repo.replace("/", "_")

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            print(f"Starting {repo} (attempt {attempt}/{MAX_ATTEMPTS})", flush=True)
            snapshot_download(
                repo_id=repo,
                repo_type="dataset",
                local_dir=local_dir,
                force_download=False,
                resume_download=True,
                max_workers=FILE_WORKERS,
            )
            validate_dataset(repo, local_dir)
            return f"Finished and validated: {repo}"
        except Exception as exc:
            if attempt == MAX_ATTEMPTS:
                raise RuntimeError(
                    f"Failed after {MAX_ATTEMPTS} attempts: {repo}: {exc}"
                ) from exc

            delay = retry_delay_seconds(exc, attempt)
            response = getattr(exc, "response", None)
            reason = "rate limit" if getattr(response, "status_code", None) == 429 else "download error"
            print(
                f"Retrying {repo} in {delay:.1f}s after {reason}: {exc}",
                file=sys.stderr,
                flush=True,
            )
            time.sleep(delay)

    raise AssertionError("unreachable")


def select_datasets(requested_repositories: Sequence[str]) -> list[str]:
    """Use explicit repositories for resume/new downloads, otherwise full list."""
    return list(requested_repositories) if requested_repositories else list(DATASETS)


def main(argv: Sequence[str] | None = None) -> int:
    datasets = select_datasets(list(sys.argv[1:] if argv is None else argv))
    print(f"Downloading {len(datasets)} dataset(s) to {OUTPUT_DIR}\n")
    failures = []

    with ThreadPoolExecutor(max_workers=DATASET_WORKERS) as executor:
        futures = {executor.submit(download_dataset, repo): repo for repo in datasets}

        for future in as_completed(futures):
            repo = futures[future]
            try:
                print(f"OK: {future.result()}")
            except Exception as exc:
                failures.append(repo)
                print(f"ERROR: {exc}", file=sys.stderr)

    if failures:
        print(
            f"\n{len(failures)} dataset(s) failed: {', '.join(failures)}",
            file=sys.stderr,
        )
        return 1

    print("\nAll datasets downloaded and validated successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
