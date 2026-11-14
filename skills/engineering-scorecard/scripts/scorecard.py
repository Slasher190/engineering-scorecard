#!/usr/bin/env python3
"""Engineering scorecard: score developers and complex features out of 100 from git history.

Reads local git repos (git log) and GitHub repos (gh api, no clone), then writes:
  changes.jsonl / commits.jsonl  normalised history (collect)
  modules.json                   lines per module with tier and top authors (modules)
  developer-scores.json          eight parameters + overall per developer (score)
  feature-scores.json            complexity score per configured feature (features)
  report.html                    self-contained report with charts (report)

Usage:
  python3 scorecard.py survey   --config config.json
  python3 scorecard.py collect  --config config.json --out OUT
  python3 scorecard.py modules  --config config.json --out OUT
  python3 scorecard.py score    --config config.json --out OUT
  python3 scorecard.py features --config config.json --out OUT
  python3 scorecard.py report   --config config.json --out OUT
  python3 scorecard.py all      --config config.json --out OUT

Only the standard library is used. GitHub repos need the `gh` CLI, signed in.
Nothing is written anywhere except OUT, and nothing is sent anywhere.
"""
import argparse, datetime as dt, html, json, math, os, re, subprocess, sys
from collections import defaultdict
from pathlib import Path

# ----------------------------------------------------------------------------- defaults

SKIP = (r"(^|/)(dist|build|out|target|vendor|third_party|logs?|node_modules|\.next|\.nuxt|coverage|__pycache__|"
        r"\.npm-cache|\.pnpm-store|tmp|\.gradle|\.expo|\.terraform|\.venv|venv)/|lock|"
        r"\.(json|csv|tsv|html?|md|mdx|rst|txt|svg|snap|log|map|ya?ml|png|jpe?g|webp|gif|ico|pdf|xlsx?|pptx?|docx?|"
        r"mp4|mov|mp3|wav|zip|gz|tar|woff2?|ttf|eot|tfstate|example|sample)$|\.min\.")
# Infra and delivery files are kept even when their extension (yml, json) would be skipped as data.
INFRA = (r"(^|/)(\.github/|\.gitlab-ci|\.circleci/|infra/|infrastructure/|terraform/|deploy/|deployment/|k8s/|"
         r"kubernetes/|helm/|charts/|monitoring/|docker/|ansible/|pulumi/)|"
         r"(^|/)(Dockerfile[^/]*|docker-compose[^/]*\.ya?ml|compose\.ya?ml|deploy[^/]*\.sh|Jenkinsfile|Procfile|"
         r"nginx[^/]*\.conf|Caddyfile|serverless\.ya?ml|cloudbuild\.ya?ml|buildspec\.ya?ml)$")
INFRA_KEEP = r"\.(ya?ml|json|tf|hcl|sh|py|js|mjs|ts|conf|service|path|timer|toml|ini)$|(^|/)(Dockerfile[^/]*|Jenkinsfile|Procfile|Caddyfile)$"
IAC = r"(^|/)(infra|infrastructure|terraform|pulumi|helm|charts|k8s|kubernetes|ansible)/"
TEST = r"(\.spec\.|\.test\.|_test\.(go|py|rb)$|(^|/)tests?/|(^|/)e2e/|__tests__|(^|/)test_[^/]*\.py$|/testing/|(^|/)spec/)"
HYGIENE = (r"^(\[[A-Z][A-Z0-9]+-\d+\]|[A-Z][A-Z0-9]+-\d+[: ]|"
           r"(feat|fix|chore|refactor|test|tests|docs|ci|perf|style|build|revert)(\([^)]*\))?!?:)")
BOTS = r"(\[bot\]$|^dependabot|^renovate|^github-actions|^snyk-bot|^greenkeeper)"
CODE_EXT = (r"\.(ts|tsx|js|jsx|mjs|cjs|py|go|rs|java|kt|kts|swift|rb|php|cs|scala|c|cc|cpp|h|hpp|m|mm|sql|prisma|"
            r"graphql|gql|proto|tf|hcl|sh|vue|svelte|dart|ex|exs|erl|clj|lua|r|jl)$")
CONFIG_EXT = r"\.(ya?ml|json|conf|service|path|toml|ini)$|(^|/)(Dockerfile[^/]*|Jenkinsfile|Procfile|Caddyfile)$"

MARKERS = {"modules", "features", "services", "packages", "apps", "components", "domains", "libs", "plugins",
           "handlers", "routes", "controllers", "internal", "pkg", "cmd", "workers", "jobs", "connectors"}
CONTAINERS = {"apps", "packages", "services", "libs"}
# Leading folders that say nothing about the feature (src/lib/..., src/main/java/com/acme/...).
GENERIC = {"src", "lib", "app", "source", "sources", "main", "java", "kotlin", "scala", "python", "go",
           "com", "org", "io", "net", "dev"}

