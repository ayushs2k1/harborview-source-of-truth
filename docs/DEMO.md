# Five-minute demo

```bash
make setup && make dev        # API on :8000, UI on http://localhost:5173
```

Have `data/samples/healthcare/messy/` open in a file browser. Everything below runs
cold — nothing is pre-loaded.

---

## 1 · Drop the files in cold (45s)

**Ingest** → drag in all six files from `messy/`. Leave the as-of date as it is.

> "Six files, four systems. Nobody told it which is which — the type comes from the
> contents, because real exports are called `Book1.csv`."

Press **Ingest**. It jumps to the canvas.

## 2 · Watch the canvas light up (45s)

Steps turn over as the run streams in. Point at:

- **Intake** — six files in, each classified with a confidence
- **Identity** — the number of links it made
- **Rules** — the findings coming out

> "Each step is isolated. If one fails it becomes a blocker naming itself and the rest
> still run — you get a report, not a stack trace."

Click **Schedule** → the drawer shows what it read from the PDF and how.

## 3 · Marc → Marcus (45s)

**People** → **Marcus Bell** → the evidence graph.

> "Payroll calls him `BELL, MARCUS`. The rota says `Marc Bell`. HR says `Marcus Bell`.
> One person."

Click the edge from the schedule record. The **waterfall** opens:

| | |
|---|---|
| family name exact | **+6.0** |
| given name, known variant | **+3.5** |
| role same | **+1.5** |
| site same | **+1.0** |
| **total** | **12.0 → linked automatically** |

> "No machine learning. Every link can be read out loud, and the threshold is in a
> config file a judge can change."

Scroll to **Attributes**: HR and the verification service disagree on an expiry date.
Both are shown — nothing was overwritten.

## 4 · Walk the critical findings (60s)

**Flags** → **CRITICAL** tab. Pick three:

- **Paid, and in no other system** — "Payroll pays Miguel Torres 32 hours at Riverdale.
  He is in no other system. That is either agency staff nobody recorded, or money
  leaving the building."
- **Worked after their credential expired** — click **Evidence**: the PDF page appears
  with the exact cell boxed. "That is the rota, that is the shift, that is the day
  after her certification lapsed."
- **No registered nurse on duty** — "Riverdale, Sunday. Federal rules require an RN on
  duty eight consecutive hours, seven days a week."

## 5 · Resolve one and re-run (30s)

On any finding: type a reason, **Dismiss**. Then **Pipeline** → **Re-run with current
decisions**.

> "The decision is keyed on the content of the record, not its row number — so it
> survives the next export. Settings has the audit log."

## 6 · The three problems (60s)

- **Staffing** — "Every quarter this takes weeks." Reported hours by day, already split
  at midnight with meal time excluded, each figure marked as verified, in conflict, or
  rota-only. The filing period and deadline are named. The assumptions are on screen,
  because a number whose assumptions are hidden is not auditable.
- **Expirations** — "We find out too late." One list, most urgent first, including
  vendor paperwork. Two columns a date alone cannot give you: shifts already worked
  after expiry, and whether the aide recertification can be supported by the hours we
  hold.
- **Referrals** — "By the time we get through them the patient has gone elsewhere."
  Pick a site and a day: a verdict with reasons, who is on, whether an RN covers eight
  unbroken hours, and what one more resident would do to the ratios.

## 7 · Chaos coverage (30s)

**Chaos** → 62 mutations, every P0 rule exercised.

> "Each one breaks the clean sample in one specific way and asserts two things: what
> we must notice, and what we must *not* say. The second column is the important one
> — a system that panics about a renamed column header is as useless as one that
> misses a ghost employee."

---

## If the live run misbehaves

**Pipeline** → **Replay last run**. The canvas re-streams the stored event log with
nothing recomputed. Or drop to the CLI, which needs no browser:

```bash
python -m sot ingest data/samples/healthcare/messy --as-of 2026-09-21
```

## The one-line version

> Four messy files in, a reconciled picture out, and every number on every screen can
> be traced back to the cell it came from.
