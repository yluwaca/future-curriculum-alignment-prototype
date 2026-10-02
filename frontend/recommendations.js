import { auth, requireAuth } from './auth.js';
import { CONFIG, API_ENDPOINTS } from './config.js';
import { renderSidebar, setNavigationUser } from './shared-nav.js?v=20261001a';

requireAuth();

// ---- State ----
let recommendations = [];
let selectedId = null;
let dossierData = null;
let dossierForId = null;
let dossierLoading = false;
let dossierLoadError = null;
let currentPage = 1;
const PAGE_SIZE = 20;
let governanceReadiness = null;
let canGovernRecommendations = false;

// ---- DOM refs ----
const $ = (id) => document.getElementById(id);
const recList = $('recList');
const recCount = $('recCount');
const dossierContent = $('dossierContent');
const statusBar = $('statusBar');
const statusFilter = $('statusFilter');
const priorityFilter = $('priorityFilter');
const searchFilter = $('searchFilter');
const recPagination = $('recPagination');

// ---- Helpers ----
function setStatus(msg, type) {
  statusBar.textContent = msg;
  statusBar.className = 'status-bar ' + (type || 'info');
  if (msg) statusBar.style.display = 'block';
  else statusBar.style.display = 'none';
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function statusBadge(status, tone) {
  const tones = { good: 'good', warn: 'warn', bad: 'bad', info: 'info' };
  const t = tone || (status === 'approved' ? 'good' : status === 'rejected' ? 'bad' : 'warn');
  return `<span class="badge ${tones[t] || 'info'}">${escapeHtml(status)}</span>`;
}

function priorityBadge(priority) {
  const map = { high: 'bad', medium: 'warn', low: 'good' };
  return `<span class="badge ${map[priority] || 'info'}">${escapeHtml(priority)}</span>`;
}

function percent(v) {
  if (v == null || isNaN(v)) return '-';
  return (Number(v) * 100).toFixed(1) + '%';
}

function formatNumber(v) {
  if (v == null || isNaN(v)) return '0';
  return Number(v).toLocaleString();
}

function emptyStateHtml({ title, reason, action, limitation }) {
  return `<div class="empty-state empty-state-detail">
    <strong>${escapeHtml(title)}</strong>
    ${reason ? `<span><b>Why:</b> ${escapeHtml(reason)}</span>` : ''}
    ${action ? `<span><b>Next step:</b> ${escapeHtml(action)}</span>` : ''}
    ${limitation ? `<span class="empty-limitation"><b>Do not infer:</b> ${escapeHtml(limitation)}</span>` : ''}
  </div>`;
}

// ---- Load data ----
async function loadRecommendations() {
  setStatus('Loading recommendations...', 'info');
  try {
    recommendations = await auth.fetch(
      API_ENDPOINTS.ANALYTICS.RECOMMENDATIONS + '?limit=500'
    ).then(r => r.json());
    const requestedId = new URLSearchParams(window.location.search).get('recommendation_id');
    if (requestedId && recommendations.some(item => item.recommendation_id === requestedId)) {
      selectedId = requestedId;
    }
    applyFilters();
    if (selectedId) {
      await loadDossier(selectedId);
      const requestedAction = new URLSearchParams(window.location.search).get('action');
      if (['approve', 'reject', 'modify'].includes(requestedAction)) {
        openReviewModal(requestedAction);
      }
    }
    setStatus('', '');
  } catch (err) {
    console.error(err);
    setStatus('Failed to load recommendations.', 'error');
  }
}

async function loadGovernanceReadiness() {
  const summary = $('governanceSummary');
  const checks = $('governanceChecks');
  const button = $('committeePackBtn');
  try {
    const response = await auth.fetch(API_ENDPOINTS.ANALYTICS.RECOMMENDATION_GOVERNANCE_READINESS);
    if (!response.ok) throw new Error(`Readiness returned ${response.status}`);
    governanceReadiness = await response.json();
    const counts = governanceReadiness.counts || {};
    summary.textContent = governanceReadiness.status === 'ready'
      ? `${counts.committee_pack_eligible || 0} reviewed recommendation(s) are ready for a committee pack.`
      : 'Committee reporting is safely blocked until every evidence and human-review gate below is satisfied.';
    checks.innerHTML = (governanceReadiness.checks || []).map(item =>
      `<span class="governance-check ${item.status}" title="${escapeHtml(item.message)}">${escapeHtml(item.key.replaceAll('_', ' '))}: ${escapeHtml(item.status)}</span>`
    ).join('');
    button.disabled = governanceReadiness.status !== 'ready';
  } catch (error) {
    summary.textContent = 'Governance readiness could not be checked.';
    checks.innerHTML = '';
    button.disabled = true;
  }
}

// ---- Filter & Paginate ----
function applyFilters() {
  const status = statusFilter.value;
  const priority = priorityFilter.value;
  const query = searchFilter.value.toLowerCase();

  let filtered = recommendations;
  if (status) filtered = filtered.filter(r => r.status === status);
  if (priority) filtered = filtered.filter(r => r.priority === priority);
  if (query) filtered = filtered.filter(r =>
    (r.title || '').toLowerCase().includes(query)
  );

  const totalPages = Math.ceil(filtered.length / PAGE_SIZE) || 1;
  if (currentPage > totalPages) currentPage = totalPages;
  const start = (currentPage - 1) * PAGE_SIZE;
  const page = filtered.slice(start, start + PAGE_SIZE);

  recCount.textContent = `${filtered.length} recommendation${filtered.length !== 1 ? 's' : ''}`;
  renderList(page);
  renderPagination(totalPages);
}

function renderList(items) {
  if (!items.length) {
    const hasFilter = Boolean(statusFilter.value || priorityFilter.value || searchFilter.value);
    recList.innerHTML = hasFilter
      ? emptyStateHtml({ title: 'No recommendations match these filters', action: 'Clear or change the filters to inspect other review states.' })
      : emptyStateHtml(canGovernRecommendations
          ? {
              title: 'No reviewable recommendations yet',
              reason: 'Validated curriculum evidence and approved mappings have not yet produced an eligible recommendation set.',
              action: 'Complete the blocked evidence gates in Data Operations, regenerate validated outputs, then return here for human review.',
              limitation: 'An empty list does not mean the curriculum has no gaps or needs no change.',
            }
          : { title: 'No published recommendations are available yet.' });
    return;
  }
  recList.innerHTML = items.map(r => `
    <a class="rec-item ${r.recommendation_id === selectedId ? 'selected' : ''}"
         href="recommendations.html?recommendation_id=${encodeURIComponent(r.recommendation_id)}"
         data-id="${escapeHtml(r.recommendation_id)}">
      <h4>${escapeHtml(r.title || 'Untitled')}</h4>
      <p>${escapeHtml((r.description || '').substring(0, 120))}</p>
      <div class="meta">
        ${statusBadge(r.status, r.status)}
        ${priorityBadge(r.priority)}
        <span>Score: ${(r.priority_score != null ? Number(r.priority_score).toFixed(3) : '-')}</span>
        <span>Conf: ${percent(r.confidence_score)}</span>
      </div>
    </a>
  `).join('');

  // Use one delegated handler so recommendation selection remains reliable
  // after filtering, pagination, refreshes, or DOM replacement.
  recList.onclick = (event) => {
    const el = event.target.closest('.rec-item');
    if (!el || !recList.contains(el)) return;
    event.preventDefault();
    selectedId = el.dataset.id;
    recList.querySelectorAll('.rec-item').forEach(e => e.classList.remove('selected'));
    el.classList.add('selected');
    loadDossier(selectedId);
  };
}

function renderPagination(totalPages) {
  if (totalPages <= 1) { recPagination.innerHTML = ''; return; }
  const buttons = [];
  for (let i = 1; i <= totalPages; i++) {
    buttons.push(`<button class="btn sm ${i === currentPage ? 'primary' : ''}" data-page="${i}">${i}</button>`);
  }
  recPagination.innerHTML = buttons.join(' ');
  recPagination.querySelectorAll('[data-page]').forEach(btn => {
    btn.addEventListener('click', () => {
      currentPage = Number(btn.dataset.page);
      applyFilters();
    });
  });
}

// ---- Dossier ----
function dossierLoadedForSelected() {
  return Boolean(dossierData && !dossierLoading && !dossierLoadError && dossierForId === selectedId);
}

async function loadDossier(id) {
  if (id !== selectedId) return;
  dossierLoading = true;
  dossierLoadError = null;
  setStatus('Loading dossier...', 'info');
  dossierContent.innerHTML = '<div class="dossier-empty"><span class="spinner"></span> Loading evidence dossier...</div>';
  renderModalContext();
  syncReviewContextGate();
  try {
    const response = await auth.fetch(API_ENDPOINTS.ANALYTICS.RECOMMENDATION_DOSSIER(id));
    if (!response.ok) {
      throw new Error(`The evidence dossier request failed (HTTP ${response.status}).`);
    }
    const data = await response.json();
    if (!data || !data.recommendation) {
      throw new Error('The evidence dossier payload did not contain a recommendation.');
    }
    if (id !== selectedId) return;
    dossierLoading = false;
    dossierData = data;
    dossierForId = id;
    renderDossier();
    setStatus('', '');
  } catch (err) {
    if (id !== selectedId) return;
    console.error(err);
    dossierLoading = false;
    dossierData = null;
    dossierForId = null;
    dossierLoadError = err.message || 'The evidence dossier could not be loaded.';
    setStatus('Failed to load dossier.', 'error');
    $('dossierContent').innerHTML = emptyStateHtml({
      title: 'The evidence dossier could not be loaded',
      reason: `${dossierLoadError} The recommendation may be unavailable or the API request failed.`,
      action: 'Refresh once. If the problem remains, check System Operations before making any decision.',
      limitation: 'Never approve or reject a recommendation without its evidence dossier.',
    });
  }
  renderModalContext();
  syncReviewContextGate();
}

function renderDossier() {
  if (!dossierData) return;
  const rec = dossierData.recommendation || {};
  const skill = dossierData.skill || {};
  const summary = dossierData.evidence_summary || {};
  const alignment = dossierData.alignment || {};
  const forecast = dossierData.forecast || {};
  const topEvidence = (dossierData.demand_evidence || []).slice(0, 8);
  const explanations = dossierData.explanations || [];
  const reviews = dossierData.reviews || [];
  const feedback = dossierData.feedback || [];
  const statusHistory = dossierData.status_history || [];
  const meta = rec.recommendation_metadata || {};
  // Zero-evidence gate (S5): non-actionable items can be rejected but never approved.
  const actionable = dossierData.actionable !== undefined && dossierData.actionable !== null
    ? dossierData.actionable
    : (meta.actionable !== undefined ? meta.actionable : true);
  const nonActionableReason = dossierData.non_actionable_reason || meta.non_actionable_reason || null;

  dossierContent.innerHTML = `
    <div class="dossier-section">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:8px;">
        <div>
          <h3>${escapeHtml(rec.title || 'Recommendation')}</h3>
          <p style="color:var(--text-muted);margin-top:4px;">${escapeHtml(rec.description || '')}</p>
        </div>
        <div style="display:flex;gap:6px;flex-wrap:wrap;">
          ${canGovernRecommendations ? `
          <a class="btn success sm" data-action="approve" href="recommendations.html?recommendation_id=${encodeURIComponent(rec.recommendation_id)}&action=approve" ${actionable ? '' : 'aria-disabled="true" title="Non-actionable: zero labour-market evidence; approval is blocked until evidence generation re-supports this recommendation."'}>Approve${actionable ? '' : ' (blocked)'}</a>
          <a class="btn danger sm" data-action="reject" href="recommendations.html?recommendation_id=${encodeURIComponent(rec.recommendation_id)}&action=reject">Reject</a>
          <a class="btn sm" data-action="modify" href="recommendations.html?recommendation_id=${encodeURIComponent(rec.recommendation_id)}&action=modify">Modify</a>` : ''}
          ${alignment.alignment_id ? `<button class="btn sm" data-action="lineage">Lineage</button>` : ''}
        </div>
      </div>
      ${actionable ? '' : `<div class="decision-limitation" style="border-left-color:#dc2626;background:#fef2f2;"><strong>Non-actionable (zero evidence):</strong> ${escapeHtml(nonActionableReason || 'No labour-market evidence is attached; approval is blocked and the item is retained, never deleted.')}</div>`}
      <div class="decision-limitation"><strong>Human review required:</strong> confidence and priority scores rank evidence for attention; they are not probabilities that a curriculum change is correct. Verify sources, institutional context and feasibility before recording a review.</div>
    </div>

    <div class="dossier-section">
      <div class="metrics-row">
        <div class="metric-card">
          <div class="value">${statusBadge(rec.status, rec.status)}</div>
          <div class="label">Status</div>
        </div>
        <div class="metric-card">
          <div class="value">${priorityBadge(rec.priority)}</div>
          <div class="label">Priority</div>
        </div>
        <div class="metric-card">
          <div class="value">${rec.priority_score != null ? Number(rec.priority_score).toFixed(3) : '-'}</div>
          <div class="label">Priority Score</div>
        </div>
        <div class="metric-card">
          <div class="value">${percent(rec.confidence_score)}</div>
          <div class="label">Confidence</div>
        </div>
        <div class="metric-card">
          <div class="value">${formatNumber(summary.skill_demand_evidence_count || 0)}</div>
          <div class="label">Evidence Items</div>
        </div>
        <div class="metric-card">
          <div class="value">${formatNumber(summary.review_count || 0)}</div>
          <div class="label">Reviews</div>
        </div>
      </div>
    </div>

    <div class="dossier-section">
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem;">
        <div>
          <h3>Skill & Alignment</h3>
          <table>
            <tr><td style="font-weight:600;">Skill</td><td>${escapeHtml(skill.name || 'Unmapped')}</td></tr>
            <tr><td style="font-weight:600;">Category</td><td>${escapeHtml(skill.category || '-')}</td></tr>
            <tr><td style="font-weight:600;">Type</td><td>${escapeHtml(rec.recommendation_type || '-')}</td></tr>
            <tr><td style="font-weight:600;">Gap Type</td><td>${escapeHtml(meta.gap_type || '-')}</td></tr>
            <tr><td style="font-weight:600;">Alignment Score</td><td>${percent(alignment.alignment_score)}</td></tr>
            <tr><td style="font-weight:600;">Gap Score</td><td>${percent(alignment.gap_score)}</td></tr>
          </table>
        </div>
        <div>
          <h3>Forecast</h3>
          <table>
            <tr><td style="font-weight:600;">Trend</td><td>${escapeHtml(forecast.trend_direction || '-')}</td></tr>
            <tr><td style="font-weight:600;">Baseline</td><td>${forecast.baseline_value != null ? Number(forecast.baseline_value).toFixed(2) : '-'}</td></tr>
            <tr><td style="font-weight:600;">Forecast</td><td>${forecast.forecast_value != null ? Number(forecast.forecast_value).toFixed(2) : '-'}</td></tr>
            <tr><td style="font-weight:600;">Forecast Conf.</td><td>${percent(forecast.confidence_score)}</td></tr>
            <tr><td style="font-weight:600;">Method</td><td>${escapeHtml(forecast.method || '-')}</td></tr>
            <tr><td style="font-weight:600;">Horizon</td><td>${forecast.horizon_periods != null ? forecast.horizon_periods + ' periods' : '-'}</td></tr>
          </table>
        </div>
      </div>
    </div>

    <div class="dossier-section">
      <h3>Demand Evidence — ${actionable ? 'resolvable' : 'context only'} (${topEvidence.length})</h3>
      ${actionable ? '' : `<div class="decision-limitation" style="border-left-color:#dc2626;background:#fef2f2;margin-bottom:8px;">
        <strong>Context only — these rows do NOT satisfy the approval gate.</strong>
        The ${topEvidence.length} row(s) below are contextual/reference demand rows shown for reviewer awareness.
        The approval gate metric is <strong>resolvable / approved labour-market evidence</strong>:
        <code>skill_demand_evidence_count = ${formatNumber(meta.skill_demand_evidence_count ?? 0)}</code>,
        <code>labour_evidence_count = ${formatNumber(meta.labour_evidence_count ?? 0)}</code>.
        Zero resolvable evidence &rArr; approval is blocked (the item is retained, never deleted).
      </div>`}
      ${topEvidence.length ? `
      <div class="table-wrap">
        <table>
          <thead><tr><th>Context</th><th>Score</th><th>Confidence</th><th>Source</th></tr></thead>
          <tbody>${topEvidence.map(e => `
            <tr>
              <td>${escapeHtml(e.matched_context || e.context || '-')}${actionable ? '' : ' <span class="badge warn">context</span>'}</td>
              <td>${percent(e.demand_score)}</td>
              <td>${percent(e.confidence_score)}</td>
              <td>${escapeHtml(e.source_type || e.data_source || '-')}</td>
            </tr>
          `).join('')}</tbody>
        </table>
      </div>` : emptyStateHtml({title:'No demand evidence is attached', reason:'No traceable skill-demand records were found for this recommendation.', action:'Return it for revision; do not approve it until supporting evidence is available.', limitation:'A score without its evidence is insufficient for a decision.'})}
    </div>

    <div class="dossier-section">
      <h3>Explanations (${explanations.length})</h3>
      ${explanations.length ? `
      <div class="table-wrap">
        <table>
          <thead><tr><th>Type</th><th>Explanation</th></tr></thead>
          <tbody>${explanations.map(e => `
            <tr><td><span class="badge info">${escapeHtml(e.explanation_type)}</span></td><td>${escapeHtml(e.explanation_text)}</td></tr>
          `).join('')}</tbody>
        </table>
      </div>` : emptyStateHtml({title:'No explanation is attached', reason:'The system has not provided a reviewable rationale for this recommendation.', action:'Return it for revision before making a decision.', limitation:'Priority and confidence values do not substitute for an explanation.'})}
    </div>

    <div class="dossier-section">
      <h3>Status History (${statusHistory.length})</h3>
      ${statusHistory.length ? `
      <div class="table-wrap">
        <table>
          <thead><tr><th>Date</th><th>Transition</th><th>From</th><th>To</th><th>Changed by</th><th>Reason</th></tr></thead>
          <tbody>${statusHistory.map(h => `
            <tr>
              <td>${h.created_at ? new Date(h.created_at).toLocaleString() : '-'}</td>
              <td><small>${escapeHtml(h.transition_type || '-')}</small></td>
              <td>${h.previous_status ? statusBadge(h.previous_status) : '-'}</td>
              <td>${statusBadge(h.new_status)}</td>
              <td>${escapeHtml(h.changed_by || '-')}</td>
              <td>${escapeHtml(h.change_reason || '-')}</td>
            </tr>
          `).join('')}</tbody>
        </table>
      </div>` : '<p style="color:var(--text-muted);">No status history.</p>'}
    </div>

    <div class="dossier-section">
      <h3>Decision audit detail (${reviews.length})</h3>
      <p style="font-size:12px;color:var(--text-muted);margin:0 0 8px;">Every decision records the exact persisted values below. <code>-</code> means the value was not recorded for that decision (older rows created before audit fields were captured) — it is never inferred.</p>
      ${reviews.length ? reviews.map(r => {
        const rm = r.review_metadata || {};
        const ctx = rm.evidence_context || {};
        const f = ctx.forecast || {};
        const links = Array.isArray(ctx.evidence_links) ? ctx.evidence_links : [];
        const roles = rm.reviewer_role || (Array.isArray(rm.reviewer_roles) ? rm.reviewer_roles.join(', ') : '');
        const fingerprint = rm.evidence_context_fingerprint || '';
        const modelIdentity = f.method || ctx.forecast_method || '';
        const datasetIdentity = ctx.dataset_fingerprint || ctx.reviewed_label_snapshot_version || '';
        return `<details class="review-audit-detail" style="margin-bottom:8px;">
          <summary>${statusBadge(r.decision)} &middot; ${escapeHtml(r.previous_status || '-')} &rarr; ${escapeHtml(r.new_status || '-')} &middot; ${escapeHtml(r.reviewer_id || '-')} &middot; ${r.created_at ? new Date(r.created_at).toLocaleString() : '-'}</summary>
          <table style="margin-top:6px;">
            <tr><td style="font-weight:600;">Review ID</td><td><code>${escapeHtml(r.review_id || '-')}</code></td></tr>
            <tr><td style="font-weight:600;">Reviewer</td><td>${escapeHtml(r.reviewer_id || '-')}</td></tr>
            <tr><td style="font-weight:600;">Role</td><td>${escapeHtml(roles || '-')}</td></tr>
            <tr><td style="font-weight:600;">Decision</td><td>${statusBadge(r.decision)} (${escapeHtml(r.previous_status || '-')} &rarr; ${escapeHtml(r.new_status || '-')})</td></tr>
            <tr><td style="font-weight:600;">Timestamp</td><td>${r.created_at ? new Date(r.created_at).toLocaleString() : '-'}</td></tr>
            <tr><td style="font-weight:600;">Reason</td><td>${escapeHtml(r.decision_reason || '-')}</td></tr>
            <tr><td style="font-weight:600;">Evidence reviewed</td><td>${rm.evidence_reviewed === true ? 'yes (acknowledged)' : rm.evidence_reviewed === false ? 'no' : '-'}</td></tr>
            <tr><td style="font-weight:600;">Evidence-context fingerprint</td><td>${fingerprint ? `<code style="font-size:11px">${escapeHtml(fingerprint)}</code>` : '-'}</td></tr>
            <tr><td style="font-weight:600;">Model identity</td><td>${escapeHtml(modelIdentity || '-')}</td></tr>
            <tr><td style="font-weight:600;">Dataset identity</td><td>${escapeHtml(datasetIdentity || '-')}</td></tr>
            ${r.modified_title ? `<tr><td style="font-weight:600;">Modified title</td><td>${escapeHtml(r.modified_title)}</td></tr>` : ''}
            ${r.modified_priority ? `<tr><td style="font-weight:600;">Modified priority</td><td>${escapeHtml(r.modified_priority)}</td></tr>` : ''}
            <tr><td style="font-weight:600;">Source / provenance</td><td>${escapeHtml(Array.isArray(ctx.sources) ? ctx.sources.join(', ') : '-')} ${Array.isArray(ctx.provenance) && ctx.provenance.length ? '/ ' + escapeHtml(ctx.provenance.join(', ')) : ''}</td></tr>
            <tr><td style="font-weight:600;">Evidence links</td><td>${links.length ? links.map(l => `${escapeHtml(l.context || '-')} <small>(${escapeHtml(l.source || '-')})</small>`).join('<br>') : '-'}</td></tr>
          </table>
        </details>`;
      }).join('') : '<p style="color:var(--text-muted);">No decisions recorded yet.</p>'}
    </div>

    <div class="dossier-section">
      <h3>Feedback (${feedback.length})</h3>
      ${feedback.length ? `
      <div class="table-wrap">
        <table>
          <thead><tr><th>Date</th><th>Reviewer</th><th>Type</th><th>Comment</th><th>Rating</th></tr></thead>
          <tbody>${feedback.map(f => `
            <tr>
              <td>${f.created_at ? new Date(f.created_at).toLocaleString() : '-'}</td>
              <td>${escapeHtml(f.reviewer_id || '-')}</td>
              <td>${escapeHtml(f.feedback_type || '-')}</td>
              <td>${escapeHtml(f.comment || '-')}</td>
              <td>${f.rating != null ? f.rating + '/5' : '-'}</td>
            </tr>
          `).join('')}</tbody>
        </table>
      </div>` : '<p style="color:var(--text-muted);">No feedback recorded.</p>'}
    </div>

    <div class="dossier-section">
      <h3>Metadata</h3>
      <div style="font-size:12px;color:var(--text-muted);">
        <p><strong>ID:</strong> ${escapeHtml(rec.recommendation_id || '-')}</p>
        <p><strong>Type:</strong> ${escapeHtml(rec.recommendation_type || '-')}</p>
        <p><strong>Created:</strong> ${rec.created_at ? new Date(rec.created_at).toLocaleString() : '-'}</p>
        <p><strong>Updated:</strong> ${rec.updated_at ? new Date(rec.updated_at).toLocaleString() : '-'}</p>
        <p><strong>Model Version:</strong> ${escapeHtml(rec.model_version || meta.model_version || '-')}</p>
        ${meta.module_label ? `<p><strong>Module:</strong> ${escapeHtml(meta.module_label)}</p>` : ''}
        ${meta.programme ? `<p><strong>Programme:</strong> ${escapeHtml(meta.programme)}</p>` : ''}
        ${meta.faculty ? `<p><strong>Faculty:</strong> ${escapeHtml(meta.faculty)}</p>` : ''}
      </div>
    </div>
  `;

  // Wire action buttons
  dossierContent.querySelectorAll('[data-action]').forEach(btn => {
    btn.addEventListener('click', (event) => {
      const action = btn.dataset.action;
      if (btn.getAttribute('aria-disabled') === 'true') {
        event.preventDefault();
        return;
      }
      event.preventDefault();
      if (action === 'lineage') {
        loadLineage(rec.recommendation_id);
      } else {
        openReviewModal(action);
      }
    });
  });
}

// ---- Review Modal ----
const modal = $('reviewModal');
const modalTitle = $('modalTitle');
const modalReason = $('modalReason');
const modalFeedback = $('modalFeedback');
const modifyFields = $('modifyFields');
const modalTitleInput = $('modalTitleInput');
const modalDescription = $('modalDescription');
const modalPriority = $('modalPriority');
const modalConfirm = $('modalConfirm');
const reviewModalErrors = $('reviewModalErrors');
const reviewModalFooterError = $('reviewModalFooterError');
let reviewModalContext = $('reviewModalContext');
const evidenceReviewedCheckbox = $('evidenceReviewedCheckbox');
const reviewEvidenceCheckboxWrap = $('reviewEvidenceCheckboxWrap');

const FIELD_INPUT_CLASS = 'field-invalid';
const MODAL_CONFIRM_FAILED_CLASS = 'echo-error';
const MODAL_FIELDS = {
  reason: 'Reason',
  feedback_comment: 'Feedback Comment',
  modified_title: 'Modified Title',
  modified_description: 'Modified Description',
  modified_priority: 'Modified Priority',
  evidenceReviewedCheckbox: 'Evidence reviewed',
};
const FIELD_NAME_TO_INPUT = {
  reason: 'modalReason',
  feedback_comment: 'modalFeedback',
  modified_title: 'modalTitleInput',
  modified_description: 'modalDescription',
  modified_priority: 'modalPriority',
  evidenceReviewedCheckbox: 'reviewEvidenceCheckboxWrap',
};
const ALLOWED_PRIORITIES = ['high', 'medium', 'low'];

let currentAction = null;

function buildEvidenceContext(dossier) {
  if (!dossier) return null;
  const rec = dossier.recommendation || {};
  const meta = rec.recommendation_metadata || {};
  const skill = dossier.skill || {};
  const alignment = dossier.alignment || {};
  const forecast = dossier.forecast || {};
  const summary = dossier.evidence_summary || {};
  const evidence = dossier.demand_evidence || [];
  const forecastPayload = forecast.forecast_payload || {};
  const forecastProvenance = forecastPayload.provenance || {};
  const postingSources = Object.keys((forecastProvenance.query_source || {}).job_posting_sources || {});
  const sources = [...new Set([
    ...evidence.map(e => e.source_type || e.data_source || ''),
    ...postingSources,
  ].filter(Boolean))].slice(0, 10);
  const provenance = [...new Set(evidence.map(e => {
    const em = e.evidence_metadata || {};
    return em.acquisition_mode || em.provenance || em.source_name || '';
  }).filter(Boolean))].slice(0, 10);
  const evidenceLinks = evidence.slice(0, 10).map(e => ({
    context: e.matched_context || e.context || '-',
    source: e.source_type || e.data_source || '-',
    demand_score: e.demand_score,
    confidence_score: e.confidence_score,
  }));
  return {
    recommendation_id: rec.recommendation_id,
    title: rec.title,
    skill_name: skill.name,
    skill_category: skill.category,
    gap_type: meta.gap_type,
    demand_score: summary.skill_demand_score,
    labour_evidence_count: summary.skill_demand_evidence_count ?? evidence.length,
    forecast: {
      trend_direction: forecast.trend_direction,
      baseline_value: forecast.baseline_value,
      forecast_value: forecast.forecast_value,
      confidence_score: forecast.confidence_score,
      method: forecast.method,
      horizon_periods: forecast.horizon_periods,
    },
    curriculum_coverage: {
      alignment_score: alignment.alignment_score,
      gap_score: alignment.gap_score,
      module: meta.module_label,
      programme: meta.programme,
      faculty: meta.faculty,
    },
    confidence: rec.confidence_score,
    priority_score: rec.priority_score,
    dataset_fingerprint: meta.dataset_snapshot_fingerprint || forecastProvenance.dataset_snapshot_fingerprint || forecastPayload.dataset_fingerprint || null,
    reviewed_label_snapshot_version: meta.reviewed_label_snapshot_version || forecastPayload.reviewed_label_snapshot_version || null,
    sources,
    provenance,
    canonical_signal_keys: summary.canonical_signal_keys,
    evidence_links: evidenceLinks,
  };
}

function renderModalContext(dossier = dossierData) {
  // Never leave the context area blank: re-resolve the element and render exactly
  // one of loading / error / bound evidence table / explicit unavailable.
  if (!reviewModalContext) reviewModalContext = $('reviewModalContext');
  if (!reviewModalContext) return;
  if (dossierLoading) {
    reviewModalContext.innerHTML = '<div class="review-modal-context-loading"><span class="spinner"></span> Loading evidence context...</div>';
    return;
  }
  if (dossierLoadError) {
    reviewModalContext.innerHTML = `<div class="review-modal-context-error" role="alert"><strong>Evidence context failed to load.</strong><div>${escapeHtml(dossierLoadError)}</div></div>`;
    return;
  }
  // The context is bound to the currently selected recommendation. A dossier for a
  // different id must never be shown, and an absent/stale dossier shows an explicit,
  // actionable unavailable state rather than an empty box.
  if (!dossier || dossierForId !== selectedId) {
    reviewModalContext.innerHTML = '<em>Evidence context is unavailable. Reload the recommendation before reviewing.</em>';
    return;
  }
  const rec = dossier.recommendation || {};
  const meta = rec.recommendation_metadata || {};
  const skill = dossier.skill || {};
  const alignment = dossier.alignment || {};
  const forecast = dossier.forecast || {};
  const summary = dossier.evidence_summary || {};
  const evidence = dossier.demand_evidence || [];
  const forecastPayload = forecast.forecast_payload || {};
  const forecastProvenance = forecastPayload.provenance || {};
  const postingSources = Object.keys((forecastProvenance.query_source || {}).job_posting_sources || {});
  const sources = [...new Set([
    ...evidence.map(e => e.source_type || e.data_source || ''),
    ...postingSources,
  ].filter(Boolean))].slice(0, 8);
  const provenance = [...new Set(evidence.map(e => {
    const em = e.evidence_metadata || {};
    return em.acquisition_mode || em.provenance || em.source_name || '';
  }).filter(Boolean))].slice(0, 8);
  const evidenceLinks = evidence.slice(0, 8);
  const remaining = Math.max(0, (summary.skill_demand_evidence_count ?? evidence.length) - evidenceLinks.length);

  try {
  reviewModalContext.innerHTML = `
    <h4>Evidence context for this decision</h4>
    <table>
      <tr><td>Recommendation ID</td><td>${escapeHtml(rec.recommendation_id || dossier.recommendation_id || '-')}</td></tr>
      <tr><td>Skill</td><td>${escapeHtml(skill.name || 'Unmapped')}</td></tr>
      <tr><td>Category</td><td>${escapeHtml(skill.category || '-')}</td></tr>
      <tr><td>Gap type</td><td>${escapeHtml(meta.gap_type || '-')}</td></tr>
      <tr><td>Demand score</td><td>${percent(summary.skill_demand_score)}</td></tr>
      <tr><td>Labour evidence count</td><td>${formatNumber(summary.skill_demand_evidence_count ?? evidence.length)}</td></tr>
      <tr><td>Forecast</td><td>${escapeHtml(forecast.trend_direction || '-')} (${forecast.forecast_value != null ? Number(forecast.forecast_value).toFixed(2) : '-'})</td></tr>
      <tr><td>Forecast confidence</td><td>${percent(forecast.confidence_score)}</td></tr>
      <tr><td>Curriculum coverage</td><td>${percent(alignment.alignment_score)} alignment / ${percent(alignment.gap_score)} gap</td></tr>
      <tr><td>Module</td><td>${escapeHtml(meta.module_label || '-')}</td></tr>
      <tr><td>Programme</td><td>${escapeHtml(meta.programme || '-')}</td></tr>
      <tr><td>Faculty</td><td>${escapeHtml(meta.faculty || '-')}</td></tr>
      <tr><td>Confidence</td><td>${percent(rec.confidence_score)}</td></tr>
      <tr><td>Source</td><td>${sources.length ? sources.map(s => escapeHtml(s)).join(', ') : '-'}</td></tr>
      <tr><td>Provenance</td><td>${provenance.length ? provenance.map(p => escapeHtml(p)).join(', ') : '-'}</td></tr>
      <tr><td>Dataset fingerprint</td><td>${escapeHtml(meta.dataset_snapshot_fingerprint || forecastProvenance.dataset_snapshot_fingerprint || forecastPayload.dataset_fingerprint || '-')}</td></tr>
      <tr><td>Signal keys</td><td>${(summary.canonical_signal_keys || []).length ? (summary.canonical_signal_keys || []).slice(0, 6).map(k => escapeHtml(k)).join(', ') : '-'}</td></tr>
    </table>
    ${evidenceLinks.length ? `
      <h4 style="margin-top:8px;">Labour evidence</h4>
      <ul>
        ${evidenceLinks.map(e => `<li>${escapeHtml(e.matched_context || e.context || '-')} — <em>${escapeHtml(e.source_type || e.data_source || '-')}</em> ${percent(e.demand_score)}</li>`).join('')}
        ${remaining ? `<li><em>+${remaining} more</em></li>` : ''}
      </ul>
    ` : ''}
  `;
  } catch (err) {
    reviewModalContext.innerHTML = `<div class="review-modal-context-error" role="alert"><strong>Evidence context failed to load.</strong><div>${escapeHtml(err && err.message ? err.message : 'The evidence context could not be rendered.')}</div></div>`;
  }
}

function setFieldInvalid(inputId, invalid) {
  const input = $(inputId);
  if (!input) return;
  input.classList.toggle(FIELD_INPUT_CLASS, Boolean(invalid));
}

function clearFieldErrors() {
  Object.values(FIELD_NAME_TO_INPUT).forEach(id => setFieldInvalid(id, false));
  if (reviewModalErrors) {
    reviewModalErrors.innerHTML = '';
    reviewModalErrors.classList.remove('error');
  }
  if (reviewModalFooterError) reviewModalFooterError.textContent = '';
  modalConfirm.classList.remove(MODAL_CONFIRM_FAILED_CLASS);
}

function renderReviewErrors(errors) {
  clearFieldErrors();
  if (!errors || !errors.length) return;
  const lines = errors.map(e => {
    const fieldKey = FIELD_NAME_TO_INPUT[e.field] ? e.field : 'form';
    setFieldInvalid(FIELD_NAME_TO_INPUT[fieldKey], true);
    const label = MODAL_FIELDS[e.field] || e.fieldLabel || 'Request';
    return `  <div class="review-error-item"><strong>${escapeHtml(label)}:</strong> ${escapeHtml(e.message)}</div>\n`;
  }).join('');
  if (reviewModalErrors) {
    reviewModalErrors.innerHTML = lines;
    reviewModalErrors.classList.add('error');
  }
  if (reviewModalFooterError) {
    reviewModalFooterError.textContent = 'Validation failed — the review was not submitted. Fix the highlighted fields and confirm again.';
  }
  modalConfirm.classList.add(MODAL_CONFIRM_FAILED_CLASS);
}

function extractServerFieldErrors(detail) {
  if (Array.isArray(detail)) {
    return detail.map(d => {
      const loc = Array.isArray(d.loc) ? d.loc : [];
      const field = loc.length > 1 ? String(loc[loc.length - 1]) : String(d.loc || 'form');
      return { field, fieldLabel: MODAL_FIELDS[field] || 'Request', message: d.msg || String(d) };
    });
  }
  if (typeof detail === 'string') return [{ field: 'form', fieldLabel: 'Request', message: detail }];
  if (detail && typeof detail === 'object' && detail.message) {
    return [{ field: 'form', fieldLabel: 'Request', message: String(detail.message) }];
  }
  return [{ field: 'form', fieldLabel: 'Request', message: 'The review request was rejected by the server.' }];
}

function validateModalToggle() {
  if (!dossierLoadedForSelected()) {
    modalConfirm.disabled = true;
    return;
  }
  const reason = (modalReason.value || '').trim();
  const evidenceReviewed = evidenceReviewedCheckbox.checked;
  let modifyValid = true;
  if (currentAction === 'modify') {
    const title = (modalTitleInput.value || '').trim();
    const description = (modalDescription.value || '').trim();
    const priority = modalPriority.value;
    modifyValid = Boolean(title && description && ALLOWED_PRIORITIES.includes(priority));
  }
  modalConfirm.disabled = !(reason && evidenceReviewed && modifyValid);
}

function syncReviewContextGate() {
  if (!modal || !modal.classList.contains('open')) return;
  const ready = dossierLoadedForSelected();
  evidenceReviewedCheckbox.disabled = !ready;
  if (!ready) evidenceReviewedCheckbox.checked = false;
  validateModalToggle();
  renderModalContext(dossierData);
}

function validateReviewForm() {
  const errors = [];
  const reason = (modalReason.value || '').trim();
  if (!reason) errors.push({ field: 'reason', message: 'Reason is required to record this review.' });
  if (!evidenceReviewedCheckbox.checked) {
    errors.push({ field: 'evidenceReviewedCheckbox', message: 'You must confirm that you reviewed the evidence before submitting.' });
  }
  if (!dossierLoadedForSelected()) errors.push({ field: 'form', fieldLabel: 'Evidence context', message: 'Evidence context could not be loaded. Reload this recommendation before submitting.' });
  if (currentAction === 'modify') {
    const title = (modalTitleInput.value || '').trim();
    const description = (modalDescription.value || '').trim();
    const priority = modalPriority.value;
    if (!title) errors.push({ field: 'modified_title', message: 'Modified title is required.' });
    if (!description) errors.push({ field: 'modified_description', message: 'Modified description is required.' });
    if (!ALLOWED_PRIORITIES.includes(priority)) errors.push({ field: 'modified_priority', message: 'Priority must be high, medium, or low.' });
  }
  return { errors, reason };
}

function openReviewModal(action) {
  currentAction = action;
  const actionLabel = action.charAt(0).toUpperCase() + action.slice(1);
  modalTitle.textContent = `${actionLabel} Recommendation`;
  modalReason.value = '';
  modalFeedback.value = '';
  modifyFields.style.display = action === 'modify' ? 'block' : 'none';
  if (action === 'modify' && dossierData) {
    const rec = dossierData.recommendation || {};
    modalTitleInput.value = rec.title || '';
    modalDescription.value = rec.description || '';
    modalPriority.value = rec.priority || 'medium';
  }
  clearFieldErrors();
  modal.dataset.recommendationId = selectedId || '';
  renderModalContext(dossierData);
  evidenceReviewedCheckbox.checked = false;
  evidenceReviewedCheckbox.disabled = true;
  reviewEvidenceCheckboxWrap.style.display = '';
  modalConfirm.textContent = actionLabel;
  modalConfirm.className = 'btn ' + (action === 'reject' ? 'danger' : 'primary');
  modalConfirm.disabled = true;
  modal.classList.add('open');
  syncReviewContextGate();
  if (!dossierLoadedForSelected() && selectedId) {
    loadDossier(selectedId);
  }
}

function closeReviewModal() {
  modal.classList.remove('open');
  clearFieldErrors();
}

$('modalCancel').addEventListener('click', closeReviewModal);
modal.addEventListener('click', (e) => { if (e.target === modal) closeReviewModal(); });
if (modalReason) modalReason.addEventListener('input', validateModalToggle);
if (evidenceReviewedCheckbox) evidenceReviewedCheckbox.addEventListener('change', validateModalToggle);
if (modalTitleInput) modalTitleInput.addEventListener('input', validateModalToggle);
if (modalDescription) modalDescription.addEventListener('input', validateModalToggle);
if (modalPriority) modalPriority.addEventListener('change', validateModalToggle);

$('reviewForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  if (!currentAction || !selectedId) return;
  const actionLabel = currentAction.charAt(0).toUpperCase() + currentAction.slice(1);
  const { errors, reason } = validateReviewForm();
  if (errors.length) {
    renderReviewErrors(errors);
    setStatus(`Cannot ${currentAction}: fix the highlighted validation errors in the dialog.`, 'error');
    return;
  }

  const payload = {
    recommendation_id: selectedId,
    decision: currentAction,
    reason,
    feedback_comment: (modalFeedback.value || '').trim() || null,
    evidence_reviewed: !!evidenceReviewedCheckbox.checked,
    evidence_context: buildEvidenceContext(dossierData),
  };
  if (currentAction === 'modify') {
    payload.modified_title = (modalTitleInput.value || '').trim();
    payload.modified_description = (modalDescription.value || '').trim();
    payload.modified_priority = modalPriority.value;
  }

  let endpoint;
  if (currentAction === 'approve') endpoint = API_ENDPOINTS.ANALYTICS.RECOMMENDATION_APPROVE(selectedId);
  else if (currentAction === 'reject') endpoint = API_ENDPOINTS.ANALYTICS.RECOMMENDATION_REJECT(selectedId);
  else endpoint = API_ENDPOINTS.ANALYTICS.RECOMMENDATION_MODIFY(selectedId);

  clearFieldErrors();
  setStatus(`${actionLabel}ing recommendation...`, 'info');
  modalConfirm.disabled = true;
  modalConfirm.textContent = 'Submitting...';
  try {
    const response = await auth.fetch(endpoint, {
      method: 'POST',
      body: JSON.stringify(payload),
      headers: { 'Content-Type': 'application/json' },
    });
    if (!response.ok) {
      let body = null;
      try { body = await response.json(); } catch { /* non-JSON error body */ }
      renderReviewErrors(extractServerFieldErrors(body && body.detail));
      setStatus(`${actionLabel} failed — the server rejected the review; see the dialog errors.`, 'error');
      return;
    }
    const result = await response.json();
    modal.classList.remove('open');
    const newStatus = (result && result.new_status) || `${currentAction}d`;
    setStatus(`Recommendation ${currentAction}d as ${newStatus}.`, 'ok');
    await loadRecommendations();
    if (selectedId) await loadDossier(selectedId);
  } catch (err) {
    console.error(err);
    renderReviewErrors([{ field: 'form', fieldLabel: 'Request', message: err.message || 'The review request could not be submitted.' }]);
    setStatus(`Failed to ${currentAction} recommendation.`, 'error');
  } finally {
    modalConfirm.disabled = false;
    modalConfirm.textContent = actionLabel;
  }
});

