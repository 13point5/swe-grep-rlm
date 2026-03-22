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

TASK_PROMPT_GUIDANCE = """Task notes:
- Return the repository files that will be most useful for resolving this report.
- Do not return every semantically related file; prioritize files that are most likely to need inspection, modification, or validation work to implement the fix.
- Good answers often include implementation files, tests, docs, configs, metadata files, and hidden files when the report suggests them.
- Hidden files matter in some repos, so remember to look for dotfiles when they seem relevant.
- Expect multiple files, often at least 5.
- When you are ready to finish, call `submit_files(files=[...])` from inside the REPL with only repo-relative file paths.
- Do not submit prose, bullets, explanations, XML, or markdown; submit only file paths.
"""
