import { postJson, getJson } from './dashboard-state.js?v=20260912d';
import { escapeHtml } from './dashboard-utils.js?v=20260825b';
import { API_ENDPOINTS } from './config.js?v=20260908';

const sourceInput = document.getElementById('adzunaPipelineSources');
const statusEl = document.getElementById('adzunaPipelineStatus');
const runSummaryEl = document.getElementById('adzunaPipelineRunSummary');
const signalsSummaryEl = document.getElementById('adzunaPipelineSignalsSummary');
const reviewLink = document.getElementById('adzunaPipelineReviewLink');

const SOURCE_TOKENS = { adzuna: 'ADZUNA_TRIAL_NOT_EMPIRICAL' };

function sourceNames(labels) {
  return (Array.isArray(labels) ? labels : [])
    .map((label) => (label === 'ADZUNA_TRIAL_NOT_EMPIRICAL' ? 'Adzuna' : label))
    .filter((label) => String(label).trim().length > 0);
}

function sources() {
  const value = sourceInput ? sourceInput.value.trim() : '';
  const parts = value ? value.split(',').map((item) => item.trim()).filter(Boolean) : [];
  const tokens = parts.length ? parts : ['adzuna'];
  return tokens.map((part) => SOURCE_TOKENS[part] || part);
}

function numberOrDash(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toLocaleString() : '-';
}

function refreshOutlookPanel() {
  const target = document.getElementById('adzunaTrialOutlookPanel');
  if (!target) return;
  const trialToken = SOURCE_TOKENS.adzuna;
  const sourceLabelFor = (label) => (label === trialToken ? 'Adzuna' : label);
  getJson(`${API_ENDPOINTS.LABOUR_MARKET.SKILL_PIPELINE_TRIAL_SIGNALS}`, { signals: [] })
    .then((data) => {
      const signals = Array.isArray(data.signals) ? data.signals : [];
      if (!signals.length) {
        target.className = 'empty';
        target.textContent = 'No labour demand signals yet. Run the Labour-market Skill Pipeline, review mappings in Skills Alignment, then generate labour demand signals.';
        return;
      }
      const count = Number(data.total_signal_count || signals.length);
      target.className = '';
      target.innerHTML = `
        <p class="muted" style="margin-bottom:8px"><strong>${count}</strong> labour demand signals generated from approved mappings on imported job-posting evidence.</p>
        <div class="table-wrap">
          <table>
            <thead><tr><th>Skill name</th><th>Demand value</th><th>Period</th><th>Source</th><th>Evidence count</th><th>Unit</th></tr></thead>
            <tbody>
              ${signals.map((item) => `<tr>
                <td><strong>${escapeHtml(item.skill_name || '-')}</strong></td>
                <td>${numberOrDash(item.normalised_value ?? item.demand_value ?? 0)}</td>
                <td>${escapeHtml(item.period || '-')}</td>
                <td><small>${escapeHtml(Object.keys(item.source_counts || {}).map(sourceLabelFor).join(', ') || '-')}</small></td>
                <td>${numberOrDash(item.evidence_count || 0)}</td>
                <td><small>${escapeHtml(item.unit || '-')}${item.normalised_from_legacy_unit ? ` <span class="muted" title="Display unit normalised from legacy source unit '${escapeHtml(item.raw_unit || '')}'; source/licence provenance retained in the evidence dossier">(normalised)</span>` : ''}</small></td>
              </tr>`).join('')}
            </tbody>
          </table>
        </div>`;
    })
    .catch(() => { /* keep the existing panel content on failure */ });
}

function stageCounts(summary, stage) {
  const block = (summary || {})[stage] || {};
  return block;
}

function actorLabel(run) {
  const actor = run?.triggered_by || run?.summary?.actor_id;
  if (!actor) return 'unknown actor';
  return String(actor).slice(0, 40);
}

