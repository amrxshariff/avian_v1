# Phase 2 — Amendment 3

## P2.6 split: group selection now, SOC-tree zoom deferred

**Raised:** during Phase 2 delivery, on reading P2.6's definition of done against
the current node table.

---

## The dependency

P2.6 as written has three requirements:

1. zoom from major group into the occupations within it, using the SOC hierarchy
   (not a clustering re-run);
2. outer group labels remain visible while zoomed;
3. multiple groups can be selected at once, dimming the rest.

**Requirement 1 cannot be built on the current node table.** Zooming into the
occupations inside a major group requires knowing which detailed O\*NET-SOC
occupation each person holds. Config E returns the 2-digit major group only:
`soc_code` is `None` on every row of `network_nodes.csv`. There is no level
below the major group to zoom into.

This is the same constraint that produced Amendment 2. Two-stage SOC match —
resolving a detailed code beneath the major group — is already scheduled as the
dependency for P3.6 and P3.7, and was costed there at roughly +2 days on
Phase 3. P2.6 requirement 1 therefore depends on work scheduled *after* it.

---

## The decision

**Split P2.6.**

**P2.6a — Group selection and dimming (Phase 2, delivered now).**
Requirements 2 and 3. Multi-select over SOC major groups, dimming the rest,
with the selected groups labelled in the scene. Reuses the P2.4b fade mechanism
and the P2.5 scene-annotation mechanism; no new taxonomy work.

**P3.9 — SOC-tree zoom (Phase 3, after the two-stage SOC match).**
Requirement 1. Scheduled immediately after the detailed-code resolution that
P3.6 and P3.7 already depend on, so the taxonomy work is paid for once and
consumed three times.

### Options rejected

**Pull detailed-code resolution into Phase 2.** Delivers P2.6 whole, but moves
two days of taxonomy work in front of deployment. Deployment is the gate that
turns this from a local script into a product; nothing that can wait should sit
in front of it.

**Re-scope the zoom to major group → individual people.** Needs no new taxonomy
work and is a legitimate drill-down, but it is not the SOC hierarchy the DoD
names, and it would let a met criterion stand in for an unmet one. Worse than
an honest deferral.

---

## P2.6a — definition of done

1. The user can select one or more SOC major groups; unselected nodes fade using
   the existing `FADED_OPACITY` mechanism rather than a second one.
2. Selected groups are labelled in the scene while a selection is active.
3. Selection composes with search: a node is prominent only if it satisfies
   **both** the group selection and the current query. Neither filter overrides
   the other.
4. Clearing the selection restores the unfiltered view exactly as delivered in
   P2.3 — pixel-identical, not approximately.
5. Group options are drawn from the fixed 23-group palette, not from the groups
   present in the data, so the control is identical across user networks.
6. Hover remains suppressed on faded nodes, as in P2.4b.

## P3.9 — definition of done

Requirement 1 of the original P2.6, unchanged, plus:

7. Zoom uses the SOC hierarchy as resolved by the two-stage match. It is not a
   clustering re-run, and it does not re-fit any projection.
8. Where a detailed code could not be resolved, the person remains visible at
   group level rather than disappearing from the zoomed view — the same
   coverage-first principle as the grey nodes.

---

## Schedule impact

**Phase 2:** unchanged in days. P2.6a is smaller than P2.6; the difference is
carried by Phase 3, not saved.

**Phase 3:** P3.9 added. Estimate revised from 7.5–9.5 to **8–10 focused days**.

**Phase 2 closes with one original DoD deferred rather than met.** Recorded here
so that the QA checkpoint reads against the amended scope and not the original,
and so the deferral is visible in the project record rather than absorbed
silently.

---

*Data attribution: this system includes information from the O\*NET 30.3
Database by the U.S. Department of Labor, Employment and Training
Administration (USDOL/ETA), used under CC BY 4.0. USDOL/ETA has not endorsed
this application.*
