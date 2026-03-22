# GitHub PR Scraping Starter

This folder holds a small, scalable starter for collecting issue/PR-linked code-retrieval examples from GitHub repositories that are common in SWE-Bench-style benchmarks.

The current collection strategy is:

- scan merged pull requests from a repo
- keep PRs with `min_non_test_files <= non_test_file_count <= max_non_test_files`
- prefer `5-15` non-test files, with a hard floor above `3`
- attach linked issues when GitHub exposes them, and fall back to PR-body heuristics when needed
- export both JSONL and CSV

## Files

- `scrape_github_prs.py` - collector CLI
- `repos.txt` - starter repo seed list
- `reputable_recent_repos.txt` - broader seed list spanning reputable, active repos across languages
- `sample_curated.jsonl` / `sample_curated.csv` - representative output from a small run

## Recommended usage

Check GitHub auth first:

```bash
gh auth status
```

Run a small sample sweep:

```bash
python data_collection/scrape_github_prs.py \
  --repos-file data_collection/repos.txt \
  --out-jsonl data_collection/sample_prs.jsonl \
  --out-csv data_collection/sample_prs.csv \
  --min-non-test-files 4 \
  --max-non-test-files 15 \
  --max-records-per-repo 50 \
  --limit 20
```

If you want a narrower seed set:

```bash
python data_collection/scrape_github_prs.py \
  --repo pallets/flask \
  --repo psf/requests \
  --repo pytest-dev/pytest \
  --out-jsonl data_collection/flask_requests_pytest.jsonl \
  --out-csv data_collection/flask_requests_pytest.csv
```

## Output schema

Each row contains:

- repository and PR metadata
- linked issue metadata when available
- all changed files
- non-test changed files
- test changed files
- simple line-count stats
- a derived `query_text` field that prefers linked issue title and body when GitHub exposes them, and otherwise falls back to PR text

The JSONL file is the primary output. The CSV is a convenient flattened mirror for quick inspection.

## Notes

- The script uses `gh api graphql` when available and authenticated.
- For PRs with more than 100 changed files, the script fetches additional file pages so large multi-file changes are not silently truncated by the initial GraphQL query.
- If `gh` is unavailable, it falls back to the public REST API for a best-effort scrape, but that path is slower and more rate-limited.
- The file classification heuristic is intentionally conservative and can be tuned later.
