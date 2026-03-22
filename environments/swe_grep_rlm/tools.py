from __future__ import annotations

import json
import shlex

import verifiers as vf

from constants import (
    DEFAULT_GLOB_LIMIT,
    DEFAULT_READ_LIMIT,
    DEFAULT_RG_LIMIT,
    DEFAULT_SANDBOX_REPO_DIR,
    MAX_GLOB_LIMIT,
    MAX_READ_LIMIT,
    MAX_RG_LIMIT,
)
from dataset import normalize_relpath


class CodeSearchToolMixin:
    def build_root_tools(self) -> list:
        return [
            self.glob_files,
            self.ripgrep,
            self.read_file_range,
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
        """List repository files matching a glob pattern inside the sandbox checkout."""
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
        """Search sandbox repository text with ripgrep and return line-numbered matches."""
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
        """Read a numbered file slice from the sandbox checkout."""
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
