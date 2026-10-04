"""Working out what a file is from its contents."""

from __future__ import annotations

from sot.ingest.detect import MEDIA_PDF, MEDIA_TABULAR, classify_grid, detect_media_kind, is_xlsx
from sot.ingest.reader import read_delimited

PAYROLL = (
    "payroll_id,employee_name,job_code,facility_code,period_start,period_end,hours_paid\n"
    'P-1,"REYES, SOFIA",RN,BYS,2026-09-14,2026-09-20,36\n'
)
ROSTER = (
    "employee_id,first_name,last_name,job_title,facility,phone,license_number,"
    "license_expiration,hire_date\n"
    "E1,Sofia,Reyes,Registered Nurse,Harborview Bayside,718-555-0201,RN-1,2027-05-31,2020-03-02\n"
)


def _classify(text: str, pack, **kwargs):
    return classify_grid(read_delimited(text.encode()).rows, pack, **kwargs)


def test_pdf_is_recognised_by_its_leading_bytes():
    assert detect_media_kind(b"%PDF-1.7\n...", "anything.txt") == MEDIA_PDF


def test_a_misleading_extension_does_not_win():
    """M46: filenames lie. Book1.xlsx holding CSV is still CSV."""
    assert detect_media_kind(b"a,b,c\n1,2,3\n", "schedule.pdf") == MEDIA_TABULAR


def test_a_workbook_is_recognised_by_its_contents():
    from io import BytesIO

    from openpyxl import Workbook

    buffer = BytesIO()
    Workbook().save(buffer)
    assert is_xlsx(buffer.getvalue())
    assert detect_media_kind(buffer.getvalue(), "x.csv") == MEDIA_TABULAR


def test_a_random_zip_is_not_a_workbook():
    from io import BytesIO
    from zipfile import ZipFile

    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("readme.txt", "hello")
    assert not is_xlsx(buffer.getvalue())


def test_each_source_is_classified_correctly(pack):
    assert _classify(PAYROLL, pack).source == "payroll"
    assert _classify(ROSTER, pack).source == "hr"


def test_classification_is_confident_not_marginal(pack):
    """A thin margin would mean one odd column could flip a file to the wrong source."""
    for text in (PAYROLL, ROSTER):
        detection = _classify(text, pack)
        assert detection.score >= 0.7
        assert detection.margin >= 0.3


def test_a_preamble_before_the_header_is_skipped(pack):
    text = "Quarterly payroll export\nGenerated 2026-09-21\n\n" + PAYROLL
    detection = _classify(text, pack)
    assert detection.source == "payroll"
    assert detection.header_row_index == 3


def test_an_unrelated_file_is_refused_rather_than_guessed(pack):
    """M58: an inventory list dropped in with the real sources."""
    detection = _classify("sku,description,qty,unit_price\nA1,Gloves,400,3.20\n", pack)
    assert detection.source is None
    assert "below the" in detection.reason


def test_an_empty_file_is_refused(pack):
    assert _classify("", pack).source is None


def test_an_override_forces_the_source(pack):
    detection = _classify("sku,description,qty\nA1,Gloves,400\n", pack, override="payroll")
    assert detection.source == "payroll"
    assert detection.method == "override"


def test_an_override_naming_an_unknown_source_is_reported(pack):
    detection = _classify(PAYROLL, pack, override="nonsense")
    assert detection.source is None
    assert "nonsense" in detection.reason


def test_renamed_headers_still_classify(pack):
    """M01 at the file level, not just the column level."""
    renamed = (
        "Pay ID,Employee,Position Code,Cost Centre,Week Start,Week End,Hrs\n1,x,RN,BYS,a,b,8\n"
    )
    assert _classify(renamed, pack).source == "payroll"


def test_every_contract_is_scored_so_the_flag_can_explain_itself(pack):
    detection = _classify(PAYROLL, pack)
    assert set(detection.scores) == {c.source for c in pack.contracts}
    assert detection.best_alternatives(2)[0][0] == "payroll"