# Difficulty tier rules, checked after the config's own `tiers`. Matched against the module name.
DEFAULT_TIERS = [
    (5, r"^infra$"),
    (5, r"(^|[/_.-])(pay(ment)?s?|payouts?|billing|ledger|wallets?|settlements?|invoic\w*|coins?|credits?|"
        r"auth\w*|sso|oidc|oauth\w*|identity|iam|security|crypto\w*|encrypt\w*|permissions?|rbac|acl|secrets?|kms)([/_.-]|$)"),
    (5, r"(^|[/_.-])(agents?|llm|rag|orchestrat\w*|workflows?|engines?|scheduler|graph|hierarchy|risk|fraud)([/_.-]|$)"),
    (4, r"^devops$"),
    (4, r"(integrations?|connectors?|adapters?|gateway|webhooks?|sync|outbox|queues?|kyc|compliance|onboarding|"
        r"migrations?|prisma|schema|database|db|cache|search|pricing|quotes?|polic(y|ies)|claims?|checkout|orders?)"),
    (1, r"(^|[/_.-])(ui|styles?|css|themes?|landing|marketing|i18n|locales?|translations?|assets|static|public|"
        r"docs?|examples?|fixtures|mocks?|stories|storybook|icons?|fonts?)([/_.-]|$)"),
    (3, r"(^|[/_.-])(tests?|e2e|specs?|api|admin|ops|reports?|analytics|mail|emails?|notifications?|audit|"
        r"common|shared|core|utils?|helpers?|lib)([/_.-]|$)"),
]
TIER_W = {1: 0.2, 2: 0.4, 3: 0.6, 4: 0.8, 5: 1.0}
WEIGHTS = {"difficulty": .25, "hard_output": .20, "volume": .10, "breadth": .10,
           "ownership": .10, "tests": .10, "consistency": .10, "hygiene": .05}
FEATURE_WEIGHTS = {"depth": .30, "risk": .25, "integration": .20, "size": .15, "tests": .10}
LABELS = {"difficulty": "Difficulty", "hard_output": "Hard-feature output", "volume": "Volume", "breadth": "Breadth",
          "ownership": "Ownership", "tests": "Tests", "consistency": "Consistency", "hygiene": "Commit hygiene"}
FLABELS = {"depth": "Technical depth", "risk": "Domain risk", "integration": "Integration surface",
           "size": "Size", "tests": "Tests"}


def die(msg):
    sys.exit(f"scorecard: {msg}")


class Cfg:
    def __init__(self, path):
        self.path = Path(path).resolve()
        c = json.loads(self.path.read_text())
        self.raw = c
        self.company = c.get("company", "Engineering")
        self.as_of = c.get("as_of") or dt.date.today().isoformat()
        self.repos = c.get("repos") or die("config has no repos")
        for r in self.repos:
            if "label" not in r or not ("path" in r or "github" in r):
                die(f"each repo needs a label and a path or github: {r}")
            if "path" in r:
                r["path"] = str((self.path.parent / os.path.expanduser(r["path"])).resolve())
        self.labels = [r["label"] for r in self.repos]
        self.all_branches = c.get("all_branches", True)
        self.min_commits = c.get("min_commits", 10)
        self.alias = {k.lower(): v for k, v in (c.get("aliases") or {}).items()}
        self.exclude = re.compile("|".join([BOTS] + [re.escape(x) for x in c.get("exclude_authors", [])]), re.I)
        self.skip = re.compile("|".join([SKIP] + c.get("skip_paths", [])))
        self.infra = re.compile(INFRA)
        self.infra_keep = re.compile(INFRA_KEEP)
        self.iac = re.compile(IAC)
        self.test = re.compile(c.get("test_pattern", TEST))
        self.hygiene = re.compile(c.get("hygiene_pattern", HYGIENE))
        self.vendored = [(v["repo"], re.compile(v["pattern"])) for v in c.get("vendored", [])]
        self.module_rules = [(m["repo"], re.compile(m["pattern"]), m.get("name", "{1}")) for m in c.get("modules", [])]
        self.tiers = [(int(t), re.compile(rx, re.I)) for t, rx in c.get("tiers", [])]
        self.default_tiers = [(t, re.compile(rx, re.I)) for t, rx in DEFAULT_TIERS] if c.get("default_tiers", True) else []
        self.weights = {**WEIGHTS, **(c.get("weights") or {})}
        self.fweights = {**FEATURE_WEIGHTS, **(c.get("feature_weights") or {})}
        self.features = c.get("features", [])
        self.max_api_files = c.get("max_api_files", 400)
        # A module holding more than this share of its repo's lines (and 5,000+ lines) is split one level deeper.
        self.auto_split = c.get("auto_split", 0.10)
        self.split = set()

    def who(self, name, email=""):
        for k in (email.lower(), name.lower()):
            if k and k in self.alias:
                return self.alias[k]
        return name

    def repo(self, label):
        for r in self.repos:
            if r["label"] == label:
                return r
        die(f"unknown repo label {label!r}")

    def _module(self, repo, path):
        """(module name, the folder below it or None). Config rules first, then folder heuristics."""
        for rl, rx, name in self.module_rules:
            if rl in (repo, "*"):
                m = rx.search(path)
                if m:
                    return re.sub(r"\{(\d)\}", lambda g: m.group(int(g.group(1))) or "", name), None
        if self.infra.search(path):
            return ("infra" if self.iac.search(path) else "devops"), None
        segs = path.split("/")[:-1]
        if not segs:
            return "(root files)", None
        parts, i, end = [], 0, None
        while i < len(segs) and len(parts) < 2:
            if segs[i] in MARKERS and i + 1 < len(segs):
                parts.append(segs[i + 1]); end = i + 2
                if segs[i] not in CONTAINERS:
                    break
                i += 2
                continue
            i += 1
        if parts:
            return "/".join(parts), (segs[end] if end < len(segs) else None)
        j = 0
        while j < len(segs) - 1 and segs[j] in GENERIC:
            j += 1
        return segs[j], (segs[j + 1] if j + 1 < len(segs) else None)

    def prepare(self, changes):
        """Find catch-all modules (over auto_split of their repo's lines) to split one level deeper."""
        if not self.auto_split:
            return
        size, repo_total = defaultdict(int), defaultdict(int)
        for c in changes:
            size[(c["repo"], self._module(c["repo"], c["path"])[0])] += c["added"]
            repo_total[c["repo"]] += c["added"]
        self.split = {k for k, n in size.items() if n >= 5000 and n > self.auto_split * repo_total[k[0]]}

    def module(self, repo, path):
        name, below = self._module(repo, path)
        if (repo, name) in self.split and below:
            return f"{name}/{below}"
        return name

    def tier(self, repo, module):
        key = f"{repo}:{module}"
        for t, rx in self.tiers:
            if rx.search(key):
                return t
        for t, rx in self.default_tiers:
            if rx.search(module):
                return t
        return 2


