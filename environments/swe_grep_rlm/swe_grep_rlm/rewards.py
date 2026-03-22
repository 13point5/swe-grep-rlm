from __future__ import annotations

from .dataset import normalize_relpaths


def parse_result_lines(text: str | None) -> list[str]:
    if not isinstance(text, str):
        return []
    cleaned = text.strip()
    if not cleaned:
        return []
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    if not lines:
        return []
    try:
        return normalize_relpaths(lines)
    except ValueError:
        return []


def extract_result_files(state) -> list[str]:
    final_answer = state.get("final_answer")
    return parse_result_lines(final_answer if isinstance(final_answer, str) else None)


def result_stats(state) -> dict[str, float]:
    info = state.get("info", {})
    gold_raw = info.get("gold_files", []) if isinstance(info, dict) else []
    gold_files = set(normalize_relpaths(str(item) for item in gold_raw)) if gold_raw else set()
    predicted_files = set(extract_result_files(state))

    if not gold_files:
        return {
            "precision": 0.0,
            "recall": 0.0,
            "f1": 0.0,
            "exact_match": 0.0,
            "predicted_count": float(len(predicted_files)),
            "gold_count": 0.0,
        }

    overlap = len(gold_files & predicted_files)
    precision = overlap / len(predicted_files) if predicted_files else 0.0
    recall = overlap / len(gold_files)
    f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
    exact_match = 1.0 if predicted_files == gold_files else 0.0

    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "exact_match": exact_match,
        "predicted_count": float(len(predicted_files)),
        "gold_count": float(len(gold_files)),
    }


async def retrieval_f1(state) -> float:
    return result_stats(state)["f1"]


async def retrieval_precision(state) -> float:
    return result_stats(state)["precision"]


async def retrieval_recall(state) -> float:
    return result_stats(state)["recall"]


async def exact_match(state) -> float:
    return result_stats(state)["exact_match"]


async def predicted_file_count(state) -> float:
    return result_stats(state)["predicted_count"]


async def gold_file_count(state) -> float:
    info = state.get("info", {})
    gold_raw = info.get("gold_files", []) if isinstance(info, dict) else []
    gold_files = normalize_relpaths(str(item) for item in gold_raw) if gold_raw else []
    return float(len(gold_files))
