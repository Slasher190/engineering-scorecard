---
name: engineering-scorecard
description: Score a company's developers and its most complex features out of 100 from git history, across any number of local repos and GitHub repos (read through the API, no clone), and produce a ranked report with charts. Use this whenever someone wants to know who built what, which developer did the hardest work, which features are most complex, how contribution splits across repos, or wants an engineering team scorecard, contributor analytics, developer leaderboard, codebase ownership map or "complexity by developer" report, even if they don't say "scorecard". Also use it to refresh or extend such a report with more repos.
---

# Engineering scorecard

Turns git history into two rankings, each out of 100:

- **Developers**, on eight weighted parameters: difficulty, hard-feature output, volume, breadth, ownership, tests, consistency and commit hygiene.
- **Complex features**, on technical depth, domain risk and integration surface (which you rate by reading the code), plus measured size and tests, with the lead developer of each.

The heavy lifting is in `scripts/scorecard.py` (standard-library Python). Your job is the judgment the script can't make: which repos belong together, which git names are one person, how hard each module is, and which features matter. Those choices decide whether the result is fair, so spend your effort there.

`references/methodology.md` has every formula and the rubrics for tiers and feature ratings. `references/config.md` has the config schema. Read both before step 4.

## Be straight about what this measures

The scores describe the git record: what was written, where, how hard that area is, and how it was committed. They don't see code quality, design, reviews, mentoring, incidents handled or business impact. Say so when you present results, and steer away from using the ranking alone for pay or performance decisions. The report carries the same caveats.

## Requirements

`python3` (3.8+) and `git`. For GitHub repos that shouldn't be cloned, the `gh` CLI signed in with read access. Nothing is written outside the output folder, and nothing is sent anywhere except read-only GitHub API calls.

## Workflow

Work in a folder outside the repos being scored, for example `./scorecard/`, holding `config.json` and the output folder. `SC` below means `python3 <this skill>/scripts/scorecard.py`.

### 1. Find the repos

Ask which repos to include, or find them: local paths, plus GitHub `owner/name` for repos the user wants read without cloning. A `gh api repos/<owner>/<name>` 404 usually means the user hasn't accepted an invitation yet. Accepting it adds them as a collaborator, so ask before you do it (`gh api -X PATCH user/repository_invitations/<id>`).

Look for shared history before you write the config, because counting the same change twice inflates whoever wrote it:

- A parent repo with git submodules, or a monorepo that was later split, often carries the children's history under `child/` paths. List those as `subtrees` on the parent (`{"server/": "server"}`). The script then credits each change once, to the child repo.
- A package copied (vendored) from one repo into another goes in `vendored`. So does a repo or folder that was seeded by copying another team's code. Check big first commits ("from X", "copy of", "port") and compare a few files with the original. If most lines match, list the copied folder in `vendored`, so the copier isn't credited with the original author's work.

### 2. Write the config

Copy `assets/config.example.json` and fill in `company`, `repos` and `as_of`. Leave `tiers` and `features` empty for now.

### 3. Merge identities

Run `SC survey --config config.json`. It lists every author with their emails and repos and suggests merges where the emails match. Put each person's other names or emails in `aliases`, mapping to one display name. Merges backed by a shared email are safe. Ask the user about anything that rests only on similar names. Bots are excluded by default. Add others to `exclude_authors`.

### 4. Collect, then set difficulty tiers

```
SC collect --config config.json --out out
SC modules --config config.json --out out --limit 80
```

`modules` prints each module's lines, current tier and top authors. Defaults come from folder names (payments, auth, ledger and infra score high; ui, styles, docs and landing score low). Those defaults are a starting guess, not a judgment. Go through the modules that hold most of the lines and give each a tier:

- **Do read the code.** For any module whose name doesn't make its difficulty obvious, skim its largest files and header comments. A folder named `engine` might be a templating helper, and one named `utils` might hold the pricing core.
- **Then write the rules.** Add `tiers` rules to the config (regex on `repo:module`) and re-run `modules` until the big ones look right.
- **Tier by the work, not by who did it.** Use the rubric in `references/methodology.md`, and apply the same tier to every module of the same kind whoever wrote it.
- **Split catch-all folders.** A module that is too coarse (one folder holding many features) gets split automatically when it exceeds `auto_split`. You can also define modules yourself with `modules` rules.

### 5. Score developers

`SC score --config config.json --out out` writes `developer-scores.json` and prints the ranking. Developers under `min_commits` (default 10) are left out and listed in the report. Check the top modules of the leaders against what you know. A surprise usually means a missing alias, a missing `subtrees` entry or a wrong tier, not a surprising person.

### 6. Pick and rate the complex features

From the module list and the code, choose 15–30 features that a technical leader would recognise as the hard parts of the system: money flows, identity and access, core engines, major integrations, infrastructure, AI. Include a few simpler ones too, so the scale means something. For each, add to `features`:

- `name`, `area` and a one-line `what` in plain words
- `paths`: the folders that make it up, possibly across repos (frontend + backend + connector for one journey)
- `depth`, `risk` and `integration`, 1–5 per the rubric in `references/methodology.md`, rated from the code you read
- `count_config_files: true` for infrastructure features, so YAML and JSON configs count toward size

Then run `SC features --config config.json --out out`. Lead developer and shares come from the history, not from you.

### 7. Report

`SC report --config config.json --out out` writes `out/report.html`: a self-contained page with the podium, overall score split by parameter, lines per repo, a parameter heat table, feature scores, a who-built-what table, raw numbers and the method with caveats. Hand that file to the user.

If the host can publish pages or dashboards, you can also publish from `developer-scores.json` and `feature-scores.json`. Keep the caveats with the numbers.

### 8. Tell the user what it found

In your reply, give:

- **The ranking:** a short table of the top developers with overall scores and one line on what drove each.
- **The features:** the top features with their leads.
- **Corrections:** anything you corrected along the way (merged identities, de-duplicated history, re-tiered modules).
- **Limits:** what the numbers can't see.

Mention which choices were yours (tiers, feature ratings), so the user can push back. Offer to re-score after any change.

## Refreshing and extending

To add a repo, add it to `repos`, run `collect` again and repeat steps 4–7 for the new modules. GitHub API responses are cached under `out/cache/`, so re-runs are quick. Delete that folder to pick up new commits. To change weights, set `weights` or `feature_weights` in the config. Every re-run is deterministic for the same history and config.

## Troubleshooting

- **One person dominates every parameter.** Check for history counted twice (`subtrees`, `vendored`), or a bulk import commit. `collect` prints nothing for those, so look at `commits.jsonl` sorted by `added`.
- **A big module sits at tier 2.** It has no tier rule yet. Add one.
- **GitHub sizes say estimated.** The feature had more than `max_api_files` files, so lines were estimated from bytes. Raise the limit if exact counts matter.
- **A commit lists 300+ files from GitHub.** The API may have cut the list short. Clone that repo if exact numbers matter and the user agrees.