// ---- Lineage ----
async function loadLineage(id) {
  setStatus('Loading lineage...', 'info');
  try {
    const lineage = await auth.fetch(API_ENDPOINTS.ANALYTICS.RECOMMENDATION_LINEAGE(id)).then(r => r.json());
    const summary = lineage.summary || {};
    const stages = Array.from(new Set((lineage.lineage_events || []).map(e => e.processing_stage).filter(Boolean))).slice(0, 10);
    const events = (lineage.lineage_events || []).slice(0, 20);
    const nodes = (lineage.lineage_nodes || []).slice(0, 30);

    // Append lineage section
    const section = document.createElement('div');
    section.className = 'dossier-section';
    section.innerHTML = `
      <h3>Data Lineage</h3>
      <div class="metrics-row" style="margin-bottom:8px;">
        <div class="metric-card"><div class="value">${summary.node_count || 0}</div><div class="label">Nodes</div></div>
        <div class="metric-card"><div class="value">${summary.edge_count || 0}</div><div class="label">Edges</div></div>
        <div class="metric-card"><div class="value">${summary.lineage_event_count || 0}</div><div class="label">Events</div></div>
        <div class="metric-card"><div class="value">${summary.demand_evidence_count || 0}</div><div class="label">Evidence Items</div></div>
      </div>
      ${stages.length ? `<p><strong>Processing Stages:</strong> ${stages.map(s => statusBadge(s, 'info')).join(' ')}</p>` : ''}
      ${events.length ? `
      <div class="table-wrap" style="margin-top:8px;">
        <table>
          <thead><tr><th>Time</th><th>Stage</th><th>Source</th><th>Description</th></tr></thead>
          <tbody>${events.map(e => `
            <tr>
              <td>${e.event_time ? new Date(e.event_time).toLocaleString() : '-'}</td>
              <td>${escapeHtml(e.processing_stage || '-')}</td>
              <td>${escapeHtml(e.source_system || '-')}</td>
              <td>${escapeHtml(e.transformation_description || '-')}</td>
            </tr>
          `).join('')}</tbody>
        </table>
      </div>` : '<p style="color:var(--text-muted);">No lineage events.</p>'}
      ${nodes.length ? `
      <p><strong>Nodes:</strong> ${nodes.map(n => `<span class="badge info">${escapeHtml(n.label || n.id)}</span>`).join(' ')}</p>
      ` : ''}
    `;
    dossierContent.appendChild(section);
    setStatus('Lineage loaded.', 'ok');
  } catch (err) {
    console.error(err);
    setStatus('Failed to load lineage.', 'error');
  }
}

