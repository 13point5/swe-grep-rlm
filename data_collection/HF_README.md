---
pretty_name: swe-grep-rlm-reputable-recent-5plus
task_categories:
- text-retrieval
language:
- en
tags:
- code
- software-engineering
- issue-localization
- bug-localization
- github
- retrieval
size_categories:
- 100<n<1K
---

# swe-grep-rlm-reputable-recent-5plus

This dataset is a GitHub-mined collection of issue- or PR-linked retrieval examples for repository-level code search and localization.

Each row is built from a merged pull request in a reputable, actively maintained open-source repository. The target labels are the PR's changed files, with a focus on non-test files.

## Summary

- Rows: 799
- Repositories: 46
- Query source:
  - 519 rows use linked issue title/body when GitHub exposed it
  - 280 rows fall back to PR title/body
- Non-test file count:
  - minimum: 5
  - median: 8
  - maximum: 264
- Distribution:
  - 501 rows with 5-10 non-test files
  - 169 rows with 11-20 non-test files
  - 129 rows with 21+ non-test files

## Files

- `reputable_recent_5plus.jsonl`: primary dataset file
- `reputable_recent_5plus.csv`: flattened mirror for quick inspection
- `reputable_recent_repos.txt`: repo seed list used for the sweep
- `scrape_github_prs.py`: collection script

## Schema

Each example includes:

- `repo`
- `pr_number`
- `pr_url`
- `pr_title`
- `pr_body`
- `merged_at`
- `query_text`
- `query_source`
- `linked_issues`
- `file_count`
- `non_test_file_count`
- `test_file_count`
- `files`
- `non_test_files`
- `test_files`
- `additions`
- `deletions`
- `source`

## Construction Notes

- Only merged PRs were considered.
- Rows were filtered to keep `non_test_file_count >= 5`.
- The collector prefers linked issue title/body when available, and otherwise falls back to PR text.
- For PRs with more than 100 changed files, additional file pages were fetched so the file lists are not truncated at the initial GraphQL response.
- File-type classification is heuristic. In particular, "non-test" is broader than "implementation-only" and may still include docs, config, changelog, or generated artifacts in some projects.

## Intended Use

This dataset is designed for:

- repository-level code retrieval
- issue localization
- training or evaluating rerankers and retrieval policies
- weak supervision for query-to-files tasks

It is not a gold-standard human-annotated benchmark. Labels come from merged PR diffs and linked issue/PR metadata.

## Provenance

The data is derived from public GitHub repositories and metadata from their issues and pull requests. Upstream repository licenses vary by project.
