HF_DATASET_NAME = "13point5/swe-grep-rlm-reputable-recent-5plus"
DEFAULT_DATASET_SPLIT = "train"
DEFAULT_SANDBOX_LABEL = "swe-grep-rlm"
DEFAULT_SANDBOX_REPO_DIR = "/workspace/repo"

DEFAULT_GLOB_LIMIT = 200
DEFAULT_RG_LIMIT = 120
DEFAULT_READ_LIMIT = 120

MAX_GLOB_LIMIT = 1000
MAX_RG_LIMIT = 400
MAX_READ_LIMIT = 400

SYSTEM_PROMPT = """You are solving a code-search retrieval task.

Your goal is to identify the repository files that are relevant to the user query.

Rules:
- The target repository has been cloned inside the sandbox for this task.
- The repository checkout is the current REPL working directory.
- Use the Python REPL plus the search tools to inspect that checkout.
- Paths must stay relative to the repository root.
- When you are done, set answer["content"] to plain text with one repo-relative file path per line.
- Do not include bullets, numbering, XML, JSON, markdown fences, or extra commentary.
- Example:
  path/to/file_a.py
  docs/file_b.md
- After setting answer["content"], set answer["ready"] = True.
"""
