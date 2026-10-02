"""
Pluggable connector contracts for future institutional and external sources.
"""

from app.services.future_hooks.base import PlannedConnector


class LMSConnector(PlannedConnector):
    connector_key = "lms_connector"
    display_name = "Learning Management System Connector"
    source_category = "institutional"
    source_type = "lms"
    connector_type = "lms_connector"
    capabilities = [
        "course_catalogue_discovery",
        "module_outline_ingestion",
        "assessment_artifact_metadata",
    ]


class SISConnector(PlannedConnector):
    connector_key = "sis_connector"
    display_name = "Student Information System Connector"
    source_category = "institutional"
    source_type = "sis"
    connector_type = "sis_connector"
    capabilities = [
        "programme_catalogue_discovery",
        "enrolment_context_ingestion",
        "department_structure_sync",
    ]


class ERPConnector(PlannedConnector):
    connector_key = "erp_connector"
    display_name = "ERP Connector"
    source_category = "institutional"
    source_type = "erp"
    connector_type = "erp_connector"
    capabilities = [
        "organisational_unit_sync",
        "planning_reference_data",
        "approved_programme_metadata",
    ]


class ProfessionalBodySource(PlannedConnector):
    connector_key = "professional_body_source"
    display_name = "Professional Body Source"
    source_category = "reference"
    source_type = "professional_body"
    connector_type = "professional_body_source"
    capabilities = [
        "competency_framework_ingestion",
        "accreditation_requirement_tracking",
        "standard_versioning",
    ]


class IndustryAssociationSource(PlannedConnector):
    connector_key = "industry_association_source"
    display_name = "Industry Association Source"
    source_category = "labour_market"
    source_type = "industry_association"
    connector_type = "industry_association_source"
    capabilities = [
        "sector_skill_signal_ingestion",
        "emerging_skill_watchlists",
        "industry_report_ingestion",
    ]

