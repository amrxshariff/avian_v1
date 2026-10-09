# Network Visualiser

## How this was built

This repository ships as a single commit. The development history is kept
privately, because it contains real LinkedIn data that cannot be published.

`docs/defect_register.md` is the substantive record. Defects are numbered up to
D-85, and the register holds 48 of them, from D-21 on; earlier ones are
dispositioned in the gate records it points to. Its full entries say what was
found, how it was found, what it invalidated, and what was checked and turned
out not to be a defect. Several entries exist because a later check found
something an earlier check's method could not see. The register records the
method changing, not just the fixes.

## How grouping works

People are grouped by **occupation**, not by unsupervised clustering. Each
connection's job title is classified into one of the 23 SOC major groups using
the [O\*NET 30.3 taxonomy](https://www.onetcenter.org/database.html); the SOC
major group is the grouping key the dashboard renders and filters on.

This replaced an earlier HDBSCAN clustering approach. On real LinkedIn data
(430 people, 371 distinct job titles, 336 of them unique) there is no density
for a clustering algorithm to find, and clustering has no ground truth to
measure accuracy against. Classification against an external taxonomy is both
measurable and correct for the task. See
[`docs/phase1_5_methodology.md`](docs/phase1_5_methodology.md) for the full
decision log and the approaches ruled out (HDBSCAN, embedding-similarity
matching, and company as a signal).

### Accuracy and the uncertainty model

Classification of a two-word job title has a **hard ceiling of roughly 60%**,
measured by inter-annotator agreement: two people given the same titles and the
same rules agree with each other only ~60% of the time, because a title like
"Systems Engineer" or "Co-Founder" genuinely does not determine a single
occupation. The classifier operates at this human ceiling, not below a fixable
target.

The product is therefore built **coverage-first with visible uncertainty**:

- Titles the classifier can place are grouped and coloured by occupation.
- Titles it cannot place confidently (roughly 29% of the real 442-person
  network, in a single measurement — see below) are **flagged as uncertain**
  rather than guessed, and surfaced to the user for confirmation.
- A blank, honestly-flagged node is preferred over a confident wrong one that
  cites an authoritative taxonomy — the latter is undetectable to the user and
  is the worst outcome.

Every node carries an `is_uncertain` flag through to the final `network_nodes.csv`.

### Raising the ceiling

The only lever that improves accuracy is **richer input**, not a better model —
the information is simply absent from a two-word title. The planned route is
self-enrichment: a user optionally supplies their own profile "About" text,
which is consented first-party data. Automated collection of other people's
profile data is out of scope on Terms-of-Service and UK GDPR grounds.

### The demo network

The public demo is built from a synthetic export — Faker names, O*NET job
titles — and classified once in advance, so no real person appears in it and
no visitor pays for it.

The shipped demo has **124 of 442 people (28.1%) needing review**, against
roughly 29% for the real 442-person network the synthetic file was shaped to
match. Both figures are single draws from a process that is not deterministic:
five builds of the identical synthetic file, with the classification cache
cleared between each, gave 21.9%, 24.0%, 25.8%, 24.0% and 28.1% — a spread of
about six percentage points around a mean near 25%. Between two of those
builds, about 15% of individual titles received a different group. The layout
is fully seeded and does not vary; only the classification does.

Treat every classification figure in this project as one draw. The only spread
measured so far is this one; the others, including those in the methodology
documents, have not been re-run and may vary as much or more. See
`docs/defect_register.md`, D-69.

## Data attribution

This project includes information from the
[O\*NET 30.3 Database](https://www.onetcenter.org/database.html) by the U.S.
Department of Labor, Employment and Training Administration (USDOL/ETA). Used
under the [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) license.
O\*NET® is a trademark of USDOL/ETA. Amr Shariff has modified all or some of
this information. USDOL/ETA has not approved, endorsed, or tested these
modifications.

## Development

Everything runs from the repo root, inside the project venv. Commands are
PowerShell; use `Select-String` and `Get-ChildItem -Recurse`, not `grep` and
`find`.

### Environment

`requirements.txt` is the runtime lock (what Community Cloud installs) and
`requirements-dev.txt` the development lock. Both are generated: edit
`requirements.in` or `requirements-dev.in`, then recompile both.

| Purpose | Command |
|---|---|
| Recompile the runtime lock | `uv pip compile requirements.in --universal --python-version 3.11 -o requirements.txt` |
| Recompile the dev lock | `uv pip compile requirements-dev.in --universal --python-version 3.11 -o requirements-dev.txt` |
| Set up a dev environment | `uv pip sync requirements.txt requirements-dev.txt` |
| Verify both locks from scratch | `python -m tools.verify_manifests` |

### The API key

The app reads the project key from `ANTHROPIC_API_KEY` in the environment,
and nowhere else. Without it, every build is keyless and the chat is
unavailable.

- **Locally**, `streamlit run app.py` does not read `.env`; only some tools
  do. Set the key in the shell (`$env:ANTHROPIC_API_KEY = "sk-ant-..."`), or
  put it in `.streamlit/secrets.toml`, which is gitignored.
- **On Community Cloud**, enter it in the app's Secrets settings at the
  **root level**: `ANTHROPIC_API_KEY = "sk-ant-..."`. Streamlit copies
  root-level secrets into the environment when the server starts. Under a
  `[section]` heading it is not copied, and the app finds no key.

### Running code

| Purpose | Command |
|---|---|
| The app | `streamlit run app.py` |
| Tests | `python -m pytest tests -q` |
| Invariant: one loader | `python -m tools.check_single_loader` |
| Packages the runtime chain loads | `python -m tools.import_closure app src.linkedin src.ingestion src.classify_pipeline src.embeddings src.projection_3d src.graph src.centrality` |

The `-m` form is required. The VS Code Run button, or `python path/to/file.py`,
fails with `ModuleNotFoundError` because the repo root is not on the path.

The `src/` modules also form the command-line chain the project was first
built with (`python -m src.<module>`). It needs the original LinkedIn export at
`data/raw/Connections.csv`, and the intermediate files each stage writes for
the next. Neither ships, so a clone cannot run it.

The tools (`python -m tools.<name>`) are mixed. Each was started from a fresh
clone on 6 October, with no API key set, and that is how it was placed below.

**Run from a clone:**
- `build_demo` rebuilds the demo from the tracked synthetic export and the
  tracked classification cache. Every synthetic title is already cached, so it
  needs no key and makes no API call. It downloads the embedding model on first
  use. It rewrites the two tracked files in `data/demo/`: the date in
  `provenance.json`, and one row of the node table (D-73).
- `check_single_loader`, `sweep_count_surfaces` and `measure_synthetic` read
  only tracked code or the synthetic export.
- `import_closure <modules>` (as in the table above) and `verify_manifests`
  check the dependency boundary. `verify_manifests` builds two throwaway
  environments, so it needs `uv` and network access. It was not rerun here.

**Need a file you supply:**
- `reconcile_counter <session.json>` checks a session file saved from the app.

**Need a key, and spend on every run.** Neither uses the cache.
- `measure_cost` classifies a sample of titles, from the synthetic export when
  the original is absent.
- `test_injection_rule7` makes adversarial calls against the self-enrichment
  prompt.

**Need files that do not ship, so a clone cannot run them:**
- `check_chat_grounding`, `check_summary_safety`, `check_uncertainty_honesty`,
  `checkpoint_reconcile`, `probe_injection`, `probe_summaries` and
  `probe_unparsed` read the real network's node table.
- `audit_title_churn` and `diff_rebuild` compare the real network's classified
  table (`data/cache/classified.csv`) against an earlier snapshot.
- `remeasure_config_e` needs the blind evaluation labels.

### Caches

`data/cache/` is gitignored except for four tracked files: the classification
cache, below, and three parameter-sweep outputs (`sweep_results.csv`,
`sweep_silhouette.png`, `umap_sweep_results.csv`). Everything untracked is
recomputable. If you delete the directory, restore the tracked files with
`git checkout -- data/cache` before rebuilding anything. The embeddings cache
is keyed on content: each distinct set of profiles, in its order, under its
model, writes its own `embeddings-<key>.npy` (about 650 KB for 442 people),
and nothing removes old ones. A plain `embeddings.npy` predates the keying and
is never read.

`data/cache/claude_classification.json` holds the synthetic demo's titles. It
is tracked so that a clone rebuilding the demo reads these classifications,
rather than drawing fresh ones from a classifier that can answer differently
from one run to the next (D-69). It does not make the demo's node table
identical. Titles that share a normalised key are each sent, the cache keeps
the last answer, and a rebuild gives that answer to all of them (D-73).

A build started from the app writes nothing here. A session's titles are real
people's, and they stay in the session rather than accumulating in a file the
app keeps between visitors (D-71).

### Git

- Stage explicit paths (`git add <path> ...`), not `git add .`: each commit
  holds one change, and one-off scripts or local diagnostics in the working
  tree never ride along by accident.
- Review before committing: `git --no-pager diff --cached --stat`.
- Write multi-line commit messages to a BOM-free temporary file and commit
  with `git commit -F <file>`. Windows PowerShell's own file writers add a
  byte-order mark, which then appears at the start of the message.