// ---- Event handlers ----
statusFilter.addEventListener('change', () => { currentPage = 1; applyFilters(); });
priorityFilter.addEventListener('change', () => { currentPage = 1; applyFilters(); });
searchFilter.addEventListener('input', () => { currentPage = 1; applyFilters(); });

$('refreshBtn').addEventListener('click', async () => {
  await Promise.all([loadRecommendations(), loadGovernanceReadiness()]);
  if (selectedId) await loadDossier(selectedId);
});

$('committeePackBtn').addEventListener('click', async () => {
  const button = $('committeePackBtn');
  button.disabled = true;
  setStatus('Generating immutable committee evidence pack…', 'info');
  try {
    const response = await auth.fetch(API_ENDPOINTS.ANALYTICS.RECOMMENDATION_COMMITTEE_PACK, { method: 'POST' });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail?.message || result.detail || 'Pack generation failed');
    const detailResponse = await auth.fetch(`${API_ENDPOINTS.ANALYTICS.REPORTS}/${result.report_id}`);
    const detail = await detailResponse.json();
    if (!detailResponse.ok) throw new Error(detail.detail || 'Generated pack could not be retrieved');
    exportCommitteePackPdf(detail);
    setStatus(`Committee evidence pack generated and downloaded as PDF. Report ID: ${result.report_id}`, 'ok');
  } catch (error) {
    setStatus(`Committee pack was not generated: ${error.message}`, 'error');
  } finally {
    await loadGovernanceReadiness();
  }
});

