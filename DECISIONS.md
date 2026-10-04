# Decisions

Why the system is built the way it is. Written as the work happens, trimmed to two pages
at the end.

## Determinism is enforced, not hoped for

The same files, decisions, and as-of date must give identical output in any file order.
Three things quietly break that, so each is handled in one place:

- **Hashing.** Every stable identifier is blake2b over canonical JSON (`sot/ids.py`).
  Python's builtin `hash()` is salted per process, so an id derived from it changes
  between runs. A test spawns two subprocesses with different `PYTHONHASHSEED` values and
  asserts the ids match.
- **Ordering.** Unordered collections are sorted with an explicit key before becoming
  output (`sot/canon.py`). Mixed-type columns still sort, rather than raising.
- **Float accumulation.** Hour totals are summed in sorted order and rounded once, so a
  reshuffled set of shift segments cannot change a weekly total.

## Provisional person IDs use the cluster, not the first record

The spec derives a provisional id from "the first record's" name, role, and facility.
First depends on which file was read first, which contradicts the reproducibility
principle. The lexicographically smallest key in the cluster is used instead: same
intent, and the id no longer moves when uploads arrive in a different order.

## Unknown is a value, not a missing boolean

Checks return `PASS`, `FAIL`, or `UNKNOWN` (`sot/tri.py`), with Kleene combinators. An
empty series is `UNKNOWN`, never vacuously true — "every worked day was covered by a
valid credential" must not pass when no days are on record, because the usual cause is a
source that failed to load. Reporting that as compliant is precisely the failure the
three-valued rule exists to prevent.

## One standardized table, with views for readability

`std_records` holds every standardized record keyed by a canonical *source role*
(roster, payroll, credentials, schedule), with pack-mapped fields in JSON. The spec's
`std_hr`, `std_payroll`, and `std_licenses` exist as views over it. This is what lets the
trucking pack reuse every node downstream of ingestion: its sources differ, the engine
does not. Packs map their raw columns onto one shared canonical vocabulary, so trucking's
`cdl_number` becomes `license_number` and `terminal` becomes `facility_code`.

## Sample data cannot leak into the engine

The judges supply their own files. Any sample name, id, or date compiled into `sot/`
would work for our demo and not for theirs, and would not necessarily fail loudly. A test
greps the engine for sample literals, identifier shapes, and every identifying value
found in the generated fixtures, and fails on a hit. `packs/`, `scripts/`, `data/`, and
`tests/` are exempt, because that is where sample values belong.

The application title is allowed to contain the client's name; a facility name is not.

## Dependencies

Exactly the libraries the spec lists, pinned to exact versions with a lockfile. No
workflow engine: the DAG executor is small enough to read in one sitting, and reading it
is part of what the judges are being asked to do.

## Classification weights required columns, and ignores extra ones

A file is identified by how much of a contract's column signature it matches. Required
columns count three times an optional one, for two reasons: they are what makes a
source recognisable, and without the weighting, teaching the system more synonyms would
dilute every signature — the system would get worse the more it knew.

Extra columns in the file are not penalised at all. A real export has columns we have
never heard of, and a classifier that reads that as "not payroll" is useless on real
data. A column we do not understand is kept as evidence rather than dropped; it may be
the thing that explains a discrepancy later.

## Human decisions are applied before automatic matching, not after

The spec orders header matching as exact synonym, then similarity, then stored
decisions. Stored decisions are applied first instead. Someone who has already answered
"this column is the pay period start" should not be overruled by a fuzzy match that
happens to score well, and identity resolution applies human decisions first for the
same reason.

## Detection is overruled for single-byte encodings

Character-set detection is statistical, and the Windows codepages differ only in which
accented letters the high bytes mean — so a short sample cannot distinguish them. Given
a Spanish surname in Windows-1252, detection reports Windows-1250 and turns ñ into ń.
Wrong-but-plausible is the worst possible outcome for a name, because nobody notices.
The assumed codepage is explicit and configurable, the fallback is always flagged, and
the flag tells the reader to check any name that looks wrong.

## A row is repaired only where a name belongs

An unquoted `LAST, FIRST` splits a row into one field too many, and rejoining it is
usually right. But a pair of three-letter codes is indistinguishable from a surname and
a given name, so an unrestricted repair silently corrupts rows that broke for some other
reason. Repair therefore requires the merge to land on a column the contract says holds
a person's name. A quarantined row is recoverable; a wrongly repaired one is not.

## Duplicate means "twice in this upload"

Re-ingesting the same file in a later run is the normal case — it is what the rerun
button does — so flagging it every time would be noise. `FILE_DUPLICATE` fires when the
same bytes arrive twice in one upload. The file registry is still content-addressed
across runs, so evidence raised three runs ago still points at the exact bytes.

## Row numbers are physical lines

The spec fixes the convention as "header is row 1, first data row is row 2". For a file
with a preamble above the header, the more useful number is the one the user sees in
their spreadsheet, so row numbers are physical 1-based lines. For a file without a
preamble the two are identical, which is the case the spec describes.

