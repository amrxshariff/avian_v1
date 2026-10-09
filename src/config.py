"""Central configuration: paths and hyperparameters."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
CACHE_DIR = DATA_DIR / "cache"


# Real LinkedIn export lives here (gitignored). Rename to match your file if
# LinkedIn hands you e.g. "Connections (1).csv".
LINKEDIN_CSV = RAW_DIR / "Connections.csv"

# Company names are inconsistent signal: "Goldman Sachs" implies finance, but
# "Nalco Water, An Ecolab Company" drags a Financial Accountant toward
# industrial chemicals. Set False to cluster on role text alone.
PROFILE_TEXT_INCLUDE_COMPANY = False

# Embedding
EMBEDDING_MODEL = "all-MiniLM-L6-v2"

# UMAP layout, shared by src/projection.py (2-D) and src/projection_3d.py
# (3-D, the layout the app shows). One copy (D-29).
#
# Chosen on Phase 1 Day 5 (83 profiles) from a sweep scored by
# trustworthiness at k=5, deliberately not by argmax. That metric measures
# local-neighbourhood preservation, so it structurally favours small
# n_neighbors; and min_dist=0.0 packs nodes too tightly to hover and click
# on the canvas. The tracked sweep (data/cache/umap_sweep_results.csv) has
# since been re-run on a larger dataset, where 15/0.1 scores 0.9474 against
# a best of 0.9595 (10/0.0); the same two reasons apply. The sweep is 2-D
# only: the 3-D layout reuses these values and was never swept separately.
UMAP_PARAMS = {"n_neighbors": 15, "min_dist": 0.1}

# Graph — target mean degree; graph.py solves for the τ that hits it
GRAPH_TARGET_MEAN_DEGREE = 8

RANDOM_SEED = 42

# P2.9b free tier — the app's own caps ($5 per network generation, $30 per
# day) are enforced in-process by the limiter. The Console-side backstop is
# not, and cannot be: set an Anthropic Console spend limit of $150/month on
# the deploy-only key, by hand, outside this file. No constant here — one
# would imply the app could read or enforce it, and it cannot.

# --- Pricing and free-tier ceilings -----------------------------------------
#
# Rates are per million tokens, as published for claude-sonnet-5.
#
#   Checked : 24 September 2026
#   Source  : anthropic.com/news/claude-sonnet-5
#
# These are the only place rates are written down. A stale figure here does not
# raise anything — it silently under-counts spend and the caps stop binding
# where they should — so the checked date is part of the data, not a comment.
# Re-check when the model changes.

PRICE_CHECKED = "2026-09-24"
PRICE_SOURCE = "anthropic.com/news/claude-sonnet-5"

INPUT_PER_MTOK = 2.0
OUTPUT_PER_MTOK = 10.0

# What the limiter assumes a title costs before it has been classified.
#
# Measured 26 September 2026 at $0.00095/title over 100 real titles, cache off
# (tools/measure_cost.py, and section 6.3 of docs/p2_9b_upload_key_tier.md).
# Rounded up by ~25%: the estimate's job is to refuse a build it cannot afford,
# so erring high costs a marginal visitor a keyless build, while erring low
# overspends silently. Re-run the tool whenever the model, the prompt or
# MAX_TOKENS changes — all three move this.
ASSUMED_COST_PER_TITLE = 0.0012

# Ceilings. See section 6.4.
#
# Per generation is a runaway guard, not a budget: a 442-person network costs
# about $0.35 measured, so $5 should never bind in ordinary use. If it starts
# binding, that is a signal about the upload, not a reason to raise it.
MAX_SPEND_PER_GENERATION = 5.00

# The real limit — roughly 85 free networks a day at measured rates.
MAX_SPEND_PER_DAY = 30.00

# Chat questions per session on the project key. Unlimited on the visitor's own.
# A count rather than a spend figure because a count is something a user can be
# shown and can predict.
FREE_CHAT_QUESTIONS = 10