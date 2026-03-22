from __future__ import annotations

from typing import Any, Literal

import verifiers as vf

from .constants import DEFAULT_DATASET_SPLIT, DEFAULT_SANDBOX_LABEL
from .dataset import build_dataset
from .environment import CodeSearchRLMEnv
from .rubric import build_rubric


def load_environment(
    dataset_split: str = DEFAULT_DATASET_SPLIT,
    max_examples: int = -1,
    shuffle: bool = False,
    seed: int = 0,
    max_turns: int = 30,
    sub_llm_max_turns: int = 3,
    max_sub_llm_parallelism: int = 4,
    max_output_length: int = 6000,
    code_execution_timeout: int = 120,
    root_prompt_verbosity: Literal["light", "medium", "heavy"] = "heavy",
    sandbox_docker_image: str = "python:3.11-slim",
    sandbox_cpu_cores: int = 1,
    sandbox_memory_gb: int = 2,
    sandbox_disk_size_gb: int = 5,
    sandbox_gpu_count: int = 0,
    sandbox_timeout_minutes: int = 60,
    sandbox_labels: list[str] | None = None,
    **kwargs: Any,
) -> vf.Environment:
    dataset = build_dataset(
        split=dataset_split,
        max_examples=max_examples,
        shuffle=shuffle,
        seed=seed,
    )
    labels = sorted(dict.fromkeys((sandbox_labels or []) + [DEFAULT_SANDBOX_LABEL]))

    return CodeSearchRLMEnv(
        dataset=dataset,
        eval_dataset=dataset,
        rubric=build_rubric(),
        max_turns=max_turns,
        sub_llm_max_turns=sub_llm_max_turns,
        max_sub_llm_parallelism=max_sub_llm_parallelism,
        max_output_length=max_output_length,
        code_execution_timeout=code_execution_timeout,
        root_prompt_verbosity=root_prompt_verbosity,
        sandbox_docker_image=sandbox_docker_image,
        sandbox_cpu_cores=sandbox_cpu_cores,
        sandbox_memory_gb=sandbox_memory_gb,
        sandbox_disk_size_gb=sandbox_disk_size_gb,
        sandbox_gpu_count=sandbox_gpu_count,
        sandbox_timeout_minutes=sandbox_timeout_minutes,
        sandbox_labels=labels,
        **kwargs,
    )