function exportCommitteePackPdf(report) {
  if (!window.jspdf?.jsPDF) throw new Error('PDF library is unavailable');
  const { jsPDF } = window.jspdf;
  const doc = new jsPDF();
  const pageWidth = doc.internal.pageSize.getWidth();
  const payload = report.payload || {};
  let y = 18;
  const ensureSpace = (needed = 20) => {
    if (y + needed > 280) { doc.addPage(); y = 18; }
  };
  const writeWrapped = (text, size = 9, indent = 14) => {
    doc.setFontSize(size);
    const lines = doc.splitTextToSize(String(text || '-'), pageWidth - indent - 14);
    ensureSpace(lines.length * 5 + 4);
    doc.text(lines, indent, y);
    y += lines.length * 5 + 4;
  };
  doc.setFontSize(16);
  doc.text('FUTURE Curriculum Recommendation Evidence Pack', pageWidth / 2, y, { align: 'center' });
  y += 9;
  doc.setFontSize(9);
  doc.text(`Generated ${new Date(report.created_at || Date.now()).toLocaleString()}`, pageWidth / 2, y, { align: 'center' });
  y += 7;
  writeWrapped(`Report ID: ${report.report_id} | Evidence-pack SHA-256: ${report.payload_hash}`, 8);
  writeWrapped('Decision-support evidence only. Recommendations require human curriculum governance and do not apply curriculum changes automatically.', 9);
  (payload.recommendations || []).forEach((item, index) => {
    const rec = item.recommendation || {};
    const reviews = item.human_reviews || [];
    ensureSpace(45);
    doc.setFont('helvetica', 'bold');
    writeWrapped(`${index + 1}. ${rec.title || 'Recommendation'}`, 11);
    doc.setFont('helvetica', 'normal');
    writeWrapped(`Status: ${rec.status || '-'} | Priority: ${rec.priority || '-'} | Confidence: ${rec.confidence_score != null ? (Number(rec.confidence_score) * 100).toFixed(1) + '%' : '-'}`, 9);
    writeWrapped(rec.description || '-', 9);
    reviews.forEach((review) => {
      const meta = review.review_metadata || {};
      writeWrapped(`Decision: ${review.decision || '-'} (${review.previous_status || '-'} -> ${review.new_status || '-'}) | Reviewer: ${review.reviewer_id || '-'} | Role: ${meta.reviewer_role || '-'} | Date: ${review.created_at ? new Date(review.created_at).toLocaleString() : '-'}`, 8);
      writeWrapped(`Reason: ${review.decision_reason || '-'}`, 8);
      writeWrapped(`Evidence reviewed: ${meta.evidence_reviewed === true ? 'yes' : 'no'} | Evidence fingerprint: ${meta.evidence_context_fingerprint || '-'}`, 8);
    });
    (item.limitations || []).forEach(limit => writeWrapped(`Limitation: ${limit}`, 8));
  });
  const date = new Date().toISOString().slice(0, 10);
  doc.save(`FUTURE-committee-recommendation-pack-${date}.pdf`);
}