function renderRun(run) {
  if (!run) return;
  const summary = run.summary || {};
  const cleaned = stageCounts(summary, 'cleaned');
  const mappings = stageCounts(summary, 'mappings');
  const signals = stageCounts(summary, 'signals');
  const evidence = stageCounts(summary, 'evidence');
  const ended = run.completed_at || run.created_at;
  const sourceLabel = sourceNames(summary.sources).join(', ') || 'all sources';

  runSummaryEl.className = '';
  runSummaryEl.innerHTML = `
    <div class="metrics">
      <div class="metric"><span>Pipeline run</span><strong>${escapeHtml(run.status || 'Unknown')}</strong><small>Job-posting skill extraction</small></div>
      <div class="metric"><span>Postings processed</span><strong>${numberOrDash(cleaned.postings_seen)}</strong><small>source: ${escapeHtml(sourceLabel)}</small></div>
      <div class="metric"><span>Mappings created</span><strong>${numberOrDash(mappings.mappings_created)}</strong><small>${numberOrDash(mappings.mappings_skipped)} skipped</small></div>
      <div class="metric"><span>Signals created</span><strong>${numberOrDash(signals.signals_created)}</strong><small>${numberOrDash(signals.signals_updated)} updated</small></div>
      <div class="metric"><span>Demand evidence created</span><strong>${numberOrDash(evidence.evidence_created)}</strong><small>${numberOrDash(evidence.evidence_skipped)} skipped</small></div>
      <div class="metric"><span>Actor</span><strong>${escapeHtml(actorLabel(run))}</strong><small>${ended ? new Date(ended).toLocaleString() : '-'}</small></div>
    </div>
    <p style="margin-top:8px;font-size:12px;color:#526985">
      ${run.error_summary ? `<strong style="color:#b31515">Error:</strong> ${escapeHtml(run.error_summary)}` : ''}
    </p>`;
}

function renderSignals(result) {
  if (!result) return;
  const jobRefs = (result.ingestion_job_ids || []);
  const sourceLabel = sourceNames(result.sources).join(', ') || 'all';
  signalsSummaryEl.className = '';
  signalsSummaryEl.innerHTML = `
    <div style="border-top:1px solid #dbe3ef;margin-top:12px;padding-top:8px">
      <strong>Labour demand signals</strong>
      <div class="metrics">
        <div class="metric"><span>Mappings considered</span><strong>${numberOrDash(result.mappings_considered)}</strong><small>job-posting skill mappings</small></div>
        <div class="metric"><span>Approved used</span><strong>${numberOrDash(result.mappings_approved_used)}</strong><small>approved-only promotion gate</small></div>
        <div class="metric"><span>Signals created</span><strong>${numberOrDash(result.signals_created)}</strong><small>${numberOrDash(result.signals_updated)} updated</small></div>
        <div class="metric"><span>Demand evidence created</span><strong>${numberOrDash(result.evidence_created)}</strong><small>${numberOrDash(result.evidence_skipped)} skipped</small></div>
      </div>
      <p style="margin-top:6px;font-size:12px;color:#526985">
        Promotion gate: <strong>${escapeHtml(result.promotion_gate || 'approved_labour_mappings_only')}</strong>.
        Sources: <strong>${escapeHtml(sourceLabel)}</strong>.
        Ingestion jobs referenced: ${jobRefs.map((job) => `<code>${job}</code>`).slice(0, 6).join(' ') || 'none'}${jobRefs.length > 6 ? ` (+${jobRefs.length - 6} more)` : ''}.
      </p>
    </div>`;
}

async function updateReviewLink() {
  try {
    const data = await getJson(`${API_ENDPOINTS.SKILLS.GOVERNANCE_WORKBENCH}?limit=1`, { mapping_status_summary: {} });
    const summary = data.mapping_status_summary || {};
    const mappingCount = [summary.approved, summary.candidate, summary.needs_review, summary.rejected]
      .map((value) => Number(value || 0))
      .reduce((sum, value) => sum + value, 0);
    reviewLink.disabled = mappingCount <= 0;
  } catch (error) {
    reviewLink.disabled = false;
  }
}