def out_dir(args):
    p = Path(args.out).resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        die(f"{' '.join(cmd[:4])}… failed: {r.stderr.strip()[:400]}")
    return r.stdout


def unrename(path):
    """git numstat writes renames as a/{old => new}/b or old => new."""
    path = path.strip('"')
    m = re.match(r"^(.*)\{(.*) => (.*)\}(.*)$", path)
    if m:
        return re.sub("//+", "/", m.group(1) + m.group(3) + m.group(4))
    if " => " in path:
        return path.split(" => ")[1]
    return path


# ----------------------------------------------------------------------------- history sources

def git_history(cfg, repo):
    args = ["git", "-C", repo["path"], "log", "--no-merges", "--numstat", "--date=short",
            "--format=@@%aN%x09%aE%x09%ad%x09%s"]
    if cfg.all_branches:
        args.insert(4, "--all")
    for block in run(args).split("@@")[1:]:
        head, *rows = block.strip("\n").split("\n")
        name, email, date, subj = (head.split("\t", 3) + ["", "", "", ""])[:4]
        files = []
        for r in rows:
            parts = r.split("\t")
            if len(parts) == 3 and parts[0] != "-":
                files.append((int(parts[0]), unrename(parts[2])))
        yield name, email, date, subj, files


def gh_cache(out, repo):
    p = out / "cache" / "github" / repo["github"].replace("/", "__")
    p.mkdir(parents=True, exist_ok=True)
    return p


def gh_shas(repo, all_branches):
    gh = repo["github"]
    branches = [repo["branch"]] if repo.get("branch") else []
    if all_branches and not repo.get("branch"):
        branches = run(["gh", "api", "--paginate", f"repos/{gh}/branches?per_page=100", "--jq", ".[].name"]).split()
    if not branches:
        branches = [run(["gh", "api", f"repos/{gh}", "--jq", ".default_branch"]).strip()]
    shas = []
    for b in branches:
        for s in run(["gh", "api", "--paginate", f"repos/{gh}/commits?sha={b}&per_page=100", "--jq", ".[].sha"]).split():
            if s not in shas:
                shas.append(s)
    return shas


def github_history(cfg, repo, out):
    cache = gh_cache(out, repo)
    shas = gh_shas(repo, cfg.all_branches)
    print(f"  {repo['github']}: {len(shas)} commits from the GitHub API", file=sys.stderr)
    for sha in shas:
        f = cache / f"{sha}.json"
        if not f.exists():
            f.write_text(run(["gh", "api", f"repos/{repo['github']}/commits/{sha}"]))
        c = json.loads(f.read_text())
        if len(c.get("parents", [])) > 1:
            continue
        a = c["commit"]["author"]
        files = [(x.get("additions", 0), x["filename"]) for x in c.get("files", [])]
        if len(files) >= 300:
            print(f"  note: {sha[:8]} lists 300+ files; GitHub may have cut the list short", file=sys.stderr)
        yield a.get("name", ""), a.get("email", ""), a["date"][:10], c["commit"]["message"].split("\n")[0], files


# ----------------------------------------------------------------------------- collect

def cmd_collect(cfg, args):
    out = out_dir(args)
    # Repos that carry other repos' history as subtrees go last, so their copies are the duplicates.
    order = sorted(cfg.repos, key=lambda r: bool(r.get("subtrees")))
    seen, n_changes, n_commits = set(), 0, 0
    with open(out / "changes.jsonl", "w") as ch, open(out / "commits.jsonl", "w") as co:
        for repo in order:
            label = repo["label"]
            print(f"collecting {label}", file=sys.stderr)
            src = github_history(cfg, repo, out) if "github" in repo else git_history(cfg, repo)
            subtrees = sorted((repo.get("subtrees") or {}).items(), key=lambda kv: -len(kv[0]))
            for name, email, date, subj, files in src:
                if cfg.exclude.search(name) or cfg.exclude.search(email):
                    continue
                dev = cfg.who(name, email)
                kept = []
                for added, path in files:
                    home, rel = label, path
                    for prefix, target in subtrees:
                        if path.startswith(prefix):
                            home, rel = target, path[len(prefix):]
                            break
                    if any(vl == home and vr.search(rel) for vl, vr in cfg.vendored):
                        continue
                    if cfg.skip.search(rel) and not (cfg.infra.search(rel) and cfg.infra_keep.search(rel) and "lock" not in rel):
                        continue
                    kept.append((added, home, rel))
                fresh = []
                for added, home, rel in kept:
                    k = (dev, date, subj, home, rel, added)
                    if k not in seen:
                        seen.add(k)
                        fresh.append((added, home, rel))
                if kept and not fresh:
                    continue                       # the same change already counted from another repo or branch
                if not kept:
                    k = (dev, date, subj, label)
                    if k in seen:
                        continue
                    seen.add(k)
                co.write(json.dumps({"dev": dev, "date": date, "subject": subj, "repo": label,
                                     "added": sum(a for a, _, _ in fresh)}) + "\n")
                n_commits += 1
                for added, home, rel in fresh:
                    ch.write(json.dumps({"dev": dev, "date": date, "repo": home, "path": rel, "added": added}) + "\n")
                    n_changes += 1
    print(f"wrote {n_commits} commits and {n_changes} file changes to {out}", file=sys.stderr)


def load_history(out, cfg=None):
    if not (out / "changes.jsonl").exists():
        die(f"no changes.jsonl in {out}; run collect first")
    changes = [json.loads(l) for l in open(out / "changes.jsonl")]
    if cfg is not None:
        cfg.prepare(changes)
    commits = [json.loads(l) for l in open(out / "commits.jsonl")]
    return changes, commits


