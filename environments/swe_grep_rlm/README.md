# swe-grep-rlm

### Overview
- **Environment ID**: `swe-grep-rlm`
- **Short description**: RLM-based code-search environment that returns repo-relative files useful for resolving an issue report.
- **Tags**: `rlm`, `code-search`, `retrieval`, `python`, `repl`

### Datasets
- **Primary dataset**: [`13point5/swe-grep-rlm-reputable-recent-5plus`](https://huggingface.co/datasets/13point5/swe-grep-rlm-reputable-recent-5plus)
- **Split**: `train` by default
- **Transformation**: each row is converted directly into a Verifiers example with:
  - `prompt`: built from `repo`, `pr_number`, `query_text`, and a short task-guidance block
  - `answer`: newline-joined gold file paths for sample serialization and hub uploads
  - `info`: all original dataset columns, plus `task_id`, `gold_files`, `sandbox_repo_dir`, and `repo_clone_url`

### Task And Behavior
- **Type**: Multi-turn `RLMEnv` retrieval task
- **RLM scaffolding**: uses a custom Python `RLMEnv` system prompt derived from the stock prompt
- **Prompting behavior**: the custom prompt keeps the standard iterative REPL lifecycle, but adds explicit guidance about turn budgeting, `llm_batch()` usage, the search tools, and the required `submit_files(files=[...])` finish path
- **Sandbox behavior**: for each example, the environment clones `https://github.com/{repo}.git` inside the sandbox and checks out the PR head for `pr_number`
- **Working directory**: the sandbox checkout lives at `/workspace/repo`
- **Finalization**: from inside the REPL, the agent should call `submit_files(files=[...])` with only repo-relative file paths
- **Scoring behavior**: reward is file-level F1 against `info["gold_files"]`; metrics also include precision, recall, exact match, and predicted/gold file counts

### Quickstart
Run an evaluation with default settings:

```bash
prime eval run swe-grep-rlm
```

Configure model and sampling:

```bash
prime eval run swe-grep-rlm --provider prime --model openai/gpt-4.1-mini -n 1 -r 1
```

Notes:
- Use `-a` / `--env-args` to pass environment-specific configuration as a JSON object.
- The environment downloads the Hugging Face dataset at load time and clones the target repository inside the sandbox during rollout setup.
- The outer model-facing tool is the stock `call_python_repl` tool.
- `glob_files`, `ripgrep`, `read_file_range`, `submit_files`, and `llm_batch` are available inside that Python REPL.
- The custom RLM prompt explains the REPL lifecycle, turn budgeting, sub-LLM usage, and the required submission flow; the tool docstrings explain when to use the search helpers and what their arguments mean.

### Environment Arguments
Supported arguments:

| Arg | Type | Default | Description |
| --- | ---- | ------- | ----------- |
| `dataset_split` | `str` | `"train"` | Hugging Face dataset split to load from `13point5/swe-grep-rlm-reputable-recent-5plus`. |
| `max_examples` | `int` | `-1` | Limit the training dataset size. |
| `shuffle` | `bool` | `False` | Shuffle the loaded dataset before truncation. |
| `seed` | `int` | `0` | Shuffle seed. |
| `max_turns` | `int` | `30` | Maximum root-model turns. |
| `sub_llm_max_turns` | `int` | `3` | Maximum turns per `llm_batch()` sub-call. |
| `max_sub_llm_parallelism` | `int` | `4` | Maximum parallel sub-LLM calls. |
| `max_output_length` | `int` | `6000` | Maximum REPL output length returned to the model per call. |
| `code_execution_timeout` | `int` | `120` | Timeout in seconds for one REPL execution. |
| `root_prompt_verbosity` | `str` | `"heavy"` | Verbosity setting for the env's custom RLM system prompt. |
| `sandbox_docker_image` | `str` | `"python:3.11-slim"` | Docker image used for the sandbox worker. |
| `sandbox_cpu_cores` | `int` | `1` | Number of sandbox CPU cores. |
| `sandbox_memory_gb` | `int` | `2` | Sandbox memory limit in GB. |
| `sandbox_disk_size_gb` | `int` | `5` | Sandbox disk size in GB. |
| `sandbox_gpu_count` | `int` | `0` | Number of GPUs requested for the sandbox. |
| `sandbox_timeout_minutes` | `int` | `60` | Sandbox lifetime limit in minutes. |
| `sandbox_labels` | `list[str] | None` | `None` | Optional extra sandbox labels; the env always adds `swe-grep-rlm`. |

### Root REPL Tools
- `glob_files(pattern="**/*", limit=200, include_hidden=False)`
  Use this to discover candidate paths by filename or directory shape before reading content. Hidden files are excluded unless `include_hidden=True`.
- `ripgrep(pattern, path=".", glob_pattern=None, context_lines=0, ignore_case=True, limit=120)`
  Use this first for exact issue terms, symbols, option names, and error strings. Output is truncated if it exceeds the line limit.
- `read_file_range(file_path, start_line=1, end_line=None, num_lines=120)`
  Use this after narrowing down to a specific file. It returns numbered slices with continuation hints.
- `submit_files(files)`
  Use this to finish the task. Pass only repo-relative file paths, with no bullets or commentary.
- Internal safety caps clamp tool requests to `glob<=1000`, `ripgrep<=400`, and `read<=400`.

### Metrics
| Metric | Meaning |
| ------ | ------- |
| `reward` | File-level F1 between the submitted file paths and `gold_files` |
| `retrieval_precision` | Precision of the submitted file paths |
| `retrieval_recall` | Recall of the submitted file paths |
| `exact_match` | `1.0` only if the submitted files exactly match `gold_files` |
| `predicted_file_count` | Number of submitted file paths |
| `gold_file_count` | Number of gold files in the dataset row |

### Dataset Mapping

The environment uses a very small transform function over the Hugging Face row:

```python
{
  "task_id": f"{repo.replace('/', '__')}-pr-{pr_number}",
  "task": "code_search_retrieval",
  "prompt": [{"role": "user", "content": prompt}],
  "answer": "\\n".join(sorted(unique(files))),
  "info": {
    **original_row_columns,
    "task_id": task_id,
    "gold_files": sorted(unique(files)),
    "sandbox_repo_dir": "/workspace/repo",
    "repo_clone_url": f"https://github.com/{repo}.git",
  },
}
```

The `answer` field is a string for compatibility with evaluation result uploads. The rubric reads the canonical gold labels from `info["gold_files"]`.
