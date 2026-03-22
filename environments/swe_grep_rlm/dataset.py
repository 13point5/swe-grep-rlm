from __future__ import annotations

from datetime import date, datetime
from pathlib import PurePosixPath
from typing import Any, Iterable

from datasets import Dataset, load_dataset

from constants import HF_DATASET_NAME, DEFAULT_DATASET_SPLIT, DEFAULT_SANDBOX_REPO_DIR


def normalize_relpath(path: str) -> str:
    cleaned = path.replace("\\", "/").strip()
    if not cleaned:
        raise ValueError("Empty file path is not allowed.")

    normalized = PurePosixPath(cleaned)
    if normalized.is_absolute():
        raise ValueError(f"Expected a repo-relative path, got absolute path: {path}")
    if any(part == ".." for part in normalized.parts):
        raise ValueError(f"Path may not escape the repository root: {path}")
    return normalized.as_posix()


def normalize_relpaths(paths: Iterable[str]) -> list[str]:
    normalized = [normalize_relpath(path) for path in paths]
    return sorted(dict.fromkeys(normalized))


def serialize_info_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, list):
        return [serialize_info_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): serialize_info_value(item) for key, item in value.items()}
    return value


def transform_row(raw_row: dict[str, Any], row_index: int) -> dict[str, Any]:
    question = str(raw_row.get("query_text", "")).strip()
    if not question:
        raise ValueError(f"Dataset row {row_index} is missing query_text.")

    repo = str(raw_row.get("repo", "")).strip()
    if not repo:
        raise ValueError(f"Dataset row {row_index} is missing repo.")

    pr_number = raw_row.get("pr_number")
    if pr_number in (None, ""):
        raise ValueError(f"Dataset row {row_index} is missing pr_number.")

    files_raw = raw_row.get("files")
    if not isinstance(files_raw, list) or not files_raw:
        raise ValueError(f"Dataset row {row_index} must contain a non-empty files list.")
    gold_files = normalize_relpaths(str(item) for item in files_raw)

    task_id = f"{repo.replace('/', '__')}-pr-{pr_number}"
    info = {key: serialize_info_value(value) for key, value in raw_row.items()}
    info["task_id"] = task_id
    info["gold_files"] = gold_files
    info["sandbox_repo_dir"] = DEFAULT_SANDBOX_REPO_DIR
    info["repo_clone_url"] = f"https://github.com/{repo}.git"

    prompt = (
        f"Repository: {repo}\n"
        f"Pull request: #{pr_number}\n\n"
        f"Find the relevant repository files for this report:\n\n{question}"
    )

    return {
        "task_id": task_id,
        "task": "code_search_retrieval",
        "prompt": [{"role": "user", "content": prompt}],
        "answer": gold_files,
        "info": info,
    }


def build_dataset(
    *,
    split: str = DEFAULT_DATASET_SPLIT,
    max_examples: int = -1,
    shuffle: bool = False,
    seed: int = 0,
) -> Dataset:
    raw_dataset = load_dataset(HF_DATASET_NAME, split=split)
    rows = [transform_row(raw_dataset[index], index) for index in range(len(raw_dataset))]
    dataset = Dataset.from_list(rows)
    if shuffle:
        dataset = dataset.shuffle(seed=seed)
    if max_examples >= 0:
        dataset = dataset.select(range(min(max_examples, len(dataset))))
    return dataset