# ----------------------------------------------------------------------------- survey

def cmd_survey(cfg, args):
    """Authors per repo (to build aliases) and the biggest top-level folders (to understand the layout)."""
    people = defaultdict(lambda: {"commits": 0, "emails": set(), "repos": set()})
    for repo in cfg.repos:
        if "github" in repo:
            rows = run(["gh", "api", "--paginate", f"repos/{repo['github']}/contributors?per_page=100",
                        "--jq", '.[] | "\\(.login)\\t\\(.contributions)"']).splitlines()
            for row in rows:
                login, n = row.split("\t")
                p = people[login]; p["commits"] += int(n); p["repos"].add(repo["label"]); p["emails"].add("(github login)")
            continue
        args_ = ["git", "-C", repo["path"], "log", "--no-merges", "--format=%aN%x09%aE"]
        if cfg.all_branches:
            args_.insert(4, "--all")
        for line in run(args_).splitlines():
            name, email = (line.split("\t") + [""])[:2]
            p = people[name]; p["commits"] += 1; p["emails"].add(email); p["repos"].add(repo["label"])
    print("Authors (name · commits · emails · repos). Merge people with several names in `aliases`:")
    for name, p in sorted(people.items(), key=lambda kv: -kv[1]["commits"]):
        bot = "  [bot, excluded]" if cfg.exclude.search(name) else ""
        print(f"  {name} · {p['commits']} · {', '.join(sorted(p['emails']))} · {' '.join(sorted(p['repos']))}{bot}")
    by_email = defaultdict(set)
    for name, p in people.items():
        for e in p["emails"]:
            if "@" in e:
                by_email[e.lower()].add(name)
                by_email[e.lower().split("@")[0].split("+")[-1]].add(name)
    groups = {tuple(sorted(v)) for v in by_email.values() if len(v) > 1}
    if groups:
        print("\nLikely the same person (shared email or email name):")
        for g in sorted(groups):
            print("  " + " = ".join(g))


# ----------------------------------------------------------------------------- modules

def module_table(cfg, changes):
    mods = defaultdict(lambda: defaultdict(int))
    for c in changes:
        mods[(c["repo"], cfg.module(c["repo"], c["path"]))][c["dev"]] += c["added"]
    rows = []
    for (repo, mod), by in mods.items():
        tot = sum(by.values())
        top = sorted(by.items(), key=lambda kv: -kv[1])[:3]
        rows.append({"repo": repo, "module": mod, "tier": cfg.tier(repo, mod), "lines": tot,
                     "top_authors": [{"dev": d, "share_pct": round(100 * n / tot)} for d, n in top]})
    rows.sort(key=lambda r: -r["lines"])
    return rows


def cmd_modules(cfg, args):
    out = out_dir(args)
    changes, _ = load_history(out, cfg)
    rows = module_table(cfg, changes)
    (out / "modules.json").write_text(json.dumps(rows, indent=1))
    limit = args.limit or 80
    print(f"{'lines':>8}  tier  module  (top authors)")
    for r in rows[:limit]:
        who = ", ".join(f"{a['dev']} {a['share_pct']}%" for a in r["top_authors"])
        print(f"{r['lines']:>8}  {r['tier']:>4}  {r['repo']}:{r['module']}  ({who})")
    print(f"\n{len(rows)} modules; full list in {out / 'modules.json'}", file=sys.stderr)


# ----------------------------------------------------------------------------- developer scores

