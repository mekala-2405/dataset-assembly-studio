import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from huggingface_hub import HfApi, snapshot_download

DATASETS = [
    "youliangtan/so101-table-cleanup",
    "whosricky/so101-megamix-v1",
    "Cornito/so101_tea2",
    "observabot/so101_cloth_folding1",
    "Cornito/so101_test3",
    "kangkb7701/so101-vla-datasets",
    "sreetz-nv/so101-clean-up-vials-into-rack-50_20260628_131121",
    "sreetz-nv/so101_teleop_vials_rack_left_cosmos_70",
    "5hadytru/so101_IF_6",
    "Project-IRA/TPSoSe2026_Dataset_Collection_LeRobot_SO101",
]

OUTPUT_DIR = Path("/home/ubuntu/harsha/datasets")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Keep total transfers modest. The old 6 * 8 setting could start 48 at once.
DATASET_WORKERS = 2
FILE_WORKERS = 4
MAX_ATTEMPTS = 3


def validate_dataset(repo: str, local_dir: Path) -> None:
    """Raise if the local snapshot has missing or truncated repository files."""
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
            # Let snapshot_download fetch just this bad file on the next attempt.
            local_path.unlink()

        if len(problems) >= 20:
            problems.append("additional errors omitted")
            break

    if problems:
        raise RuntimeError("dataset validation failed:\n      " + "\n      ".join(problems))


def download_dataset(repo: str) -> str:
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

            delay = 2 ** attempt
            print(
                f"Retrying {repo} in {delay}s after error: {exc}",
                file=sys.stderr,
                flush=True,
            )
            time.sleep(delay)

    raise AssertionError("unreachable")


def main() -> int:
    print(f"Downloading {len(DATASETS)} datasets to {OUTPUT_DIR}\n")
    failures = []

    with ThreadPoolExecutor(max_workers=DATASET_WORKERS) as executor:
        futures = {executor.submit(download_dataset, repo): repo for repo in DATASETS}

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
