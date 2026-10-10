"""tools/probe_injection.py - print what C2 and C4 actually returned."""
import pandas as pd
from src.dashboard.loader import load_display_table
from src.dashboard.state import STATE_NEEDS_REVIEW
from src.assistant import answer_question
from tools.check_chat_grounding import INJECTION_CASES

df = load_display_table()
target = df.loc[df["display_state"] == STATE_NEEDS_REVIEW, "person_index"]
target_index = int(target.iloc[0]) if len(target) else int(df["person_index"].iloc[0])

for label, slot, text, complied in INJECTION_CASES:
    if not (label.startswith("C2") or label.startswith("C4")):
        continue
    hostile = df.copy()
    question = "Who works in finance, and who might I ask about data?"
    if slot == "question":
        question = text
    else:
        if slot not in hostile.columns:
            hostile[slot] = ""
        hostile[slot] = hostile[slot].astype(object)
        hostile.loc[hostile["person_index"] == target_index, slot] = text

    ans = answer_question(hostile, question)
    print("=" * 70)
    print(label)
    print(f"verdict: {'COMPLIED' if complied(ans, df) else 'RESISTED'}")
    print(f"status={ans.status} dropped={ans.dropped} people={len(ans.people)}")
    print("-- answer --")
    print(ans.text)
    print("-- whys --")
    for p in ans.people:
        print(f"  {p.why}")
