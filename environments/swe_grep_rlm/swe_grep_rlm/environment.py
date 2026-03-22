from __future__ import annotations

import shlex
from typing import Any, Literal

from verifiers.envs.experimental.rlm_env import RLMEnv

from .constants import DEFAULT_SANDBOX_REPO_DIR
from .prompts import build_system_prompt
from .tools import CodeSearchToolMixin


class CodeSearchRLMEnv(CodeSearchToolMixin, RLMEnv):
    def __init__(
        self,
        *,
        root_prompt_verbosity: Literal["light", "medium", "heavy"] = "heavy",
        max_turns: int = 30,
        sub_llm_max_turns: int = 3,
        max_sub_llm_parallelism: int = 4,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            root_tools=self.build_root_tools(),
            repl_language="python",
            root_prompt_verbosity=root_prompt_verbosity,
            system_prompt=build_system_prompt(
                root_prompt_verbosity=root_prompt_verbosity,
                max_turns=max_turns,
                sub_llm_max_turns=sub_llm_max_turns,
                max_sub_llm_parallelism=max_sub_llm_parallelism,
            ),
            max_turns=max_turns,
            sub_llm_max_turns=sub_llm_max_turns,
            max_sub_llm_parallelism=max_sub_llm_parallelism,
            pip_install_packages="",
            **kwargs,
        )

    async def on_sandbox_ready(self, state, sandbox_id: str) -> None:
        state["sandbox_id"] = sandbox_id
        info = state.get("info", {})
        if not isinstance(info, dict):
            raise ValueError("Expected info to be a dict during sandbox setup.")

        repo = str(info.get("repo", "")).strip()
        pr_number = info.get("pr_number")
        repo_dir = str(
            state.get("rlm_fs_root_remote")
            or info.get("sandbox_repo_dir")
            or DEFAULT_SANDBOX_REPO_DIR
        )
        clone_url = str(info.get("repo_clone_url") or f"https://github.com/{repo}.git")
        if not repo or pr_number in (None, ""):
            raise ValueError("Sandbox setup requires repo and pr_number in state['info'].")
        state["sandbox_repo_dir"] = repo_dir

        quoted_repo_dir = shlex.quote(repo_dir)
        quoted_clone_url = shlex.quote(clone_url)
        command = (
            "bash -lc '"
            "set -euo pipefail; "
            "if ! command -v git >/dev/null 2>&1 || ! command -v rg >/dev/null 2>&1; then "
            "export DEBIAN_FRONTEND=noninteractive; "
            "apt-get update >/dev/null; "
            "apt-get install -y git ripgrep ca-certificates >/dev/null; "
            "fi; "
            f"mkdir -p $(dirname {quoted_repo_dir}); "
            f"rm -rf {quoted_repo_dir}; "
            f"git clone --depth 1 {quoted_clone_url} {quoted_repo_dir}; "
            f"cd {quoted_repo_dir}; "
            f"git fetch --depth 1 origin pull/{pr_number}/head; "
            "git checkout --detach FETCH_HEAD'"
        )
        result = await self._executor._execute_sandbox_command(
            sandbox_id,
            command,
            timeout=max(self.max_startup_wait_seconds, 600),
        )
        exit_code = getattr(result, "exit_code", 0)
        if exit_code not in (0, None):
            stderr = (getattr(result, "stderr", "") or "").strip()
            stdout = (getattr(result, "stdout", "") or "").strip()
            raise RuntimeError(stderr or stdout or "Sandbox repo setup failed.")
