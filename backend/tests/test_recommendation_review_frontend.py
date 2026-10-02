"""Frontend regression tests for the Recommendations "Review Recommendation" modal.

Guards the approve/reject submission contract on frontend/recommendations.js and
frontend/recommendations.html:

- the submitted payload (reason + feedback for approve/reject; modify-only fields
  restricted to the modify flow),
- the submit handler MUST inspect `response.ok` and surface server validation
  errors as field-level dialog errors (no silent success/failure),
- the Confirm button reports failed validation and never closes the modal before
  a successful, 2xx review response,
- on success the authoritative refresh keeps the review queue/dossier consistent
  so the server-side audit trail stays visible.

Tests are DB-free source-inspection guards, following test_adzuna_workflow_ui.py.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
DEPLOY_FRONTEND = ROOT / "Deploy" / "frontend"

RECOMMENDATIONS_JS = (FRONTEND / "recommendations.js").read_text(encoding="utf-8")
RECOMMENDATIONS_HTML = (FRONTEND / "recommendations.html").read_text(encoding="utf-8")
RECOMMENDATIONS_CSS = (FRONTEND / "recommendations.css").read_text(encoding="utf-8")


def test_deploy_frontend_mirror_matches_recommendations_sources():
    """The packaged Deploy/frontend copies must not drift from the source files."""
    for name in ("recommendations.js", "recommendations.html", "recommendations.css"):
        deploy = DEPLOY_FRONTEND / name
        source = FRONTEND / name
        assert deploy.exists(), f"{name} missing from Deploy/frontend"
        assert deploy.read_text(encoding="utf-8") == source.read_text(encoding="utf-8"), (
            f"Deploy/frontend/{name} does not match frontend/{name}"
        )


def test_approve_and_reject_submit_to_correct_endpoints():
    js = RECOMMENDATIONS_JS
    approve_block = (
        "if (currentAction === 'approve') "
        "endpoint = API_ENDPOINTS.ANALYTICS.RECOMMENDATION_APPROVE(selectedId);"
    )
    reject_block = (
        "else if (currentAction === 'reject') "
        "endpoint = API_ENDPOINTS.ANALYTICS.RECOMMENDATION_REJECT(selectedId);"
    )
    modify_block = (
        "else endpoint = API_ENDPOINTS.ANALYTICS.RECOMMENDATION_MODIFY(selectedId);"
    )
    assert approve_block in js
    assert reject_block in js
    assert modify_block in js


def test_test_submit_payload_shape_is_decided_per_action():
    js = RECOMMENDATIONS_JS
    # Common payload carries reason + feedback_comment only.
    assert "const payload = {" in js
    assert "reason," in js
    assert "feedback_comment: (modalFeedback.value || '').trim() || null," in js
    # The reason must come from client-side validation, not a silent default.
    assert "from review page" not in js
    # Modify-only fields are added inside the modify guard.
    modify_guard = """
  if (currentAction === 'modify') {
    payload.modified_title = (modalTitleInput.value || '').trim();
    payload.modified_description = (modalDescription.value || '').trim();
    payload.modified_priority = modalPriority.value;
  }
