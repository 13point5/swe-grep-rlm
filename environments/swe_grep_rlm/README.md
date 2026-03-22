# swe-grep-rlm

### Overview
- **Environment ID**: `swe-grep-rlm`
- **Short description**: RLM-based code-search environment that returns relevant files for a repository query.
- **Tags**: `rlm`, `code-search`, `retrieval`, `python`, `repl`

### Datasets
- **Primary dataset**: [`13point5/swe-grep-rlm-reputable-recent-5plus`](https://huggingface.co/datasets/13point5/swe-grep-rlm-reputable-recent-5plus)
- **Split**: `train` by default
- **Transformation**: each row is converted directly into a Verifiers example with:
  - `prompt`: built from `repo`, `pr_number`, and `query_text`
  - `answer`: the row's `files`
  - `info`: all original dataset columns, plus `task_id`, `gold_files`, `sandbox_repo_dir`, and `repo_clone_url`

### Task
- **Type**: Multi-turn RLM tool-use retrieval
- **Output format expectations**: The agent should set `answer["content"]` to:
  - one repo-relative file path per line
  - then set `answer["ready"] = True`
- **Rubric overview**: Main reward is file-level F1 against `gold_files`; metrics include precision, recall, exact match, and predicted file count parsed from `answer["content"]`.
- **Sandbox behavior**: for each example, the environment clones `https://github.com/{repo}.git` inside the sandbox and checks out the PR head for `pr_number` before the worker starts

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

### Environment Arguments
Supported arguments:

| Arg | Type | Default | Description |
| --- | ---- | ------- | ----------- |
| `dataset_split` | `str` | `"train"` | Hugging Face dataset split to load from `13point5/swe-grep-rlm-reputable-recent-5plus`. |
| `max_examples` | `int` | `-1` | Limit the training dataset size. |
| `shuffle` | `bool` | `False` | Shuffle the loaded dataset before truncation. |
| `seed` | `int` | `0` | Shuffle seed. |
| `max_turns` | `int` | `8` | Maximum root-model turns. |
| `sub_llm_max_turns` | `int` | `3` | Maximum turns per `llm_batch()` sub-call. |
| `max_sub_llm_parallelism` | `int` | `4` | Maximum parallel sub-LLM calls. |

Tool-level knobs:
- `glob_files(pattern="**/*", limit=200, include_hidden=False)`
- `ripgrep(pattern, path=".", glob_pattern=None, context_lines=0, ignore_case=True, limit=120)`
- `read_file_range(file_path, start_line=1, end_line=None, num_lines=120)`

### Metrics
| Metric | Meaning |
| ------ | ------- |
| `reward` | File-level F1 between the parsed `answer["content"]` file paths and `gold_files` |
| `retrieval_precision` | Precision of the file paths parsed from `answer["content"]` |
| `retrieval_recall` | Recall of the file paths parsed from `answer["content"]` |
| `exact_match` | `1.0` only if the parsed `answer["content"]` files exactly match `gold_files` |
| `predicted_file_count` | Number of file paths parsed from `answer["content"]` |
| `gold_file_count` | Number of gold files in the dataset row |

### Dataset Mapping

The environment uses a very small transform function over the Hugging Face row:

```python
{
  "task_id": f"{repo.replace('/', '__')}-pr-{pr_number}",
  "task": "code_search_retrieval",
  "prompt": [{"role": "user", "content": prompt}],
  "answer": sorted(unique(files)),
  "info": {
    **original_row_columns,
    "task_id": task_id,
    "gold_files": sorted(unique(files)),
    "sandbox_repo_dir": "/workspace/repo",
    "repo_clone_url": f"https://github.com/{repo}.git",
  },
}
```