def cmd_score(cfg, args):
    out = out_dir(args)
    changes, commits = load_history(out, cfg)
    lines = defaultdict(lambda: defaultdict(int))
    by_repo = defaultdict(lambda: defaultdict(int))
    tests, total = defaultdict(int), defaultdict(int)
    for c in changes:
        d = c["dev"]
        total[d] += c["added"]
        by_repo[d][c["repo"]] += c["added"]
        if cfg.test.search(c["path"]):
            tests[d] += c["added"]
        lines[d][(c["repo"], cfg.module(c["repo"], c["path"]))] += c["added"]
    days, ncommits, tidy = defaultdict(set), defaultdict(int), defaultdict(int)
    for c in commits:
        d = c["dev"]
        ncommits[d] += 1
        days[d].add(c["date"])
        if cfg.hygiene.search(c["subject"]):
            tidy[d] += 1
    devs = [d for d in ncommits if ncommits[d] >= cfg.min_commits and total[d] > 0]
    if not devs:
        die(f"no developer has {cfg.min_commits}+ commits; lower min_commits")
    tier = lambda key: cfg.tier(*key)
    owner = {}
    for m in {m for d in devs for m in lines[d]}:
        if sum(lines[d].get(m, 0) for d in devs) >= 800:
            owner[m] = max(devs, key=lambda d: lines[d].get(m, 0))
    raw = {}
    for d in devs:
        L, tot = lines[d], max(total[d], 1)
        raw[d] = {"difficulty": sum(v * tier(m) for m, v in L.items()) / tot,
                  "hard_output": sum(v * TIER_W[tier(m)] for m, v in L.items()),
                  "volume": total[d],
                  "breadth": sum(1 for v in L.values() if v >= 200),
                  "ownership": sum(tier(m) for m, o in owner.items() if o == d),
                  "tests": tests[d] / tot, "days": len(days[d]),
                  "hygiene": tidy[d] / max(ncommits[d], 1)}

    def rootnorm(k, p):            # share of the top developer, raised to p: diminishing returns on size
        top = max(r[k] for r in raw.values()) or 1
        return {d: 100 * (r[k] / top) ** p for d, r in raw.items()}

    def linnorm(k):
        top = max(r[k] for r in raw.values()) or 1
        return {d: 100 * r[k] / top for d, r in raw.items()}

    score = {"difficulty": {d: 100 * (r["difficulty"] - 1) / 4 for d, r in raw.items()},
             "hard_output": rootnorm("hard_output", 1 / 3), "volume": rootnorm("volume", 1 / 3),
             "breadth": linnorm("breadth"), "ownership": rootnorm("ownership", 1 / 2),
             "tests": {d: min(100, 100 * r["tests"] / 0.35) for d, r in raw.items()},
             "consistency": linnorm("days"),
             "hygiene": {d: 100 * r["hygiene"] for d, r in raw.items()}}
    rows = []
    for d in devs:
        s = {k: round(score[k][d], 1) for k in cfg.weights}
        top = sorted(((m, v) for m, v in lines[d].items() if not cfg.test.search(m[1] + "/")),
                     key=lambda kv: -kv[1] * TIER_W[tier(kv[0])])[:4]
        rows.append({"developer": d, "overall": round(sum(s[k] * w for k, w in cfg.weights.items()), 1),
                     **{f"s_{k}": v for k, v in s.items()},
                     "lines_added": total[d], "commits": ncommits[d], "active_days": len(days[d]),
                     "test_share_pct": round(100 * raw[d]["tests"], 1), "hygiene_pct": round(100 * raw[d]["hygiene"], 1),
                     "mean_tier": round(raw[d]["difficulty"], 2), "modules_200plus": raw[d]["breadth"],
                     "modules_led": sum(1 for o in owner.values() if o == d),
                     "repos": " ".join(l for l in cfg.labels if by_repo[d].get(l)),
                     **{f"lines_{l}": by_repo[d].get(l, 0) for l in cfg.labels},
                     "top_modules": ", ".join(m[1] for m, _ in top)})
    rows.sort(key=lambda r: -r["overall"])
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    skipped = sorted((d for d in ncommits if d not in devs), key=lambda d: -ncommits[d])
    doc = {"rows": rows, "repos": cfg.labels, "weights": cfg.weights, "as_of": cfg.as_of,
           "below_min_commits": [{"developer": d, "commits": ncommits[d]} for d in skipped]}
    (out / "developer-scores.json").write_text(json.dumps(doc, indent=1))
    for r in rows:
        print(f"{r['rank']:>3}. {r['developer']:<28} {r['overall']:>5}")


# ----------------------------------------------------------------------------- feature scores

def local_files(base):
    if base.is_file():
        return [base]
    return [f for f in base.rglob("*") if f.is_file()]


def gh_tree(cfg, repo, out):
    f = gh_cache(out, repo) / "tree.json"
    if not f.exists():
        branch = repo.get("branch") or run(["gh", "api", f"repos/{repo['github']}", "--jq", ".default_branch"]).strip()
        f.write_text(run(["gh", "api", f"repos/{repo['github']}/git/trees/{branch}?recursive=1"]))
    return [t for t in json.loads(f.read_text())["tree"] if t["type"] == "blob"], f


def gh_lines(cfg, repo, out, path):
    """Line count of one file through the contents API, cached."""
    cache = gh_cache(out, repo) / "lines.json"
    known = json.loads(cache.read_text()) if cache.exists() else {}
    if path not in known:
        branch = repo.get("branch") or ""
        ref = f"?ref={branch}" if branch else ""
        text = run(["gh", "api", "-H", "Accept: application/vnd.github.raw", f"repos/{repo['github']}/contents/{path}{ref}"])
        known[path] = text.count("\n") + (0 if text.endswith("\n") or not text else 1)
        cache.write_text(json.dumps(known))
    return known[path]


def cmd_features(cfg, args):
    out = out_dir(args)
    if not cfg.features:
        die("config has no features; add them (see references/config.md) and run again")
    changes, _ = load_history(out, cfg)
    code_rx, conf_rx = re.compile(CODE_EXT), re.compile(CONFIG_EXT)
    junk = re.compile(r"lock|tfstate|(^|/)(node_modules|dist|build|\.terraform|__pycache__|vendor)/")
    rows, estimated_any = [], False
    for f in cfg.features:
        infra = bool(f.get("count_config_files"))
        code = tests = 0
        estimated = False
        by = defaultdict(int)
        for p in f["paths"]:
            repo = cfg.repo(p["repo"])
            folder = p["path"].strip("/")
            ok = lambda rel: (code_rx.search(rel) or (infra and conf_rx.search(rel))) and not junk.search(rel)
            if "github" in repo:
                blobs, _ = gh_tree(cfg, repo, out)
                hits = [b for b in blobs if (b["path"] == folder or b["path"].startswith(folder + "/")) and ok(b["path"])]
                fetch = len(hits) <= cfg.max_api_files
                estimated |= not fetch
                for b in hits:
                    n = gh_lines(cfg, repo, out, b["path"]) if fetch else round(b.get("size", 0) / 38)
                    if cfg.test.search(b["path"]): tests += n
                    else: code += n
            else:
                base = Path(repo["path"]) / folder
                if not base.exists():
                    print(f"  warning: {p['repo']}:{folder} does not exist", file=sys.stderr)
                    continue
                for fp in local_files(base):
                    rel = str(fp.relative_to(repo["path"]))
                    if not ok(rel):
                        continue
                    try:
                        n = sum(1 for _ in open(fp, errors="ignore"))
                    except OSError:
                        continue
                    if cfg.test.search(rel): tests += n
                    else: code += n
            for c in changes:
                if c["repo"] == p["repo"] and (c["path"] == folder or c["path"].startswith(folder + "/")) \
                        and not cfg.test.search(c["path"]):
                    by[c["dev"]] += c["added"]
        estimated_any |= estimated
        tot = sum(by.values()) or 1
        ranked = sorted(by.items(), key=lambda kv: -kv[1])
        rows.append({"feature": f["name"], "area": f.get("area", ""), "what": f.get("what", ""),
                     "lead": ranked[0][0] if ranked else "—",
                     "lead_share_pct": round(100 * ranked[0][1] / tot) if ranked else 0,
                     "others": ", ".join(f"{d} {round(100 * n / tot)}%" for d, n in ranked[1:4] if n / tot >= 0.05),
                     "code_lines": code, "test_lines": tests, "size_estimated": estimated,
                     "depth": int(f["depth"]), "risk": int(f["risk"]), "integration": int(f["integration"])})
    top = max((r["code_lines"] for r in rows), default=1) or 1
    w = cfg.fweights
    for r in rows:
        r["s_depth"] = (r["depth"] - 1) * 25
        r["s_risk"] = (r["risk"] - 1) * 25
        r["s_integration"] = (r["integration"] - 1) * 25
        r["s_size"] = round(100 * (r["code_lines"] / top) ** 0.5, 1)
        r["s_tests"] = round(min(100, 100 * r["test_lines"] / max(r["code_lines"], 1) / 0.8), 1)
        r["score"] = round(sum(r[f"s_{k}"] * w[k] for k in w), 1)
    rows.sort(key=lambda r: -r["score"])
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    (out / "feature-scores.json").write_text(json.dumps({"rows": rows, "weights": w, "as_of": cfg.as_of}, indent=1))
    for r in rows:
        print(f"{r['rank']:>3}. {r['feature']:<40} {r['score']:>5}  {r['lead']} {r['lead_share_pct']}%")
    if estimated_any:
        print("note: some GitHub sizes were estimated from file bytes (over max_api_files files)", file=sys.stderr)


