# E1 — two removals: the blast radius, before touching anything

_2026-08-20. **Report only. Nothing removed yet.** Both rulings undo shipped
behaviour; this names what breaks and what must survive._

---

# 1. Remove the day state

**Ruled:** on a rain or shutdown day nobody is on site, including the CP, so
nobody opens the app to record it. A blank day is legally fine — the absence of
a log for a date is itself the record. The control was specified for a case that
cannot be filled.

## 1a. The surface, measured

Eight files. `dayState` appears 16× in `daily_jobsite.jsx` alone.

| File | What it holds | Action |
|---|---|---|
| `frontend/src/utils/dayStateModel.js` | The whole model: `DAY_WORKED/DAY_RAIN/DAY_SHUTDOWN`, `dayState()`, `isNoWorkDay()`, `crewWorkRequired()`, `retainedWork()`, `isDayStateId()` | **Delete** |
| `frontend/src/utils/dayStateModel.test.cjs` | Its tests | **Delete** |
| `frontend/app/logbooks/daily_jobsite.jsx` | The step-1 control (`:1782-1790`), the state (`:327`), payload (`:393`), hydrate (`:698`), the #167 relaxation (`:1584`), `keptWork` (`:1590`), the crew-card suppression (`:1888`) | **Remove, 16 sites** |
| `frontend/src/i18n/en.js` | 7 keys: `dayStateQuestion`, `dayState_*`, `dayStateKeptWork`, `dayStateCrewNote_*` | **Remove** |
| `frontend/src/utils/dailyJobsiteModel.js` | 1 reference | **Remove** |
| `backend/server.py` | `_DAY_STATE_LABELS` (`:19506`), `_day_state_label()` (`:19512`), the report render (`:14030`) | **KEEP — see §1c** |
| `backend/tests/test_day_state_on_the_report.py` | The renderer's tests | **KEEP, retargeted** |
| `backend/app/scheduling/sequence_rules_v1.py` | Only a comment explaining the taxonomy removal | **KEEP untouched** |

## 1b. The taxonomy correction survives, confirmed by measurement

Run just now against the real module:

```
nodes = 84   edges = 145
ALWAYS_AVAILABLE_ORDER = ('site_cleanup', 'material_delivery', 'hoisting',
  'scaffold_erection', 'scaffold_dismantle', 'sidewalk_shed_work',
  'dewatering', 'survey_layout', 'inspection', 'safety_meeting')
rain_no_work in nodes? False | shutdown in nodes? False
```

**Edge count holds at 145.** Node count is 84. Neither depends on the day-state
feature: `rain_no_work` and `shutdown` were removed from the node table and from
`ALWAYS_AVAILABLE_ORDER` because *they are not a crew's activity* — a reason that
stands on its own and is unaffected by whether a day-level control exists. The
module's own note records that both had **no edges**, which is why removing them
moved nodes 86 → 84 and left edges at 145.

**Removing the day state does not put them back**, and nothing in the removal
should touch `sequence_rules_v1.py`. The one thing to watch: its comment at
`:107` and `:296` explains the removal by referring to
"day-level fields now… (frontend/src/utils/dayStateModel.js)". That file is about
to stop existing, so the comment needs rewording to stand on the taxonomy
argument alone — otherwise it justifies a correct decision by pointing at a
deleted file, and the next reader may take the deletion as grounds to undo it.
**That is the one edit `sequence_rules_v1.py` needs, and it is prose only.**

## 1c. ANSWER — logs already filed carrying `day_state`

**They keep printing exactly what they printed. Nothing about them changes.**

The read path is one function reading stored data:

```python
def _day_state_label(data):
    return _DAY_STATE_LABELS.get(str((data or {}).get("day_state") or ""))
```

It reads `data["day_state"]` off the **stored logbook document**. Removing the
control and the payload field affects only what NEW logs write; it cannot reach
a document already in Mongo. So the report keeps rendering
`Day: Rain — no work performed` on every log that was signed with it.