async function runPipeline(button) {
  button.disabled = true;
  statusEl.textContent = 'Running the labour-market skill pipeline on imported job-posting evidence…';
  runSummaryEl.className = 'empty';
  runSummaryEl.textContent = 'Pipeline running …';
  try {
    const result = await postJson(API_ENDPOINTS.LABOUR_MARKET.SKILL_PIPELINE, {
      limit: 50000,
      offset: 0,
      sources: sources(),
    });
    const cleaned = result.cleaned || {};
    const mappings = result.mappings || {};
    statusEl.textContent = `Pipeline completed (run ${result.run_id}). Postings processed: ${numberOrDash(cleaned.postings_seen)}; mappings created: ${numberOrDash(mappings.mappings_created)}. Review candidate mappings in Skills Alignment, then generate labour demand signals from approved mappings.`;
    await refreshStatus();
  } catch (error) {
    statusEl.textContent = `Pipeline failed: ${error.message}`;
    runSummaryEl.className = 'empty';
    runSummaryEl.textContent = 'Pipeline run failed. Review the message above and retry.';
  } finally {
    button.disabled = false;
  }
}

async function generateSignals(button) {
  button.disabled = true;
  statusEl.textContent = 'Generating labour demand signals and demand evidence from approved mappings…';
  try {
    const result = await postJson(API_ENDPOINTS.LABOUR_MARKET.SKILL_PIPELINE_SIGNALS, {
      limit: 10000,
      sources: sources(),
    });
    renderSignals(result);
    statusEl.textContent = `Signal generation completed (run ${result.run_id}). Approved mappings used: ${numberOrDash(result.mappings_approved_used)}; signals created: ${numberOrDash(result.signals_created)}; demand evidence created: ${numberOrDash(result.evidence_created)}.`;
    await updateReviewLink();
    window.dispatchEvent(new CustomEvent('labour-signals-updated', { detail: { run_id: result.run_id } }));
    refreshOutlookPanel();
  } catch (error) {
    statusEl.textContent = `Signal generation failed: ${error.message}`;
  } finally {
    button.disabled = false;
  }
}

async function refreshStatus() {
  statusEl.textContent = 'Refreshing pipeline run status…';
  try {
    const runs = await getJson(`${API_ENDPOINTS.LABOUR_MARKET.SKILL_PIPELINE_RUNS}?limit=5`, []);
    if (!Array.isArray(runs) || !runs.length) {
      runSummaryEl.className = 'empty';
      runSummaryEl.textContent = 'No labour-market skill pipeline run recorded yet.';
      statusEl.textContent = 'No pipeline run recorded yet.';
      return;
    }
    const latest = runs.find((run) => run.summary?.cleaned || run.summary?.mappings);
    if (!latest) {
      runSummaryEl.className = 'empty';
      runSummaryEl.textContent = 'No skill extraction run in recent history. Run the pipeline to process imported postings.';
      statusEl.textContent = 'Signal generation is recorded; run skill extraction to see posting counts.';
      await updateReviewLink();
      return;
    }
    renderRun(latest);
    statusEl.textContent = `Latest run: ${latest.status} (${new Date(latest.completed_at || latest.created_at).toLocaleString()}).`;
    await updateReviewLink();
  } catch (error) {
    statusEl.textContent = `Refresh failed: ${error.message}`;
  }
}

document.getElementById('adzunaPipelineRunBtn').addEventListener('click', (event) => runPipeline(event.currentTarget));
document.getElementById('adzunaPipelineSignalsBtn').addEventListener('click', (event) => generateSignals(event.currentTarget));
document.getElementById('adzunaPipelineRefreshBtn').addEventListener('click', refreshStatus);
reviewLink.addEventListener('click', () => {
  if (typeof window.openDataOperationsSection === 'function') {
    window.openDataOperationsSection('labour', 'review');
    return;
  }
  window.location.href = 'data-operations.html?area=labour&step=review';
});

refreshStatus();
updateReviewLink();
refreshOutlookPanel();
