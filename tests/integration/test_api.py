"""The API, against a real ingested run.

One run is performed at module scope and every endpoint is asked about it, because
the thing worth testing is that the API answers questions about real output - not
that it returns 200 for an empty database.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sot.api.app import create_app

SAMPLES = Path(__file__).resolve().parent.parent.parent / "data" / "samples" / "healthcare"
AS_OF = "2026-09-21"


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture(scope="module")
def run(client: TestClient) -> dict:
    """Ingest the clean set through the API, the way the browser does."""
    files = [
        ("files", (path.name, io.BytesIO(path.read_bytes()), "application/octet-stream"))
        for path in sorted((SAMPLES / "clean").iterdir())
    ]
    response = client.post(
        "/api/ingest", files=files, data={"as_of": AS_OF, "pack": "healthcare_ny"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["run_id"]
    # The run continues in the background; wait for it to land.
    for _ in range(400):
        detail = client.get(f"/api/runs/{body['run_id']}").json()
        if detail["status"] != "RUNNING":
            return detail
        import time

        time.sleep(0.05)
    raise AssertionError("the run did not finish")


# --- ingest and runs --------------------------------------------------------


def test_an_upload_starts_a_run_and_returns_its_id_immediately(run):
    """Returned before the run finishes, so the canvas can watch it happen rather
    than waiting on a blank screen."""
    assert run["run_id"].startswith("R-")
    assert run["status"] in {"OK", "DEGRADED"}


def test_the_run_reports_what_each_step_did(run):
    nodes = {node["node_id"]: node for node in run["nodes"]}
    assert {"intake", "resolve", "ledger", "match", "staffing", "views", "rules"} <= set(nodes)
    assert nodes["intake"]["rows_in"] == 6
    assert all(node["status"] in {"ok", "degraded"} for node in run["nodes"])


def test_the_run_lists_the_files_it_was_given(run):
    names = {item["original_name"] for item in run["files"]}
    assert "roster_export.csv" in names
    assert "weekly_schedule.pdf" in names
    assert all(item["detected_source"] for item in run["files"] if item["media_kind"] == "tabular")


def test_the_clean_run_reports_nothing_above_info(run):
    assert run["flags"].get("CRITICAL", 0) == 0
    assert run["flags"].get("WARNING", 0) == 0
    assert run["flags"].get("BLOCKER", 0) == 0


def test_runs_can_be_listed(client, run):
    body = client.get("/api/runs").json()
    assert run["run_id"] in {item["run_id"] for item in body["runs"]}


def test_latest_is_an_alias_for_the_most_recent_run(client, run):
    assert client.get("/api/runs/latest").json()["run_id"] == run["run_id"]


def test_an_unknown_run_is_a_clean_404(client):
    assert client.get("/api/runs/R-nope").status_code == 404


# --- events -----------------------------------------------------------------


def test_a_finished_run_replays_its_stored_events(client, run):
    """The demo-day fallback: the canvas lights up exactly as it did, with nothing
    recomputed and nothing that can fail twice."""
    body = client.post(f"/api/runs/{run['run_id']}/replay").json()
    assert body["events"] > 0
    with client.stream("GET", body["stream"]) as response:
        assert response.status_code == 200
        text = "".join(chunk for chunk in response.iter_text())
    assert "node_finished" in text
    assert "run_finished" in text


# --- flags ------------------------------------------------------------------


def test_flags_come_back_worst_first(client, run):
    body = client.get("/api/flags", params={"run_id": run["run_id"]}).json()
    order = ["BLOCKER", "CRITICAL", "WARNING", "INFO"]
    seen = [order.index(flag["severity"]) for flag in body["flags"]]
    assert seen == sorted(seen)


def test_flags_can_be_filtered(client, run):
    body = client.get("/api/flags", params={"run_id": run["run_id"], "severity": "INFO"}).json()
    assert body["flags"]
    assert {flag["severity"] for flag in body["flags"]} == {"INFO"}


def test_a_flag_detail_carries_its_evidence_and_what_the_rule_means(client, run):
    listing = client.get("/api/flags", params={"run_id": run["run_id"]}).json()
    flag_id = listing["flags"][0]["flag_id"]
    body = client.get(f"/api/flags/{flag_id}", params={"run_id": run["run_id"]}).json()
    assert body["suggested_action"]
    assert body["rule"]["meaning"]
    assert isinstance(body["evidence"], list)


def test_the_rule_catalog_is_served(client):
    body = client.get("/api/rules").json()
    assert len(body["rules"]) >= 80
    assert all(rule["meaning"] for rule in body["rules"])


# --- people -----------------------------------------------------------------


def test_people_are_listed_with_their_credentials(client, run):
    body = client.get("/api/persons", params={"run_id": run["run_id"]}).json()
    assert len(body["persons"]) == 10
    assert all(person["display_name"] for person in body["persons"])
    assert any(person["credentials"] for person in body["persons"])


def test_a_person_shows_every_claim_behind_every_value(client, run):
    """The losing claims are the point: this is how the page shows two systems
    disagreeing rather than quietly siding with one."""
    listing = client.get("/api/persons", params={"run_id": run["run_id"]}).json()
    person_id = listing["persons"][0]["person_id"]
    body = client.get(f"/api/persons/{person_id}", params={"run_id": run["run_id"]}).json()
    assert body["attributes"]
    attribute = body["attributes"][0]
    assert attribute["won_because"]
    assert attribute["all_claims"]
    assert body["shifts"] or body["weeks"]


def test_the_evidence_graph_carries_the_score_waterfall(client, run):
    listing = client.get("/api/persons", params={"run_id": run["run_id"]}).json()
    person_id = next(person["person_id"] for person in listing["persons"] if person["credentials"])
    body = client.get(f"/api/persons/{person_id}/graph", params={"run_id": run["run_id"]}).json()
    kinds = {node["kind"] for node in body["nodes"]}
    assert {"person", "record"} <= kinds
    scored = [edge for edge in body["edges"] if edge.get("explanation", {}).get("features")]
    assert scored, "at least one link should show how it was decided"
    assert {"feature", "level", "weight"} <= set(scored[0]["explanation"]["features"][0])


# --- views ------------------------------------------------------------------


def test_staffing_returns_hours_and_the_assumptions_behind_them(client, run):
    body = client.get("/api/views/staffing", params={"run_id": run["run_id"]}).json()
    assert body["rows"]
    assert body["assumptions"]["meal_deduction_minutes"] == 30
    assert body["assumptions"]["split_at_midnight"] is True
    assert {row["tier"] for row in body["rows"]} <= {
        "VERIFIED",
        "CONFLICT",
        "SCHEDULE_ONLY",
        "UNALLOCATED",
    }


def test_the_staffing_summary_names_the_filing_period(client, run):
    body = client.get("/api/views/staffing", params={"run_id": run["run_id"]}).json()
    assert body["summaries"]
    summary = body["summaries"][0]
    assert "FFY" in summary["quarter"]
    assert summary["quarter_due"]
    assert summary["pct_verified"] == 100.0, "the clean set reconciles completely"


def test_staffing_can_be_filtered_by_facility(client, run):
    body = client.get(
        "/api/views/staffing", params={"run_id": run["run_id"], "facility": "BYS"}
    ).json()
    assert {row["facility"] for row in body["rows"]} == {"BYS"}


def test_expirations_come_back_most_urgent_first(client, run):
    body = client.get("/api/views/expirations", params={"run_id": run["run_id"]}).json()
    assert body["rows"]
    days = [row["days_left"] for row in body["rows"] if row["days_left"] is not None]
    assert days == sorted(days)
    assert body["windows"] == [90, 60, 30, 14]


def test_expirations_cover_vendor_paperwork_too(client, run):
    """The same model, which is the point of making a credential its own entity."""
    body = client.get("/api/views/expirations", params={"run_id": run["run_id"]}).json()
    assert {row["holder_type"] for row in body["rows"]} == {"person", "org"}


def test_referral_answers_yes_for_a_compliant_day(client, run):
    body = client.get(
        "/api/views/referral",
        params={"run_id": run["run_id"], "facility": "BYS", "work_date": "2026-09-14"},
    ).json()
    assert body["verdict"] == "YES"
    assert body["rn_covered"] == "PASS"
    assert body["on_duty"]
    assert all(person["credential_status"] == "PASS" for person in body["on_duty"])
    assert "quarterly average" in body["note"]


def test_referral_is_unknown_for_a_day_outside_the_rota(client, run):
    """Not "no". We have no record of that day, which is a different answer."""
    body = client.get(
        "/api/views/referral",
        params={"run_id": run["run_id"], "facility": "BYS", "work_date": "2026-11-01"},
    ).json()
    assert body["verdict"] == "UNKNOWN"


def test_referral_shows_the_effect_of_one_more_resident(client, run):
    body = client.get(
        "/api/views/referral",
        params={
            "run_id": run["run_id"],
            "facility": "BYS",
            "work_date": "2026-09-14",
            "census": 3,
            "plus_one": True,
        },
    ).json()
    assert body["hprd"]["total"] > body["hprd_plus_one"]["total"]


def test_a_bad_date_is_refused_with_a_message(client, run):
    response = client.get(
        "/api/views/referral",
        params={"run_id": run["run_id"], "facility": "BYS", "work_date": "last tuesday"},
    )
    assert response.status_code == 400
    assert "YYYY-MM-DD" in response.json()["detail"]


# --- evidence ---------------------------------------------------------------


def test_a_source_row_can_be_fetched_with_its_neighbours(client, run):
    files = client.get(f"/api/runs/{run['run_id']}").json()["files"]
    assert files
    detail = client.get(f"/api/runs/{run['run_id']}").json()
    del detail
    listing = client.get("/api/flags", params={"run_id": run["run_id"]}).json()
    evidence = None
    for flag in listing["flags"]:
        full = client.get(f"/api/flags/{flag['flag_id']}", params={"run_id": run["run_id"]}).json()
        evidence = next(
            (item for item in full["evidence"] if item["row"] and item["file_id"]), None
        )
        if evidence:
            break
    assert evidence, "at least one finding should point at a row"
    body = client.get(
        f"/api/evidence/file/{evidence['file_id']}/row/{evidence['row']}",
        params={"run_id": run["run_id"]},
    ).json()
    assert body["raw"]
    assert len(body["context"]) > 1


def test_a_schedule_page_renders_as_an_image(client, run):
    pdf = next(
        item
        for item in client.get(f"/api/runs/{run['run_id']}").json()["files"]
        if item["media_kind"] == "pdf"
    )
    del pdf
    files = client.get("/api/flags", params={"run_id": run["run_id"]}).json()
    del files
    database_files = client.get(f"/api/runs/{run['run_id']}").json()["files"]
    assert any(item["media_kind"] == "pdf" for item in database_files)


def test_page_cells_carry_their_rectangles(client, run):
    """Without geometry the evidence viewer has nothing to highlight."""
    from sot.api import deps

    row = deps.db().query_one(
        "SELECT file_id FROM pdf_cells WHERE run_id = ? LIMIT 1", [run["run_id"]]
    )
    assert row
    body = client.get(
        f"/api/evidence/pdf/{row['file_id']}/page/1/cells", params={"run_id": run["run_id"]}
    ).json()
    assert body["cells"]
    assert all(len(cell["bbox"]) == 4 for cell in body["cells"])
    assert body["render_scale"] > 1


def test_a_page_image_is_served(client, run):
    from sot.api import deps

    row = deps.db().query_one(
        "SELECT file_id FROM pdf_cells WHERE run_id = ? LIMIT 1", [run["run_id"]]
    )
    response = client.get(f"/api/evidence/pdf/{row['file_id']}/page/1.png")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert len(response.content) > 1000


# --- exports ----------------------------------------------------------------


@pytest.mark.parametrize(
    "name", ["flags", "pbj_daily_hours", "person_weeks", "credentials", "claims", "golden"]
)
def test_each_export_produces_a_csv(client, run, name: str):
    response = client.get(f"/api/exports/{name}.csv", params={"run_id": run["run_id"]})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    lines = response.text.strip().splitlines()
    assert len(lines) > 1, f"{name} produced only a header"


def test_an_unknown_export_says_what_is_available(client):
    response = client.get("/api/exports/nonsense.csv")
    assert response.status_code == 404
    assert "available" in response.json()["detail"]


# --- decisions and parameters -----------------------------------------------


def test_a_decision_can_be_recorded_and_withdrawn(client):
    created = client.post(
        "/api/decisions",
        json={
            "decision_type": "ACCEPT_MATCH",
            "key": {"fingerprint": "RF-test"},
            "value": {"person_id": "P-E201"},
            "reason": "checked against the timesheet",
        },
    )
    assert created.status_code == 200
    decision_id = created.json()["decision_id"]

    listing = client.get("/api/decisions").json()
    assert decision_id in {item["decision_id"] for item in listing["decisions"]}

    client.delete(f"/api/decisions/{decision_id}")
    after = client.get("/api/decisions").json()
    withdrawn = next(item for item in after["decisions"] if item["decision_id"] == decision_id)
    assert withdrawn["active"] is False, "kept in the log, marked inactive"


def test_an_unknown_decision_type_is_refused(client):
    response = client.post("/api/decisions", json={"decision_type": "NONSENSE", "key": {"a": 1}})
    assert response.status_code == 400


def test_the_editable_parameters_carry_their_limits(client):
    body = client.get("/api/pipeline/params").json()
    keys = {item["key"] for item in body["params"]}
    assert "hours_tolerance" in keys
    assert "rn_min_consecutive_hours" in keys
    tolerance = next(item for item in body["params"] if item["key"] == "hours_tolerance")
    assert tolerance["value"] == 0.25
    assert tolerance["max"] is not None


def test_a_parameter_outside_its_range_is_refused(client):
    response = client.put("/api/pipeline/params", json={"values": {"hours_tolerance": 999}})
    assert response.status_code == 400
    assert "at most" in str(response.json()["detail"])


def test_a_parameter_that_is_not_editable_is_refused(client):
    """Structural change is a code change, not a form field."""
    response = client.put("/api/pipeline/params", json={"values": {"week_start": "sunday"}})
    assert response.status_code == 400


def test_a_valid_parameter_change_is_saved_and_can_be_reset(client):
    updated = client.put("/api/pipeline/params", json={"values": {"hours_tolerance": 0.5}})
    assert updated.status_code == 200
    assert client.get("/api/pipeline/params").json()
    after = next(
        item
        for item in client.get("/api/pipeline/params").json()["params"]
        if item["key"] == "hours_tolerance"
    )
    assert after["value"] == 0.5
    assert after["overridden"] is True
    assert after["default"] == 0.25, "the shipped value stays visible"

    client.delete("/api/pipeline/params")
    restored = next(
        item
        for item in client.get("/api/pipeline/params").json()["params"]
        if item["key"] == "hours_tolerance"
    )
    assert restored["value"] == 0.25


# --- the pipeline graph -----------------------------------------------------


def test_the_graph_is_served_with_the_latest_numbers_on_each_step(client, run):
    body = client.get("/api/pipeline", params={"run_id": run["run_id"]}).json()
    assert len(body["nodes"]) >= 10
    assert body["order"][0] == "intake"
    intake = next(node for node in body["nodes"] if node["id"] == "intake")
    assert intake["stats"]["rows_in"] == 6
    assert all("port" in edge for edge in body["edges"])


def test_every_step_in_the_graph_declares_what_it_does(client):
    body = client.get("/api/pipeline").json()
    assert all(node["description"] for node in body["nodes"])
    assert all(node["label"] for node in body["nodes"])
