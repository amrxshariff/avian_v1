"""tools/checkpoint_reconcile.py - Day-15 QA checkpoint data reconciliation.

Reads the display table through the single loader with NO corrections applied,
so these are base-table facts, not session artefacts.
"""
from src.dashboard.loader import load_display_table

df = load_display_table()

print(f"rows                      : {len(df)}")
print(f"is_uncertain True         : {int(df['is_uncertain'].sum())}")
print()
print("display_state counts (no corrections):")
print(df["display_state"].value_counts().to_string())
print()
print(f"distinct soc_major present: {df['soc_major'].nunique(dropna=True)}")
print(f"distinct soc_major_name   : {df['soc_major_name'].nunique(dropna=True)}")
print()
print("soc_major_name breakdown:")
print(df["soc_major_name"].value_counts(dropna=False).to_string())
