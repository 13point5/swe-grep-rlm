from __future__ import annotations

import json
import shlex

import verifiers as vf

from .constants import (
    DEFAULT_GLOB_LIMIT,
    DEFAULT_READ_LIMIT,
    DEFAULT_RG_LIMIT,
    DEFAULT_SANDBOX_REPO_DIR,
    MAX_GLOB_LIMIT,
    MAX_READ_LIMIT,
    MAX_RG_LIMIT,
)
from .dataset import normalize_relpath, normalize_relpaths


class CodeSearchToolMixin:
    def build_root_tools(self) -> list:
        return [
            self.glob_files,
            self.ripgrep,
            self.read_file_range,
            self.submit_files,
        ]

    def require_root_state(self) -> vf.State:
        context = self._root_tool_context_var.get()
        if not context or "state" not in context:
            raise RuntimeError("This tool can only be used from the root REPL.")
        state = context["state"]
        if not isinstance(state, dict):
            raise RuntimeError("Root REPL state is unavailable.")
        return state

    def sandbox_repo_dir_for_state(self, state: vf.State) -> str:
        repo_dir = state.get("sandbox_repo_dir")
        if isinstance(repo_dir, str) and repo_dir.strip():
            return repo_dir
        info = state.get("info", {})
        if isinstance(info, dict):
            repo_dir = info.get("sandbox_repo_dir")
            if isinstance(repo_dir, str) and repo_dir.strip():
                return repo_dir
        return DEFAULT_SANDBOX_REPO_DIR

    def sandbox_id_for_state(self, state: vf.State) -> str:
        sandbox_id = state.get("sandbox_id")
        if not isinstance(sandbox_id, str) or not sandbox_id:
            raise RuntimeError("Sandbox is unavailable for this task.")
        return sandbox_id

    async def execute_sandbox_command(
        self,
        state: vf.State,
        command: str,
        *,
        working_dir: str | None = None,
        timeout: int = 30,
    ):
        sandbox_id = self.sandbox_id_for_state(state)
        return await self._executor._execute_sandbox_command(
            sandbox_id,
            command,
            working_dir=working_dir,
            timeout=timeout,
        )

    async def glob_files(
        self,
        pattern: str = "**/*",
        limit: int = DEFAULT_GLOB_LIMIT,
        include_hidden: bool = False,
    ) -> list[str]:
        """List repo-relative files matching a glob pattern.

        Use this to discover candidate paths by filename or directory shape before
        reading file contents. It is especially useful for finding tests, docs,
        configs, and metadata files. Prefer this over broad REPL shelling when you
        already know something about the path structure.

        Args:
            pattern: Glob rooted at the repository checkout, such as
                ``"docs/**/*.md"``, ``"tests/**/*"``, or ``"**/*query*"``.
            limit: Maximum number of matching files to return.
            include_hidden: Set to ``True`` when hidden files or directories may
                matter, such as ``.changeset/*`` or ``.size-limit.json``.

        Returns:
            A sorted list of repo-relative file paths.
        """
        state = self.require_root_state()
        repo_root = self.sandbox_repo_dir_for_state(state)
        payload = json.dumps(
            {
                "pattern": pattern,
                "limit": max(1, min(limit, MAX_GLOB_LIMIT)),
                "include_hidden": include_hidden,
            }
        )
        command = (
            "python - <<'PY'\n"
            "import json\n"
            "from pathlib import Path, PurePosixPath\n"
            f"cfg = json.loads({payload!r})\n"
            "matches = []\n"
            "for path in Path('.').glob(cfg['pattern']):\n"
            "    if not path.is_file():\n"
            "        continue\n"
            "    relative = path.as_posix()\n"
            "    if not cfg['include_hidden'] and any(part.startswith('.') for part in PurePosixPath(relative).parts):\n"
            "        continue\n"
            "    matches.append(relative)\n"
            "    if len(matches) >= cfg['limit']:\n"
            "        break\n"
            "print(json.dumps(sorted(matches)))\n"
            "PY"
        )
        result = await self.execute_sandbox_command(state, command, working_dir=repo_root, timeout=30)
        exit_code = getattr(result, "exit_code", 0)
        if exit_code not in (0, None):
            stderr = (getattr(result, "stderr", "") or "").strip()
            raise RuntimeError(stderr or "glob_files failed.")
        stdout = (getattr(result, "stdout", "") or "").strip()
        return json.loads(stdout or "[]")

    async def ripgrep(
        self,
        pattern: str,
        path: str = ".",
        glob_pattern: str | None = None,
        context_lines: int = 0,
        ignore_case: bool = True,
        limit: int = DEFAULT_RG_LIMIT,
    ) -> str:
        """Search repository text with ripgrep and return line-numbered matches.

        Use this first when you have concrete search terms from the report, such
        as option names, function names, error strings, symbols, or exact phrases.
        Narrow the search with ``path`` or ``glob_pattern`` before reading files.
        If the output is large, tighten the query instead of dumping more text.

        Args:
            pattern: Text or regex pattern to search for.
            path: Repo-relative directory or file to search within. Use ``"."``
                for the whole checkout.
            glob_pattern: Optional ripgrep ``-g`` filter such as ``"*.py"`` or
                ``"docs/**/*.md"``.
            context_lines: Number of surrounding lines to include per match.
            ignore_case: Whether the search should be case-insensitive.
            limit: Maximum number of output lines to return before truncation.

        Returns:
            A newline-delimited string of matches with line numbers, or a short
            no-match/truncation message.
        """
        state = self.require_root_state()
        repo_root = self.sandbox_repo_dir_for_state(state)
        relative_path = "." if path.strip() in {"", "."} else normalize_relpath(path)

        command = ["rg", "--line-number", "--no-heading", "--color", "never"]
        if ignore_case:
            command.append("-i")
        safe_context = max(0, min(context_lines, 5))
        if safe_context:
            command.extend(["-C", str(safe_context)])
        if glob_pattern:
            command.extend(["-g", glob_pattern])
        command.extend([pattern, relative_path])

        result = await self.execute_sandbox_command(
            state,
            " ".join(shlex.quote(part) for part in command),
            working_dir=repo_root,
            timeout=30,
        )
        exit_code = getattr(result, "exit_code", 0)
        stdout = getattr(result, "stdout", "") or ""
        stderr = getattr(result, "stderr", "") or ""
        if exit_code == 1:
            return "No matches found."
        if exit_code not in (0, None):
            raise RuntimeError(stderr.strip() or "ripgrep failed.")

        lines = stdout.splitlines()
        if not lines:
            return "No matches found."
        safe_limit = max(1, min(limit, MAX_RG_LIMIT))
        if len(lines) > safe_limit:
            truncated = "\n".join(lines[:safe_limit])
            return (
                f"{truncated}\n\n"
                f"[TRUNCATED after {safe_limit} lines. Narrow the pattern, path, or glob_pattern.]"
            )
        return "\n".join(lines)

    async def read_file_range(
        self,
        file_path: str,
        start_line: int = 1,
        end_line: int | None = None,
        num_lines: int = DEFAULT_READ_LIMIT,
    ) -> str:
        """Read a numbered slice from one repository file.

        Use this only after you have narrowed down to a promising file. Prefer
        small slices around the relevant symbol or match instead of reading whole
        files. If you need more context, continue from the follow-up hint in the
        returned footer.

        Args:
            file_path: Repo-relative file path to inspect.
            start_line: First line number to read, inclusive.
            end_line: Last line number to read, inclusive. If omitted, the tool
                reads ``num_lines`` starting at ``start_line``.
            num_lines: Slice length when ``end_line`` is omitted.

        Returns:
            A formatted snippet with line numbers and continuation hints.
        """
        state = self.require_root_state()
        repo_root = self.sandbox_repo_dir_for_state(state)
        payload = json.dumps(
            {
                "file_path": normalize_relpath(file_path),
                "start_line": max(1, start_line),
                "end_line": end_line,
                "num_lines": num_lines,
                "max_read_lines": MAX_READ_LIMIT,
            }
        )
        command = (
            "python - <<'PY'\n"
            "import json\n"
            "from pathlib import Path\n"
            f"cfg = json.loads({payload!r})\n"
            "path = Path(cfg['file_path'])\n"
            "if not path.exists():\n"
            "    raise FileNotFoundError(f\"Path does not exist: {cfg['file_path']}\")\n"
            "if not path.is_file():\n"
            "    raise ValueError(f\"Expected a file path, got: {cfg['file_path']}\")\n"
            "lines = path.read_text(encoding='utf-8', errors='replace').splitlines()\n"
            "if not lines:\n"
            "    print(f\"{cfg['file_path']} is empty.\")\n"
            "    raise SystemExit(0)\n"
            "safe_start = max(1, int(cfg['start_line']))\n"
            "end_line = cfg['end_line']\n"
            "if end_line is None:\n"
            "    safe_count = max(1, min(int(cfg['num_lines']), int(cfg['max_read_lines'])))\n"
            "    safe_end = min(len(lines), safe_start + safe_count - 1)\n"
            "else:\n"
            "    safe_end = max(safe_start, min(int(end_line), len(lines)))\n"
            "    if safe_end - safe_start + 1 > int(cfg['max_read_lines']):\n"
            "        safe_end = safe_start + int(cfg['max_read_lines']) - 1\n"
            "if safe_start > len(lines):\n"
            "    print(f\"{cfg['file_path']} has only {len(lines)} lines.\")\n"
            "    raise SystemExit(0)\n"
            "snippet_lines = []\n"
            "for line_number in range(safe_start, safe_end + 1):\n"
            "    snippet_lines.append(f\"{line_number:>4}: {lines[line_number - 1]}\")\n"
            "trailer = []\n"
            "if safe_end < len(lines):\n"
            "    trailer.append(f\"[MORE BELOW: continue at start_line={safe_end + 1}]\")\n"
            "if safe_start > 1:\n"
            "    trailer.append(f\"[MORE ABOVE: current slice starts at line {safe_start}]\")\n"
            "body = '\\n'.join(snippet_lines)\n"
            "if trailer:\n"
            "    body = body + '\\n\\n' + '\\n'.join(trailer)\n"
            "print(f\"{cfg['file_path']}:{safe_start}-{safe_end}\\n{body}\")\n"
            "PY"
        )
        result = await self.execute_sandbox_command(state, command, working_dir=repo_root, timeout=30)
        exit_code = getattr(result, "exit_code", 0)
        if exit_code not in (0, None):
            stderr = (getattr(result, "stderr", "") or "").strip()
            raise RuntimeError(stderr or "read_file_range failed.")
        return (getattr(result, "stdout", "") or "").rstrip()

    async def submit_files(self, files: list[str]) -> str:
        """Finalize the task by submitting repo-relative file paths.

        This is the required completion path for this task. Call it once you have
        your final file list. The rollout will stop after submission, and the
        reward will be computed from the submitted paths.

        Args:
            files: Final repo-relative file paths. Pass only file paths, one list
                element per file, with no explanations or extra formatting.

        Returns:
            A short confirmation message summarizing the stored submission.
        """
        state = self.require_root_state()
        normalized_files = normalize_relpaths(str(item) for item in files)
        state["submitted_files"] = normalized_files
        state["final_answer"] = "\n".join(normalized_files)
        return f"Submitted {len(normalized_files)} files."
