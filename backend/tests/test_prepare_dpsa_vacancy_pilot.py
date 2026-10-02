from pathlib import Path
import importlib.util
import sys


SCRIPT = Path(__file__).parents[1] / "scripts" / "prepare_dpsa_vacancy_pilot.py"
SPEC = importlib.util.spec_from_file_location("prepare_dpsa", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_labelled_field_stops_at_next_label():
    block = "REQUIREMENTS : Python and SQL.\nDUTIES : Build systems.\nENQUIRIES : Example"
    assert MODULE.labelled(block, "REQUIREMENTS") == "Python and SQL."
    assert MODULE.labelled(block, "DUTIES") == "Build systems."


def test_parse_date_is_iso_or_empty():
    assert MODULE.parse_date("Closing at 17 April 2026 at 16:00") == "2026-04-17"
    assert MODULE.parse_date("not supplied") == ""


def test_ict_filter_terms_are_specific():
    assert MODULE.ICT_TITLE_TERMS.search("Assistant Director: Information Management")
    assert MODULE.ICT_REQUIREMENT_TERMS.search("Degree in computer science")
    assert not MODULE.ICT_TITLE_TERMS.search("Professional Nurse")
    assert not MODULE.ICT_TITLE_TERMS.search("Director: Finance")
