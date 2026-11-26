# Methodology

## Contents
1. Which lines count
2. Modules and difficulty tiers
3. Developer parameters
4. Feature score
5. Rubric: difficulty tiers
6. Rubric: feature ratings
7. Caveats to pass on

## 1. Which lines count

- **Lines added** come from `git log --numstat` across all branches (or the GitHub commits API), with merges skipped.
- **Generated and data files are skipped:** lockfiles, build output (`dist`, `build`, `target`, `.next`), `node_modules`, vendor folders, logs, images and fonts, plus JSON, CSV, Markdown, HTML, YAML and other data or docs formats. Generated code is skipped too (gqlgen `generated.go`, `*_gen.go`, protobuf output, `__generated__/` and `generated/` folders), as are data tables stored as code (`*.data.ts`) and `mock_data/` folders.
- **Infrastructure files are kept** even when their extension would be skipped: Terraform and HCL, CI workflows (`.github/`, GitLab CI, CircleCI), Dockerfiles and compose files, deploy scripts, Kubernetes and Helm, systemd units, monitoring config. Terraform state and example env files are skipped.
- **Each file change counts once,** keyed by author, date, commit title, the repo it belongs to, its path there and its line count. That removes the same commit on several branches, and a parent repo's copies of its subtrees' history (`subtrees` in the config). Vendored copies are dropped by `vendored`.
- **Commits count when at least one of their file changes is new.**

## 2. Modules and difficulty tiers

A module is a feature-sized folder.
- **Config `modules` rules** win.
- **Otherwise folder heuristics apply:**
  - **Marker folders:** the folder after a marker such as `modules/`, `features/`, `services/`, `components/` or `connectors/`.
  - **App containers:** `apps/<app>/…/modules/<m>` becomes `<app>/<m>`.
  - **Generic leading folders** such as `src`, `lib` and `main` are skipped.
- **Infra and CI files:** infrastructure-as-code becomes `infra` and other delivery files become `devops`.
- **Catch-all splitting:** a module holding more than `auto_split` (10%) of its repo's lines and 5,000+ lines is split one folder deeper.

Each module gets a tier from 1 to 5 (config `tiers` rules first, then defaults). Tier weights for output are 0.2, 0.4, 0.6, 0.8 and 1.0.

## 3. Developer parameters

All are 0–100. The overall score is the weighted sum (weights in brackets are the defaults).

| Parameter | How it's worked out |
|---|---|
| Difficulty (25%) | Line-weighted average tier of the developer's code, mapped so tier 1 = 0 and tier 5 = 100 |
| Hard-feature output (20%) | Σ lines × tier weight, as a share of the top developer, cube-rooted |
| Volume (10%) | Lines added, as a share of the top developer, cube-rooted |
| Breadth (10%) | Modules where they added 200+ lines, against the top developer |
| Ownership (10%) | Σ tier of modules (800+ lines in all) where they added the most lines, share of the top developer, square-rooted |
| Tests (10%) | Test lines ÷ all their lines; 35% or more = 100 |
| Consistency (10%) | Distinct days with a commit, against the most active developer |
| Commit hygiene (5%) | Share of commit titles with a ticket id (`ABC-123`) or conventional prefix (`feat:`, `fix:` …) |

Why the roots: raw line counts differ by 50× between people, and a linear scale would make everyone but the top contributor look like zero. Cube roots keep size meaningful with diminishing returns. Difficulty is an average, so a focused developer in hard code can beat a prolific one there; hard-feature output balances that by rewarding the amount of hard code.

## 4. Feature score

`score = 0.30·depth + 0.25·risk + 0.20·integration + 0.15·size + 0.10·tests`

- **Depth, risk and integration** are rated 1–5 and mapped to 0, 25, 50, 75 and 100.
- **Size** is 100 × √(code lines ÷ the largest feature's code lines). Code lines are the non-test lines in the feature's folders as they are now.
- **Tests** are test lines ÷ code lines, where 0.8 or more = 100.
- **Lead** is the developer who added the most non-test lines in those folders. Others listed hold 5% or more.

## 5. Rubric: difficulty tiers

Tier the kind of work, the same way for everyone.

| Tier | Kind of code | Examples |
|---|---|---|
| 5 | A mistake loses money, leaks data, locks people out or takes production down; or the code is an algorithmic core | Payments, ledgers, payouts, billing; authentication, SSO and identity providers, permissions, encryption, secrets; production infrastructure as code; pricing or matching engines, graph or hierarchy engines; AI agent and workflow runtimes |
| 4 | Business-critical flows, and integrations with outside systems | Third-party connectors (insurers, banks, carriers, payment providers), compliance and onboarding/KYC flows, sync and webhooks, database schema and migrations, CI/CD and deploy, search, caching, quoting |
| 3 | Supporting business modules and shared foundations | Admin and ops tools, notifications and email, reports, audit, shared/common libraries, API clients, test suites |
| 2 | Ordinary product code | CRUD screens and endpoints, dashboards, page shells, hooks, state management, seeds |
| 1 | Presentation and content | Design-system UI kits, styles, landing and marketing pages, i18n strings, docs, static assets, config |

Judge by what the code does, not the folder name. If a `utils` folder holds the pricing core, it's tier 5. If a folder named `auth` only holds the login page's layout, it's tier 2.

## 6. Rubric: feature ratings

**Technical depth**: how hard the code is to get right.
- **1:** static content
- **2:** standard CRUD and UI
- **3:** non-trivial flows and state, with careful validation
- **4:** concurrency, transactions, multi-step orchestration, parsing or non-trivial algorithms
- **5:** novel engines, ledgers with invariants, graph or ML systems, protocol implementations

**Domain risk**: the cost of a bug.
- **1:** cosmetic
- **2:** inconvenience
- **3:** wrong data that someone will notice
- **4:** regulatory, contractual or customer-money exposure, or an outage of a key flow
- **5:** direct money movement, security or identity, or production-wide outage

**Integration surface**: what it must stay in agreement with.
- **1:** self-contained
- **2:** one internal module
- **3:** several internal modules
- **4:** one or two external systems, or many internal consumers
- **5:** many external systems or every service in the company (identity, infra, a shared contract)

Rate from the code you read, and keep a one-line reason for each 5 in case the user asks.

## 7. Caveats to pass on

- The scores measure the git record, not code quality, design, reviews, mentoring, on-call or impact. Don't use them alone to judge people.
- Copied or ported code counts for whoever committed it. Bulk-import commits inflate volume while barely touching consistency.
- Work outside git (cloud consoles, manual ops, documents) isn't seen.
- Tiers and feature ratings are judgment. Say they're yours, and re-score when the user disagrees.
