# Engineering Scorecard

A Claude skill that scores your company's developers and its most complex features out of 100, straight from git history.

**[Live demo report →](https://slasher190.github.io/engineering-scorecard/examples/roinet/report.html)**

Point it at your repos, local clones or GitHub repos it reads through the API without cloning, and it produces:

- **A developer ranking** on eight weighted parameters: difficulty of the code they wrote, hard-feature output, volume, breadth, ownership, tests, consistency and commit hygiene.
- **A feature ranking:** the hardest parts of your system scored on technical depth, domain risk, integration surface, size and tests, each with its lead developer and contributors.
- **A self-contained HTML report** with the overall score split by parameter, code per repo, a parameter heat table, feature scores, a who-built-what table, raw numbers and the method.

Claude does the parts a script can't:
- merging one person's several git identities
- spotting history that would be counted twice (submodules, split monorepos, vendored code)
- reading the code to decide how hard each module is
- choosing and rating the features that matter

The scripts do the counting, deterministically.

## Example

[`examples/roinet`](examples/roinet) is a real run across seven repos at Roinet, with developer names replaced by their rank:
- **Screenshots:** the [overview](examples/roinet/screenshots/overview.png) and the [feature ranking](examples/roinet/screenshots/features.png).
- **The full report:** [view it live](https://slasher190.github.io/engineering-scorecard/examples/roinet/report.html), or download [`report.html`](examples/roinet/report.html) and open it in a browser.

## Install

**Claude Code (plugin):**

```
/plugin marketplace add Slasher190/engineering-scorecard
/plugin install engineering-scorecard@engineering-scorecard
```

**Claude Code (personal skill):** copy `skills/engineering-scorecard` into `~/.claude/skills/`.

**Claude.ai or Claude Desktop:** zip the `skills/engineering-scorecard` folder and upload it under Settings → Capabilities → Skills.

## Use

Ask Claude something like:

- "Score our developers across `~/code/api`, `~/code/web` and `acme/auth-service` on GitHub (don't clone that one)."
- "Who built the most complex features in this codebase? Score them out of 100."
- "Add `~/code/payments` to last month's engineering scorecard and refresh it."

Claude will:
1. survey the authors
2. confirm identity merges with you
3. collect history
4. tier the modules after reading the code
5. score developers
6. pick and rate the complex features
7. hand you `report.html`

You can also run the script yourself:

```
python3 skills/engineering-scorecard/scripts/scorecard.py all --config config.json --out out
```

Commands: `survey`, `collect`, `modules`, `score`, `features`, `report` and `all`. The config schema is in [`references/config.md`](skills/engineering-scorecard/references/config.md), and every formula and rubric is in [`references/methodology.md`](skills/engineering-scorecard/references/methodology.md).

## Requirements

- Python 3.8+, standard library only
- `git`
- the [`gh` CLI](https://cli.github.com/), signed in, for repos read through the GitHub API

## Privacy

Everything runs locally:
- **Writes:** only to the output folder you choose.
- **Network:** only read-only GitHub API calls, for repos you list as `github`. No other network calls.
- **Report:** contains developer names and numbers, so share it as you would any internal document.

## What the scores mean

They measure the git record: what was written, where, how hard that area is, and how it was committed.

They don't measure code quality, design, reviews, mentoring, incident work or business impact. Use them to understand who built what and where complexity lives, not on their own to judge people. The report says the same.

## License

MIT