## Every rule is declared before it is implemented

All 81 codes from the rule catalog exist as data from the start, including the ones
whose evaluator is not written. That makes the generated documentation complete, lets
the chaos deck demand coverage of codes that should exist, and turns "which P0 rules are
still missing" into a query instead of a memory exercise.

## The footnote beats the clock, and disagreements are kept

A printed rota says at the bottom what its shifts are worth: "7a-3p, 3p-11p, 11p-7a
are 8 hours". That is the facility telling us how it counts its own time, breaks
included, and it wins over subtracting one clock time from another. Where the two
disagree the footnote is used and the difference is reported, because an unpaid break
is exactly the kind of thing that turns a reconciliation into an argument.

Where the footnote is silent, the clock decides and the segment says so. Where there
is no footnote at all, every segment says so.

## A cell saying PTO does not say how long

Paid leave has to be worth some number of hours or the week will not reconcile, and
the rota does not supply one. The person's own usual shift that week is used, falling
back to the facility's commonest shift, and the segment records that the figure was
assumed rather than read. A facility whose leave day is not a normal shift length will
see the difference in the variance, which is the right place for it to show up.

## An ambiguous shift is matched against the page, then refused

`7-3` could be eight hours or twenty. It is matched against the shifts the page's own
footnote defines, which resolves it exactly when the facility has told us what it runs.
Without a footnote it reads as a day shift, which is what a bare range on a rota
overwhelmingly means. If neither gives a plausible length it is refused and flagged,
because an invented twenty-hour shift would quietly become reported staffing.

## Equal start and end is a full day, not nothing

A shift from 7a to 7a is almost certainly a mistake in the source. Reading it as 24
hours gets it caught by the daily cap rule; reading it as zero would hide it. When in
doubt, prefer the reading that raises a flag.

## Names keep two forms

The comparison key is folded hard - accents stripped, punctuation removed, lowercased -
because a system that cannot write accents has not given us a different person. The
display form keeps every accent and apostrophe. Getting somebody's name wrong on screen
is its own kind of failure, and the two requirements are irreconcilable in one string.

## A column is read before its values are

One date with a day above twelve settles the order for the whole column, and that is
evidence rather than an assumption about the exporting system. So normalization runs in
two passes: collect the column, decide how to read it, then parse each value. The flag
says which it used and why.

## Adapters report findings, not flags

An adapter returns a rule code and the values its message needs; the caller decides
what becomes a flag. That keeps the adapters testable without the rule machinery and
keeps the decision about severity in one place.

## A continuation page and an unrecognised page are different

A page with a table and no facility might be a table that spilled over - in which case
it quietly continues the page before it - or a page whose title names a site we do not
know, in which case the facility has to be inferred from the staff listed and the
assumption reported. They are told apart by whether anything is printed above the
table, which is the only signal that actually distinguishes them.

## Hand-set match weights, not a model

Each feature contributes evidence for or against two records being the same person,
the evidence is summed, and the total falls into one of three bands: link it, ask a
human, or leave it alone. The weights live in the pack.

Deliberately not machine learning. There is no labelled training data for this client,
the cost of a wrong automatic link is somebody being paid or rostered as the wrong
person, and a judge is entitled to ask why any particular link was made. Hand-set
weights answer that in one sentence per feature. A model would answer it with a number
nobody can argue with, which is worse.

Every link stores the features that produced it - what was compared, at what level,
for what weight - so the person page can show the whole derivation.

## Three steps, in order of how wrong each is willing to be

Human decisions first: somebody already answered this and does not get a second
opinion. Then the credential number, which is issued to exactly one person and settles
the question outright - which is what lets a credential under a previous surname still
link, with the name difference reported rather than the link refused. Only what is
left reaches the weighted matcher.

## Two records claiming one slot

A person has one payroll row per period, role and site, and appears once on a rota
page. Two records claiming the same slot is either a look-alike that belongs to
somebody else, or a genuine duplicate. The first is reassigned when there is another
candidate good enough on its own; the second stays linked and is flagged, because a
duplicated payment is the finding, not an inconvenience to route around.

The slot is namespaced by source. Being paid for a week and being on that week's rota
are the two halves of a match, not two claims on one slot.

## Unmatched records become people

A nurse who is paid but is in no other system is the single most interesting thing
this system can find, and she only stays visible if she has somewhere to be. Every
unmatched record becomes a provisional person, grouped by name, role and site so the
same unknown person appearing in payroll and on the rota is one person rather than two.

## A missing source is one finding

Ingesting payroll with no roster would otherwise flag every row as a possible ghost
employee. That is true and useless. The spec has no code for an absent source, so
`SOURCE_MISSING` was added, with the expected sources declared in the pack - the same
principle the spec already applies to sources that cover different periods.

## Precision over recall

A missed link becomes a visible flag that a human resolves in seconds. A wrong link
quietly pays the wrong person and is never noticed. So the bands are set to refuse
rather than guess, and the measured target is precision.