$('logoutBtn').addEventListener('click', async () => {
  try { await auth.fetch(API_ENDPOINTS.AUTH.LOGOUT, { method: 'POST' }); } catch {}
  auth.clearToken();
  window.location.href = 'index.html';
});

// ---- User display ----
try {
  const token = auth.getToken();
  if (token) {
    const payload = JSON.parse(atob(token.split('.')[1]));
    $('userDisplay').textContent = payload.sub || payload.username || '';
  }
} catch {}

// ---- Init ----
async function initialiseRecommendations() {
  try {
    const response = await auth.fetch(API_ENDPOINTS.AUTH.ME);
    if (response.ok) {
      const user = await response.json();
      setNavigationUser(user);
      renderSidebar('recommendations');
      const roles = (user.roles || []).map((role) => String(role).toLowerCase());
      canGovernRecommendations = Boolean(user.is_admin)
        || roles.includes('admin')
        || roles.includes('administrator')
        || roles.includes('analyst')
        || roles.includes('curriculum_approver')
        || roles.includes('curriculum approver');
    }
  } catch {
    canGovernRecommendations = false;
  }
  $('viewerReadOnlyNotice').hidden = canGovernRecommendations;
  $('committeePackBtn').classList.toggle('is-hidden', !canGovernRecommendations);
  await Promise.all([loadRecommendations(), loadGovernanceReadiness()]);
}

initialiseRecommendations();