"""
    assert modify_guard in js


def test_submit_payload_carries_review_ids_decision_and_evidence_context():
    js = RECOMMENDATIONS_JS
    # The decision record must be traceable back to the recommendation being
    # reviewed and the requested action once it reaches the server.
    assert "recommendation_id: selectedId," in js
    assert "decision: currentAction," in js
    assert "evidence_reviewed: !!evidenceReviewedCheckbox.checked," in js
    assert "evidence_context: buildEvidenceContext(dossierData)," in js
    # buildEvidenceContext must surface skill, gap type, demand score, forecast,
    # curriculum coverage, labour evidence, confidence, sources and provenance.
    context_fn = js[js.index("function buildEvidenceContext(dossier)"):js.index("function renderModalContext(dossier = dossierData)")]
    for key in (
        "recommendation_id",
        "skill_name",
        "gap_type",
        "demand_score",
        "forecast",
        "curriculum_coverage",
        "confidence",
        "sources",
        "provenance",
        "evidence_links",
    ):
        assert key in context_fn, f"buildEvidenceContext missing {key!r}"
    assert "trend_direction" in context_fn
    assert "alignment_score" in context_fn


def test_evidence_reviewed_checkbox_gates_the_confirm_button():
    js = RECOMMENDATIONS_JS
    html = RECOMMENDATIONS_HTML
    # The acknowledgement checkbox must exist and be presented inside a labelled
    # wrapper so the requirement is visible to the reviewer.
    assert 'id="evidenceReviewedCheckbox"' in html
    assert 'class="review-evidence-label"' in html
    assert "reviewEvidenceCheckboxWrap" in js
    # The Confirm button starts disabled until evidence is acknowledged.
    assert "modalConfirm.disabled = true;" in js
    assert "function validateModalToggle()" in js
    assert "modalConfirm.disabled = !(reason && evidenceReviewed && modifyValid);" in js
    # Full validation (not just the gating) also enforces the acknowledgement
    # before any payload is submitted.
    assert "You must confirm that you reviewed the evidence before submitting." in js
    assert "if (!evidenceReviewedCheckbox.checked) {" in js
    assert "evidenceReviewedCheckbox.addEventListener('change', validateModalToggle)" in js
    # The gating wrapper exposes the requirement as a styled, invalid-able field.
    assert ".review-evidence-checkbox-wrap" in RECOMMENDATIONS_CSS
    assert ".review-evidence-checkbox-wrap.field-invalid" in RECOMMENDATIONS_CSS


def test_modal_renders_evidence_context_before_review():
    js = RECOMMENDATIONS_JS
    html = RECOMMENDATIONS_HTML
    # The evidence context panel is rendered inside the review modal.
    assert 'id="reviewModalContext"' in html
    assert "function renderModalContext(dossier = dossierData)" in js
    assert "renderModalContext(dossierData);" in js
    # The context is rendered on every open so it reflects the latest dossier.
    assert 'modal-review' in html
    assert ".modal-review" in RECOMMENDATIONS_CSS
    assert ".review-modal-context" in RECOMMENDATIONS_CSS
    # The Confirm button stays gated when the context could not be loaded.
    assert "modalConfirm.disabled = true;" in js


def test_opening_recommendation_renders_its_evidence_context_in_modal():
    """Selecting a recommendation loads its dossier via the detail API and the review
    modal renders that exact recommendation's evidence context (skill, gap type, demand,
    forecast, confidence, evidence count, provenance, evidence links)."""
    js = RECOMMENDATIONS_JS
    # Selecting a recommendation issues the detail (dossier) API request for that id.
    assert "el.addEventListener('click', () => {" in js
    assert "selectedId = el.dataset.id;" in js
    assert "loadDossier(selectedId);" in js
    # The dossier detail endpoint is called for the selected recommendation.
    assert "API_ENDPOINTS.ANALYTICS.RECOMMENDATION_DOSSIER(id)" in js
    # The modal is bound to the selected recommendation id when opened.
    assert "modal.dataset.recommendationId = selectedId" in js
    assert "renderModalContext(dossierData);" in js
    # The loaded dossier is the evidence payload for the review decision.
    assert "dossierForId = id;" in js
    assert "dossierForId === selectedId" in js
    # Rendered context rows: skill, gap type, demand score, forecast, confidence,
    # evidence count, provenance/source, and evidence links.
    context_section = js[js.index("reviewModalContext.innerHTML = `"):js.index("function setFieldInvalid")]
    for row in (
        "Recommendation ID",
        ">Skill<",
        ">Gap type<",
        ">Demand score<",
        ">Labour evidence count<",
        ">Forecast<",
        ">Forecast confidence<",
        ">Confidence<",
        ">Source<",
        ">Provenance<",
        "Labour evidence",
    ):
        assert row in context_section, f"modal context missing row {row!r}"
    assert "+${remaining} more" in context_section
    # buildEvidenceContext ships the evidence context with the review payload.
    assert "evidence_context: buildEvidenceContext(dossierData)," in js


def test_evidence_context_shows_loading_and_visible_error_on_dossier_failure():
    js = RECOMMENDATIONS_JS
    html = RECOMMENDATIONS_HTML
    # The dossier detail request MUST be treated as failed when the API returns an
    # error status — an error JSON body must never masquerade as a loaded dossier.
    assert "const response = await auth.fetch(API_ENDPOINTS.ANALYTICS.RECOMMENDATION_DOSSIER(id));" in js
    assert "if (!response.ok) {" in js
    assert "The evidence dossier request failed (HTTP" in js
    # While the dossier loads, the modal context shows a visible loading state.
    assert "Loading evidence context..." in js
    assert 'class="review-modal-context-loading"' in js
    assert ".review-modal-context-loading" in RECOMMENDATIONS_CSS
    # On failure the modal context shows a visible error message.
    assert "Evidence context failed to load." in js
    assert 'role="alert"' in js
    assert ".review-modal-context-error" in RECOMMENDATIONS_CSS
    # The error is surfaced in the dossier pane too, with the decision-blocking guard.
    assert "The evidence dossier could not be loaded" in js
    assert "Never approve or reject a recommendation without its evidence dossier." in js


def test_evidence_checkbox_and_confirm_stay_disabled_until_dossier_loaded():
    js = RECOMMENDATIONS_JS
    # A loaded dossier is scoped to the currently selected recommendation.
    assert "function dossierLoadedForSelected()" in js
    assert "dossierData && !dossierLoading && !dossierLoadError && dossierForId === selectedId" in js
    # The checkbox is enabled only when the evidence payload has loaded for the selected id.
    assert "evidenceReviewedCheckbox.disabled = !ready;" in js
    assert "if (!ready) evidenceReviewedCheckbox.checked = false;" in js
    # Confirm is disabled until the dossier has loaded for the selected recommendation.
    assert "function syncReviewContextGate()" in js
    assert "if (!dossierLoadedForSelected()) {" in js
    assert "modalConfirm.disabled = true;" in js
    # The modal opens disabled and re-syncs when the dossier finishes loading.
    assert "evidenceReviewedCheckbox.disabled = true;" in js
    assert "modalConfirm.disabled = true;" in js
    assert "syncReviewContextGate();" in js
    assert "if (!dossierLoadedForSelected() && selectedId) {" in js


def test_submit_checks_response_ok_and_surfaces_server_errors():
    js = RECOMMENDATIONS_JS
    assert "if (!response.ok) {" in js
    assert "renderReviewErrors(extractServerFieldErrors(body && body.detail));" in js
    # The failure path must not silently report success or refresh a false state.
    assert "server rejected the review" in js
    assert "return;" in js
    # The modal must only close after a successful review response: the error
    # block cannot call the success status text or close the modal.
    ok_block_start = js.index("const response = await auth.fetch(endpoint")
    ok_block_end = js.index("const result = await response.json();")
    ok_block = js[ok_block_start:ok_block_end]
    assert "body = await response.json();" in ok_block
    assert "modal.classList.remove('open')" not in ok_block
    assert "Recommendation ${currentAction}d as" not in ok_block


def test_success_path_reads_response_and_refreshes_authoritative_state():
    js = RECOMMENDATIONS_JS
    # The review response is parsed and its new_status reported, proving the
    # submission returned a usable response body.
    assert "const result = await response.json();" in js
    assert "const newStatus = (result && result.new_status) || `${currentAction}d`;" in js
    assert "modal.classList.remove('open');" in js
    assert "await loadRecommendations();" in js
    assert "if (selectedId) await loadDossier(selectedId);" in js


def test_field_level_validation_is_exposed_in_the_modal():
    js = RECOMMENDATIONS_JS
    html = RECOMMENDATIONS_HTML
    # Client-side field validation.
    assert "function validateReviewForm()" in js
    assert "Reason is required to record this review." in js
    assert "Modified title is required." in js
    assert "Modified description is required." in js
    assert "Priority must be high, medium, or low." in js
    # Server 422 detail (loc/msg pairs) is mapped back to fields.
    assert "function extractServerFieldErrors(detail)" in js
    assert "Array.isArray(d.loc)" in js
    assert "loc[loc.length - 1]" in js
    # Field-level error display surfaces in the dialog DOM.
    assert 'id="reviewModalErrors"' in html
    assert 'id="reviewModalFooterError"' in html
    assert 'aria-live="assertive"' in html
    # Invalid fields are visually flagged for correction.
    assert "classList.toggle(FIELD_INPUT_CLASS, Boolean(invalid))" in js
    assert ".field-invalid" in RECOMMENDATIONS_CSS
    assert ".review-error-item" in RECOMMENDATIONS_CSS


def test_confirm_button_reports_failed_validation_and_never_silently_succeeds():
    js = RECOMMENDATIONS_JS
    # The Confirm button is clearly marked as having failed, disabled during the
    # round-trip, and re-enabled afterwards.
    assert "MODAL_CONFIRM_FAILED_CLASS = 'echo-error';" in js
    assert "modalConfirm.classList.add(MODAL_CONFIRM_FAILED_CLASS);" in js
    assert "modalConfirm.classList.remove(MODAL_CONFIRM_FAILED_CLASS);" in js
    assert "modalConfirm.disabled = true;" in js
    assert "modalConfirm.textContent = 'Submitting...';" in js
    assert "modalConfirm.disabled = false;" in js
    assert ".btn.echo-error" in RECOMMENDATIONS_CSS
    # A validation failure blocks submission entirely (modal stays open).
    assert "if (errors.length) {" in js
    assert "renderReviewErrors(errors);" in js
    assert "return;" in js


def test_review_modal_keeps_audit_trail_visible_and_no_silent_failure():
    js = RECOMMENDATIONS_JS
    # On success the queue and the dossier are reloaded so the recorded decision,
    # status history and reviewer identity remain visible (audit trail preserved).
    assert "await loadRecommendations();" in js
    assert "if (selectedId) await loadDossier(selectedId);" in js
    # The success status names the authoritative new status rather than guessing.
    assert "as ${newStatus}" in js
    # No submission path treats a non-2xx response as success: the ok-check must
    # be evaluated before the success status is ever reached.
    ok_check_idx = js.index("if (!response.ok) {")
    success_status_idx = js.index("Recommendation ${currentAction}d as ${newStatus}.")
    assert ok_check_idx < success_status_idx
    assert success_status_idx < js.index("} finally {")


def test_modal_context_is_never_blank_and_is_bound_to_the_selected_recommendation():
    """Regression guard for the urgent modal defect: the review modal's evidence
    context region must always render exactly one defined state (loading / error /
    bound table / explicit unavailable), never an empty box, and must never show a
    dossier belonging to a different recommendation."""
    js = RECOMMENDATIONS_JS
    # 1. Default argument binds the no-argument calls to the current module dossier,
    #    so loadDossier()/openReviewModal() can never render a blank/stale context.
    assert "function renderModalContext(dossier = dossierData)" in js
    # 2. The element reference is re-resolved so a stale/missing binding cannot blank it.
    assert "reviewModalContext = $('reviewModalContext')" in js
    # 3. Stale/wrong id guard: only the dossier bound to the selected id is shown.
    assert "dossierForId !== selectedId" in js
    # 4. The three defined states are all present.
    assert "Loading evidence context..." in js
    assert "<strong>Evidence context failed to load.</strong>" in js
    assert "Evidence context is unavailable. Reload the recommendation before reviewing." in js
    # 5. A render-time exception falls back to the visible error state, not a blank box.
    assert "The evidence context could not be rendered." in js
    assert "catch (err) {" in js


def test_modal_context_covers_selection_load_click_error_and_loading_paths():
    """Card selection -> dossier load -> action click -> context table; plus the
    HTTP-error and loading states; and Confirm stays disabled until the matching
    dossier is loaded and the acknowledgement + reason are present."""
    js = RECOMMENDATIONS_JS
    # Selection issues the dossier request; loadDossier sets a line-visible loading
    # state for the context at the start and a defined state at the end.
    assert "loadDossier(selectedId);" in js
    assert "dossierContent.innerHTML = '<div class=\"dossier-empty\"><span class=\"spinner\"></span> Loading evidence dossier..." in js
    assert "Loading evidence context..." in js
    # HTTP error path: non-2xx is treated as failure and surfaced, never as success.
    assert "if (!response.ok) {" in js
    assert "The evidence dossier request failed (HTTP" in js
    assert "The evidence dossier payload did not contain a recommendation." in js
    # The action click renders the context (bound) before the modal is shown.
    assert "renderModalContext(dossierData);" in js
    assert "modal.classList.add('open');" in js
    # Gating: Confirm requires the matching loaded dossier AND acknowledgement AND reason.
    assert "function dossierLoadedForSelected()" in js
    assert "dossierData && !dossierLoading && !dossierLoadError && dossierForId === selectedId" in js
    assert "modalConfirm.disabled = !(reason && evidenceReviewed && modifyValid);" in js
    assert "evidenceReviewedCheckbox.disabled = !ready;" in js
