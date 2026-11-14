# config.json

Only `repos` is required. Paths are relative to the config file unless absolute.

```jsonc
{
  "company": "Acme",                 // used in the report title
  "title": "Acme Engineering Scorecard",   // optional; overrides the report title
  "as_of": "2026-11-14",             // date shown in the report (default: today)
  "repos": [
    // A local clone. label is how the repo is named everywhere else.
    {"label": "api", "path": "../acme-api"},
    {"label": "web", "path": "../acme-web"},
    // A parent repo that also carries api/ and web/ history (submodules, or a split monorepo).
    // Changes under these prefixes are credited to the child repo, once.
    {"label": "platform", "path": "../acme-platform", "subtrees": {"api/": "api", "web/": "web"}},
    // A GitHub repo read through the API (gh CLI), never cloned. branch is optional:
    // without it, every branch is read (or only the default branch if all_branches is false).
    {"label": "auth", "github": "acme/auth-service", "branch": "main"}
  ],
  "all_branches": true,              // git log --all; false = current branch only
  "min_commits": 10,                 // developers below this are left out of the ranking

  // One person, several git names or emails -> one display name. Keys match name or email, any case.
  "aliases": {"jdoe": "Jane Doe", "jane@old-laptop.local": "Jane Doe"},
  "exclude_authors": ["release-bot"],   // added to the built-in bot list

  "skip_paths": ["^legacy/"],          // extra regexes for paths to ignore everywhere
  "vendored": [{"repo": "web", "pattern": "^packages/shared-contracts/"}],   // copies of another repo's code

  // Custom module names, tried before the folder heuristics. {1} = first capture group.
  "modules": [{"repo": "web", "pattern": "^src/features/([^/]+)/", "name": "{1}"}],
  "auto_split": 0.10,                // split a module holding >10% of its repo (and 5,000+ lines) one level deeper; 0 = off

  // Difficulty tiers: [tier, regex on "repo:module"], first match wins, before the defaults.
  "tiers": [
    [5, "^api:(payments|ledger|auth)$"],
    [4, "^web:checkout"],
    [2, "^web:admin-ui$"]
  ],
  "default_tiers": true,             // false = only your rules, everything else tier 2

  "weights": {"difficulty": 0.25, "hard_output": 0.20, "volume": 0.10, "breadth": 0.10,
              "ownership": 0.10, "tests": 0.10, "consistency": 0.10, "hygiene": 0.05},
  "feature_weights": {"depth": 0.30, "risk": 0.25, "integration": 0.20, "size": 0.15, "tests": 0.10},

  "features": [
    {
      "name": "Payments and ledger",
      "area": "Money",
      "what": "Card and bank payments, double-entry ledger, refunds and daily reconciliation",
      "depth": 5, "risk": 5, "integration": 4,          // 1-5, see methodology.md
      "paths": [{"repo": "api", "path": "src/modules/payments"},
                {"repo": "api", "path": "src/modules/ledger"},
                {"repo": "web", "path": "src/features/checkout"}]
    },
    {
      "name": "Cloud infrastructure and CI/CD",
      "area": "Platform",
      "what": "Terraform for the production cloud, CI pipelines and deploys",
      "depth": 4, "risk": 5, "integration": 5,
      "count_config_files": true,                        // count YAML/JSON/Dockerfiles toward size
      "paths": [{"repo": "platform", "path": "infra"}, {"repo": "api", "path": ".github"}]
    }
  ],
  "max_api_files": 400,              // GitHub features with more files get sizes estimated from bytes
  "report_notes": ["Anything else readers should know, shown under the method."],

  // Rarely needed overrides
  "test_pattern": "(\\.spec\\.|\\.test\\.|(^|/)tests?/)",
  "hygiene_pattern": "^(\\[[A-Z]+-\\d+\\]|(feat|fix|chore)(\\(.+\\))?:)"
}
```

## Outputs (in `--out`)

| File | Made by | Holds |
|---|---|---|
| `changes.jsonl` | collect | One row per counted file change: dev, date, repo, path, lines added |
| `commits.jsonl` | collect | One row per counted commit: dev, date, subject, repo, lines added |
| `cache/github/…` | collect, features | GitHub API responses (delete to refresh) |
| `modules.json` | modules | Every module with lines, tier and top authors |
| `developer-scores.json` | score | `rows` (one per developer: `overall`, `s_<parameter>`, raw metrics, `lines_<repo>`), `repos`, `weights`, `below_min_commits` |
| `feature-scores.json` | features | `rows` (one per feature: `score`, `s_<part>`, ratings, lead, shares, sizes), `weights` |
| `report.html` | report | The self-contained report |
