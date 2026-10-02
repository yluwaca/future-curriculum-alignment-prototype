from app.services.ingestion.curriculum_pdf_service import CurriculumPDFIngestionService


def test_subject_outcome_labels_are_not_module_codes():
    assert CurriculumPDFIngestionService.extract_module_code("SO1 Introduction to Project Management") is None
    assert CurriculumPDFIngestionService.extract_module_code("LO2 Apply scheduling methods") is None
    assert CurriculumPDFIngestionService.extract_module_code("ELO3 Demonstrate professional practice") is None
    assert CurriculumPDFIngestionService.extract_module_code("CCFO1 Identify and solve problems") is None
    assert CurriculumPDFIngestionService.extract_module_code("CREDITS4") is None
    assert CurriculumPDFIngestionService.extract_module_code("THEMES12") is None


def test_real_module_code_is_preferred_after_outcome_label():
    text = "SO1 Introduction to Project Management\nPFD470S Professional Development Methods"
    assert CurriculumPDFIngestionService.extract_module_code(text) == "PFD470S"


def test_explicit_subject_code_remains_authoritative():
    text = "Subject code: PFD470S\nSO1 Introduction to Project Management"
    assert CurriculumPDFIngestionService.extract_module_code(text) == "PFD470S"


def test_study_guide_treats_programme_specific_codes_as_aliases():
    service = CurriculumPDFIngestionService()
    pages = [{
        "page_number": 1,
        "text": "PROJECTS IV\nPRJ470S\nPRJ471S\nPRJ472S\nNQF LEVEL: 7",
    }]

    structure = service.extract_curriculum_structure(pages, declared_evidence_type="study_guide")

    assert [item["module_code"] for item in structure["modules"]] == ["PRJ470S"]