# ----------------------------------------------------------------------------- report

PALETTE = ["#4269d0", "#efb118", "#ff725c", "#6cc5b0", "#3ca951", "#ff8ab7", "#a463f2", "#97bbf5", "#9c6b4e", "#9498a0"]
esc = lambda s: html.escape(str(s), quote=True)


def fmt(v):
    if isinstance(v, float):
        return f"{v:.1f}"
    if isinstance(v, int):
        return f"{v:,}"
    return esc(v)


def stacked_svg(rows, name_key, total_key, parts, max_value, aria, total_fmt=lambda v: f"{v:.1f}", unit="points"):
    """Horizontal stacked bars. parts: [(key, label, weight or None)]."""
    W, row_h, gap = 760, 24, 10
    longest = max((len(str(r[name_key])) for r in rows), default=10)
    ml = min(250, 26 + longest * 7.2)
    mr, mt, mb = 56, 4, 26
    inner = W - ml - mr
    H = mt + len(rows) * (row_h + gap) - gap + mb
    x = lambda v: inner * v / (max_value or 1)
    ticks = [0, 25, 50, 75, 100] if max_value == 100 else [max_value * i / 4 for i in range(5)]
    tick_lab = (lambda t: f"{t:.0f}") if max_value == 100 else (lambda t: f"{t/1000:.0f}k" if t >= 1000 else f"{t:.0f}")
    s = [f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="{esc(aria)}"><g transform="translate({ml},{mt})">']
    for t in ticks:
        s.append(f'<line x1="{x(t):.1f}" x2="{x(t):.1f}" y1="0" y2="{H-mt-mb}" class="grid"/>'
                 f'<text x="{x(t):.1f}" y="{H-mt-mb+16}" text-anchor="middle" class="tick">{tick_lab(t)}</text>')
    for i, r in enumerate(rows):
        y = i * (row_h + gap)
        name = str(r[name_key])
        short = name if len(name) * 7.2 <= ml - 20 else name[: max(4, int((ml - 24) / 7.2))] + "…"
        s.append(f'<text x="-10" y="{y+row_h/2}" dy=".35em" text-anchor="end" class="name"><title>{esc(name)}</title>{esc(short)}</text>')
        acc = 0.0
        for j, (key, label, weight) in enumerate(parts):
            v = (r.get(key) or 0) * (1 if weight is None else weight)
            if v > 0:
                tip = (f"{name} — {label}: {r.get(key, 0):.1f}/100 × {int(weight*100)}% = {v:.1f} points" if weight is not None
                       else f"{name} — {label}: {v:,.0f} {unit}")
                s.append(f'<rect x="{x(acc):.1f}" y="{y}" width="{max(0, x(acc+v)-x(acc)-0.8):.1f}" height="{row_h}" '
                         f'fill="{PALETTE[j % len(PALETTE)]}"><title>{esc(tip)}</title></rect>')
            acc += v
        s.append(f'<text x="{x(acc)+6:.1f}" y="{y+row_h/2}" dy=".35em" class="total">{esc(total_fmt(r[total_key]))}</text>')
    s.append("</g></svg>")
    return "".join(s)


def legend(labels):
    return '<ul class="legend">' + "".join(
        f'<li><span class="sw" style="background:{PALETTE[i % len(PALETTE)]}"></span>{esc(l)}</li>' for i, l in enumerate(labels)) + "</ul>"


def table(rows, cols, heat=None):
    """cols: [(key, header, align)]; heat: keys to shade by value 0..100."""
    h = ['<div class="scroll"><table><thead><tr>']
    h += [f'<th class="{a}">{esc(t)}</th>' for _, t, a in cols]
    h.append("</tr></thead><tbody>")
    for r in rows:
        h.append("<tr>")
        for k, _, a in cols:
            v = r.get(k, "")
            style = ""
            if heat and k in heat and isinstance(v, (int, float)):
                style = f' style="background:color-mix(in srgb, var(--accent) {round(6 + v * 0.55)}%, transparent)"'
            h.append(f'<td class="{a}"{style}>{fmt(v) if v != "" else "—"}</td>')
        h.append("</tr>")
    h.append("</tbody></table></div>")
    return "".join(h)


def cmd_report(cfg, args):
    out = out_dir(args)
    dev_path, feat_path = out / "developer-scores.json", out / "feature-scores.json"
    if not dev_path.exists():
        die("no developer-scores.json; run score first")
    devs = json.loads(dev_path.read_text())
    feats = json.loads(feat_path.read_text()) if feat_path.exists() else {"rows": []}
    D, F = devs["rows"], feats["rows"]
    title = cfg.raw.get("title") or f"{cfg.company} Engineering Scorecard"
    w = devs["weights"]
    params = [(f"s_{k}", f"{LABELS.get(k, k)} {round(v*100)}%", v) for k, v in w.items()]
    fw = feats.get("weights", FEATURE_WEIGHTS)
    fparams = [(f"s_{k}", f"{FLABELS.get(k, k)} {round(v*100)}%", v) for k, v in fw.items()]
    repo_parts = [(f"lines_{l}", l, None) for l in devs["repos"]]
    by_lines = sorted(D, key=lambda r: -r["lines_added"])
    lead = D[0]
    second = D[1] if len(D) > 1 else None
    sentence = f"<b>{esc(lead['developer'])}</b> leads with <b>{lead['overall']:.1f}</b>/100"
    if second:
        sentence += f", ahead of <b>{esc(second['developer'])}</b> at <b>{second['overall']:.1f}</b>"
    sentence += "."
    if F:
        sentence += (f" The most complex feature is <b>{esc(F[0]['feature'])}</b> ({F[0]['score']:.1f}/100), "
                     f"led by <b>{esc(F[0]['lead'])}</b>.")
    podium = "".join(f'<div class="card tile"><span class="place">{p}</span><span class="big">{r["overall"]:.1f}<small>/100</small></span>'
                     f'<span class="who">{esc(r["developer"])}</span></div>' for p, r in zip(["1st", "2nd", "3rd"], D[:3]))
    heat_cols = [("developer", "Developer", "l"), ("overall", "Overall", "r")] + [(f"s_{k}", LABELS.get(k, k), "r") for k in w]
    raw_cols = ([("rank", "#", "r"), ("developer", "Developer", "l"), ("commits", "Commits", "r"), ("lines_added", "Lines added", "r")]
                + [(f"lines_{l}", l, "r") for l in devs["repos"]]
                + [("active_days", "Active days", "r"), ("mean_tier", "Avg tier", "r"), ("test_share_pct", "Test %", "r"),
                   ("hygiene_pct", "Tidy commits %", "r"), ("modules_200plus", "Modules touched", "r"),
                   ("modules_led", "Modules led", "r"), ("top_modules", "Hardest work", "l wrap")])
    feat_cols = [("rank", "#", "r"), ("feature", "Feature", "l"), ("area", "Area", "l"), ("lead", "Lead", "l"),
                 ("lead_share_pct", "Lead share %", "r"), ("others", "Others", "l"), ("depth", "Depth 1–5", "r"),
                 ("risk", "Risk 1–5", "r"), ("integration", "Integration 1–5", "r"), ("code_lines", "Code lines", "r"),
                 ("test_lines", "Test lines", "r"), ("score", "Score", "r"), ("what", "What it does", "l wrap")]
    below = devs.get("below_min_commits", [])
    sections = [
        f'<header><h1>{esc(title)}</h1><p class="lede">{sentence}</p>'
        f'<p class="sub">Scored from the git history of {len(devs["repos"])} repos ({esc(", ".join(devs["repos"]))}) up to {esc(devs["as_of"])}. '
        f'Each developer gets eight scores out of 100, weighted into one overall score.</p></header>',
        f'<section class="podium">{podium}</section>',
        f'<section class="card"><h2>Overall score, split by what earned it</h2><p class="note">Each segment is one parameter\'s score times its weight; '
        f'segments add up to the total. Hover a segment for its score.</p>{legend([p[1] for p in params])}'
        f'{stacked_svg(D, "developer", "overall", params, 100, "Overall developer scores split by weighted parameter")}</section>',
        f'<section class="card"><h2>Where each developer\'s code lives</h2><p class="note">Lines of code added per repo, after removing generated files and duplicate history.</p>'
        f'{legend(devs["repos"])}{stacked_svg(by_lines, "developer", "lines_added", repo_parts, max(r["lines_added"] for r in D), "Lines added per developer by repo", lambda v: f"{v/1000:.1f}k" if v >= 1000 else str(v), "lines")}</section>',
        f'<section class="card"><h2>All eight parameters, out of 100</h2><p class="note">Darker cells are higher scores.</p>{table(D, heat_cols, heat={c[0] for c in heat_cols[1:]})}</section>',
    ]
    if F:
        sections += [
            f'<section class="card"><h2>Most complex features, out of 100</h2><p class="note">Depth, risk and integration are rated 1–5 from reading the code; '
            f'size and tests are measured. Hover a segment for its part of the score.</p>{legend([p[1] for p in fparams])}'
            f'{stacked_svg(F, "feature", "score", fparams, 100, "Feature complexity scores split by weighted parameter")}</section>',
            f'<section class="card"><h2>Who built each feature</h2><p class="note">Lead is the developer who added the most non-test lines in the feature\'s folders; '
            f'Others lists anyone with 5% or more.</p>{table(F, feat_cols)}</section>']
    sections.append(f'<section class="card"><h2>The raw numbers behind the scores</h2>{table(D, raw_cols)}</section>')
    method = "".join(f"<dt>{esc(LABELS.get(k, k))} ({round(v*100)}%)</dt><dd>{esc(METHOD[k])}</dd>" for k, v in w.items() if k in METHOD)
    notes = list(cfg.raw.get("report_notes", []))
    if below:
        notes.append("Left out for having fewer than %d commits: %s." % (cfg.min_commits, ", ".join(f"{b['developer']} ({b['commits']})" for b in below[:12])))
    sections.append(
        f'<details class="card"><summary>How the scores are worked out, and what they miss</summary><dl>{method}'
        f'<dt>Feature score</dt><dd>{esc(METHOD["feature"])}</dd></dl><ul>'
        + "".join(f"<li>{esc(n)}</li>" for n in CAVEATS + notes) + "</ul></details>")
    page = REPORT_TEMPLATE.replace("{{TITLE}}", esc(title)).replace("{{BODY}}", "\n".join(sections))
    (out / "report.html").write_text(page)
    print(f"wrote {out / 'report.html'}", file=sys.stderr)


METHOD = {
    "difficulty": "Every module gets a tier from 1 (presentation, config, docs) to 5 (money, security, identity, production infrastructure, engines and AI agents). The score is the line-weighted average tier of a developer's code, mapped so tier 1 is 0 and tier 5 is 100.",
    "hard_output": "Lines added, each weighted by its tier (tier 5 counts fully, tier 1 a fifth), as a share of the top developer and cube-rooted so size has diminishing returns.",
    "volume": "Lines of code added, cube-rooted against the top developer.",
    "breadth": "Number of modules where the developer added 200+ lines, against the top developer.",
    "ownership": "Modules (800+ lines in all) where the developer added the most lines, weighted by tier and square-rooted against the top developer.",
    "tests": "Share of the developer's lines that are tests; 35% or more earns full marks.",
    "consistency": "Distinct days with at least one commit, against the most active developer.",
    "hygiene": "Share of commits titled with a ticket id or a conventional prefix such as feat: or fix:.",
    "feature": "30% technical depth, 25% domain risk and 20% integration surface, each rated 1–5 from reading the code; 15% size (square root of code lines against the largest feature) and 10% tests (0.8 test lines per code line earns full marks).",
}
CAVEATS = [
    "These scores measure the git record. They don't measure code quality, design, reviews, mentoring, on-call or business impact, and shouldn't be used alone to judge people.",
    "Generated and data files (lockfiles, build output, JSON, CSV, Markdown, images) are left out. Infrastructure files such as Terraform, CI workflows, Dockerfiles and deploy config count in full.",
    "Merges are skipped. A change that appears on several branches or in several repos counts once. Copied or ported code still counts for whoever committed it.",
    "Work done outside git (cloud consoles, manual ops, design docs) isn't scored.",
]

REPORT_TEMPLATE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{TITLE}}</title><style>
:root{--bg:#f7f8fa;--panel:#fff;--fg:#1d2330;--muted:#5b6475;--line:#e3e6ec;--accent:#4269d0;color-scheme:light}
@media (prefers-color-scheme:dark){:root{--bg:#12151b;--panel:#1a1e26;--fg:#e8ebf1;--muted:#9aa3b2;--line:#2b313c;--accent:#7f9cf5;color-scheme:dark}}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1180px;margin:0 auto;padding:32px max(16px,env(safe-area-inset-right)) 48px max(16px,env(safe-area-inset-left));display:grid;grid-template-columns:minmax(0,1fr);gap:20px}
main>*{min-width:0}
h1{font:400 2rem/1.15 Georgia,"Iowan Old Style",serif;margin:0;text-wrap:balance}h2{font-size:1.05rem;margin:0}
.lede{font-size:1.05rem;max-width:75ch;margin:.4rem 0}.sub,.note{color:var(--muted);font-size:.85rem;margin:0;max-width:80ch}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:20px;display:grid;gap:12px;min-width:0}
.podium{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,200px),1fr));gap:12px}
.tile{gap:2px}.place{color:var(--muted);font-size:.75rem;letter-spacing:.06em;text-transform:uppercase}
.big{font:400 2.4rem/1 Georgia,serif;font-variant-numeric:tabular-nums}.big small{font:.9rem system-ui;color:var(--muted)}.who{font-weight:600}
.legend{display:flex;flex-wrap:wrap;gap:4px 16px;list-style:none;margin:0;padding:0;color:var(--muted);font-size:.8rem}
.legend li{display:flex;align-items:center;gap:6px}.sw{width:10px;height:10px;border-radius:2px;display:inline-block}
svg text{font-family:inherit;font-size:12px;fill:var(--muted)}svg .name,svg .total{fill:var(--fg)}svg .total{font-weight:600}
svg .grid{stroke:var(--line)}.scroll{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:.8rem;font-variant-numeric:tabular-nums}
th,td{padding:6px 8px;border-bottom:1px solid var(--line);white-space:nowrap;text-align:right}th{color:var(--muted);font-weight:600}
.l{text-align:left}.wrap{white-space:normal;min-width:360px;max-width:560px}
details summary{cursor:pointer;font-weight:600}dt{font-weight:600;margin-top:8px}dd{margin:0;color:var(--muted);max-width:80ch}
details ul{color:var(--muted);max-width:80ch}
</style></head><body><main>
{{BODY}}
</main></body></html>"""


# ----------------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["survey", "collect", "modules", "score", "features", "report", "all"])
    ap.add_argument("--config", required=True)
    ap.add_argument("--out", default="scorecard-out")
    ap.add_argument("--limit", type=int, default=0, help="modules: rows to print")
    args = ap.parse_args()
    cfg = Cfg(args.config)
    if args.command == "all":
        cmd_collect(cfg, args); cmd_score(cfg, args)
        if cfg.features:
            cmd_features(cfg, args)
        cmd_report(cfg, args)
    else:
        globals()[f"cmd_{args.command}"](cfg, args)


if __name__ == "__main__":
    main()