**Therefore: keep `_DAY_STATE_LABELS`, `_day_state_label()`, the render site at
`:14030`, and `test_day_state_on_the_report.py`.** Delete only the write side.

If the renderer were deleted with the rest, every filed log carrying the field
would silently stop printing a line it printed at signing — changing the
appearance of a filed compliance record after the fact. That is the one outcome
this removal must not produce, and it is the reason the split is write-side-only.

The renderer's own docstring already handles the post-removal world correctly
without modification: *"Anything unrecognised — absent, null, junk, a log filed
before the field existed — is an ordinary day."* After the removal, every new log
is exactly that case.

### Two consequences worth naming

1. **An amendment of a day-state log drops the field.** Parent and child are
   separate documents; the child is filed by the new editor, which no longer
   sends `day_state`. So the parent prints "Rain — no work performed" and its
   amendment does not. That is arguably correct — the child is a new record under
   the new model — but it is a visible difference between two linked documents
   and someone will ask. Worth a line in the PR.
2. **`retainedWork` disappears with the model.** It exists so work typed before
   the day turned is not erased. With no day state there is no turn, so nothing
   is retained-vs-cleared and the concept goes cleanly. No data path depends on
   it.

## 1d. What the removal restores

The **#167 gate returns to unconditional**: every crew must have an activity and
a location. Today `crewWorkRequired(dayStateValue)` relaxes that on a no-work
day. With the day state gone the relaxation has no trigger, so `crewGaps` becomes
`crewsWithoutWork(activities)` outright — which is #167 as originally specified.
**That is a restoration, not a new gate**, but it is behaviour a CP could hit on
the next filing, so it belongs in the PR description rather than only in the diff.

---

# 2. Remove "Not assessed"

**Ruled:** a project starts regular and an admin changes it when the project
changes. Regular is a real starting value, not a guess.

## 2a. The surface

| File | What it holds | Action |
|---|---|---|
| `frontend/app/projects/index.jsx:454-458` | The `{ key: null, label: 'Not assessed — set later' }` option, selected until he chooses | **Remove; default to regular** |
| `frontend/app/admin/superintendent.jsx:316` | The NOT ASSESSED badge | **Remove** |
| `frontend/app/logbooks/index.jsx` | The "classification not assessed" explanation on the safety-staff screen | **Remove** |
| `frontend/src/utils/projectClass.js` | `classificationAssessed`, `isMajorClass`, `VALID_PROJECT_CLASSES` | **See §2c** |
| The list filter fix | An unclassified project appearing on the safety-staff screen | **KEEP — ruled.** It now shows as regular rather than as not assessed |

## 2a-bis. A FOURTH SURFACE, and it is not UI

A file-by-file cross-check (the indexed search under-counted it) puts the
largest concentration somewhere the ruling does not mention:

```
  8  frontend/src/utils/requiredLogbooksWiring.test.cjs
  7  backend/tests/test_required_logbooks_model.py
  3  frontend/src/utils/projectClass.test.cjs
  1  frontend/src/utils/createProjectClass.test.cjs
```

Nineteen assertions across four test files, and they are not about badges.
They pin `get_required_logbooks` (`server.py:1569`):

```python
assessed = str(project_class or "") in VALID_PROJECT_CLASSES
...
if assessed and project_class not in classes:
    continue          # skip a log that does not apply to THIS class
```

**This is a fail-closed compliance rule.** When the class is unassessed, the
class filter is skipped entirely, so the project gets the FULL set of required
logbooks rather than a narrowed one. An unassessed project is over-covered, not
under-covered — which is the correct direction to fail on a §3310 staffing and
records question.

**Nothing in either ruling touches this, and nothing should.** It is listed
because:

* it is the largest `not_assessed` surface by count, so a search-and-remove pass
  would walk straight into it;
