from __future__ import annotations

from textwrap import dedent


def build_system_prompt(
    *,
    root_prompt_verbosity: str,
    max_turns: int,
    sub_llm_max_turns: int,
    max_sub_llm_parallelism: int,
) -> str:
    if root_prompt_verbosity == "light":
        return dedent(
            f"""\
            You have the `call_python_repl` tool and a filesystem available to you.

            This task is iterative: explore the repository step by step, inspect output, and refine your search.
            After a quick orientation step, prefer the provided search functions over ad hoc Python exploration.
            In particular, use `ripgrep(...)`, `glob_files(...)`, and `read_file_range(...)` inside the REPL.

            The task is only complete when you call `submit_files(files=[...])` from inside the REPL.
            Submit only repo-relative file paths, with one list element per file and no prose.

            You have at most {max_turns} main turns. Use the functions early, and use `llm_batch()` when semantic help would save time.
            """
        ).strip()

    if root_prompt_verbosity == "medium":
        return dedent(
            f"""\
            You have the `call_python_repl` tool and a filesystem available to you.

            This is an iterative environment. Explore the repository, inspect outputs, and update your plan as you learn more.
            After the first quick filesystem check, prefer the provided search functions to raw Python or subprocess calls.
            Use `ripgrep(...)` for text/symbol search, `glob_files(...)` for path discovery, and `read_file_range(...)` for focused inspection.

            For this environment, do not finish with a plain assistant message. The task is only complete when you call
            `submit_files(files=[...])` from inside the REPL with only repo-relative file paths.

            You have at most {max_turns} main turns. Work efficiently: search broadly first, narrow quickly, and submit once
            you have enough evidence.

            Use `llm_batch()` for semantic tasks like comparing candidate files, classifying snippets, or summarizing evidence.
            Prefer batching related prompts together instead of making many sequential calls. You can use up to
            {max_sub_llm_parallelism} parallel sub-LLM requests, each with at most {sub_llm_max_turns} turns.
            """
        ).strip()

    return dedent(
        f"""\
        You are operating in a Recursive Language Model (RLM) environment - an iterative Python REPL where you explore data step by step.

        A filesystem is available; explore it as needed.

        ## Critical: This is an ITERATIVE environment

        You will write code, see its output, then write more code based on what you learned. **Do NOT try to solve everything in one tool call.**
        Each tool call executes and returns output before you continue.

        Use the `call_python_repl` tool to execute Python code. The REPL maintains state across calls. See the tool description for available
        variables and functions.

        ## Workflow

        **Step 1: Explore the repository**
        ```python
        import os
        print(os.getcwd())
        print(os.listdir("."))
        ```
        Wait for output. Once you know the repository layout, stop wandering and start narrowing the search with the provided functions.

        **Step 2: Search efficiently using the root REPL tools**
        - Use the provided functions early. Do not spend many turns on repeated `os.listdir`, raw `glob`, or subprocess `rg` calls.
        - Use `glob_files(...)` to discover candidate paths by filename or directory shape.
        - Use `ripgrep(...)` as your default search primitive for exact strings, symbols, option names, error messages, or phrases from the report.
        - Use `read_file_range(...)` only after you have narrowed down to promising files.
        - Use hidden-file searches when the repo or report suggests dotfiles, metadata, or release/config files may matter.
        - A good default pattern is: `ripgrep(...)` or `glob_files(...)` first, then `read_file_range(...)`, then repeat.
        - If you have gone several turns without using the provided search functions, correct course immediately.

        **Step 3: Use sub-LLMs when semantic help would save turns**
        - Use `llm_batch()` for semantic tasks like summarization, snippet comparison, clustering candidate files, or checking whether a file
          looks relevant to the report.
        - Prefer batching related prompts together instead of making many sequential calls.
        - You can use up to {max_sub_llm_parallelism} parallel sub-LLM requests, each with at most {sub_llm_max_turns} turns.

        **Step 4: Finalize correctly**
        ```python
        submit_files(files=[
            "path/to/file_one.py",
            "path/to/file_two_test.py",
        ])
        ```
        This is the required completion path for this environment. Submit only repo-relative file paths. Do not submit prose, markdown, XML,
        bullets, or explanations.

        ## Important Rules

        1. **Do not end with a normal assistant message** - the rollout only finishes when you call `submit_files(files=[...])` from inside the REPL.
        2. **One step at a time** - make a small tool call, inspect output, then continue.
        3. **Use the provided root tools instead of ad hoc subprocess searches when possible** - they are faster, easier to read, and more likely to keep you on track.
        4. **You have at most {max_turns} main turns** - avoid wandering. Start broad, narrow quickly, and submit before you run out of budget.
        5. **Good answers often include more than core implementation files** - tests, docs, configs, metadata, and hidden files can all matter.
        6. **Do not dump whole files unnecessarily** - read focused slices and keep building a candidate set.
        7. **Use the functions more than raw filesystem code** - the intended workflow is built around `ripgrep(...)`, `glob_files(...)`, `read_file_range(...)`, `llm_batch()`, and `submit_files(...)`.
        """
    ).strip()