* it is a **fourth consumer of the null path**, which reinforces §2b — if the
  model default became `"regular"`, a legacy document with no key would start
  taking the `assessed` branch and get a NARROWED logbook set. That is a
  compliance behaviour change on existing projects, arrived at through a
  serialisation default. It is the strongest single argument for the backfill
  sequence over the default flip.

So the count that matters for §2a is **three UI sites**; the other four files
are the fail-closed rule and its tests, and they stay exactly as they are.

## 2b. ANSWER — does the null path still matter? **YES. It is not unreachable.**

The reasoning behind the question is sound — if the form always sends `regular`,
the create-path `else` never fires *from that form*. But the form is one of
**three** producers, and the other two are untouched by a form change:

**(i) Legacy documents already in Mongo.** `ProjectResponse` deserialises stored
projects. Documents written before the classification model landed have **no
`project_class` key at all**. Restoring the default to `"regular"` makes every one
of them serialise as a real class — the exact bug
`test_project_response_class_null.py` was written for, reintroduced on existing
data that no form will ever touch. **This is the decisive one.**

**(ii) The UPDATE path** (`server.py:9822-9829`) has the same `else` branch as
create:

```python
else:
    update_data["project_class"] = suggested          # may be None
    update_data["classification_source"] = "measured" if suggested else "unassessed"
```

`classify_project` returns `None` when there was nothing to measure. So a PUT
that touches any classification field without supplying a valid class still
**writes null today**, regardless of what the create form sends.

**(iii) The create `else` itself** stays reachable from any client that is not
this form. `ProjectCreate.project_class` is `Optional[str] = None`, and the
endpoint is open to any authenticated admin.

**And the coherence constraint.** `classification_source` is written beside the
class. Defaulting `project_class` to `"regular"` while a stored document carries
`classification_source: "unassessed"` produces one response with two
contradictory answers and nothing to say which a consumer should believe. That
is precisely what the existing test pins.

### So the honest sequence is a backfill, not a default flip

Restoring `ProjectResponse.project_class = "regular"` **now** would be a
regression, not housekeeping. To make the null genuinely unreachable — at which
point the default becomes moot and can be restored honestly:

1. **Backfill** the legacy documents: set `project_class: "regular"` and
   `classification_source` to something truthful for a defaulted value (not
   `"admin"` — nobody decided it; a new `"default"` value, or `"unassessed"`
   retained deliberately).
2. **Close the two `else` branches** so a create or update without a valid class
   stores `"regular"` rather than `suggested or None`.
3. **Then** the None default has no producer left, and restoring it is a
   statement about a state that cannot occur rather than a silent reinterpretation
   of one that can.

Steps 1 and 2 are the actual work. Step 3 is a one-line consequence.

**Recommendation: do §2a now — it is pure UI and matches the ruling exactly —
and treat 1–3 as a separate, sequenced change.** Doing the model default in the
same PR as the UI removal would bundle a data-visible reinterpretation with a
form change, and the diff would stop being reviewable.

## 2c. What `projectClass.js` becomes

`classificationAssessed` loses its consumers once the badge and the explanation
go. `isMajorClass` does **not** — it is the "unassessed is not major" guard and
stays correct under either model. Suggest keeping the module, deleting only
`classificationAssessed` **after** confirming its last caller is gone, and
leaving `VALID_PROJECT_CLASSES` (still the validation set on both write paths).

---

# 3. New finding — logged, not built

**"All activities" shows the full catalogue.** With chips trade-filtered, the
expander dumps unrelated activities from every trade — all 84 nodes — instead of
that crew's remaining trade work. Recorded here so it is not lost; not touched
in either removal.

---

# Recommended split

Two PRs, because they share no code and fail differently:

- **PR A — remove the day state.** Frontend-only except for the one prose edit in
  `sequence_rules_v1.py`. Renderer and its tests explicitly retained; the PR
  should say so in the title body, because "removed the day state" and "the
  report still prints it" look contradictory without the reason.
- **PR B — remove "Not assessed".** UI only. `ProjectResponse` untouched, with
  §2b linked as the reason.

Neither should carry the other's risk.
