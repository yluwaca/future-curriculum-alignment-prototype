import { auth, requireAuth } from './auth.js';
import { CONFIG, API_ENDPOINTS } from './config.js';

function $(id) { return document.getElementById(id); }

function fmt(val, fallback) {
  if (val === null || val === undefined) return fallback || '-';
  if (typeof val === 'number') return val.toLocaleString();
  return String(val);
}

function pct(v) {
  if (v == null || isNaN(v)) return null;
  return (Number(v) * 100).toFixed(1) + '%';
}

function thresholdBar(pctVal, label) {
  const color = pctVal >= 80 ? '#16a34a' : pctVal >= 50 ? '#ca8a04' : '#dc2626';
  return `<div style="margin-bottom:10px;">
    <div style="display:flex;justify-content:space-between;font-size:12px;">
      <span>${label}</span><span>${pctVal.toFixed(0)}%</span>
    </div>
    <div class="threshold-bar"><div class="threshold-fill" style="width:${pctVal}%;background:${color};"></div></div>
  </div>`;
}

async function loadMetrics() {
  if (!auth.isAuthenticated()) {
    $('quickStats').innerHTML = '<p style="font-size:13px;color:var(--muted);"><a href="index.html" style="color:var(--accent);">Log in</a> to view live system metrics.</p>';
    return;
  }

  // Fetch from multiple endpoints in parallel
  let summary = {};
  let modelReady = {};
  try {
    const [sumRes, modRes] = await Promise.allSettled([
      auth.fetch(API_ENDPOINTS.ANALYTICS.SUMMARY),
      auth.fetch(API_ENDPOINTS.PREDICTIVE.MODEL_READINESS),
    ]);
    if (sumRes.status === 'fulfilled' && sumRes.value.ok) summary = await sumRes.value.json();
    if (modRes.status === 'fulfilled' && modRes.value.ok) modelReady = await modRes.value.json();
  } catch {}

  const counts = modelReady.counts || {};
  const baseline = modelReady.baseline_metrics || {};

  // Map actual field names from API responses
  const recsCount = fmt(summary.recommendations ?? counts.reviewed_recommendations ?? null, '0');
  const alignmentCount = fmt(summary.alignment_scores ?? counts.alignment_scores ?? null, '0');
  const forecastsCount = fmt(summary.forecasts ?? counts.forecasts ?? null, '0');
  const skillsCount = fmt(counts.skill_mappings ?? null, '0');
  const evidenceCount = fmt(summary.skill_demand_evidence ?? counts.skill_demand_evidence ?? null, '0');
  const signalsCount = fmt(summary.labour_market_signals ?? counts.labour_market_signals ?? null, '0');
  const docsCount = fmt(counts.curriculum_documents ?? null, '0');

  const avgAlignConf = baseline.average_alignment_confidence;
  const avgForecastConf = baseline.average_forecast_confidence;

  $('metricsGrid').innerHTML = `
    <div class="metric-tile"><div class="value">${skillsCount}</div><div class="label">Skill Mappings</div></div>
    <div class="metric-tile"><div class="value">${recsCount}</div><div class="label">Recommendations</div></div>
    <div class="metric-tile"><div class="value">${alignmentCount}</div><div class="label">Alignment Scores</div></div>
    <div class="metric-tile"><div class="value">${forecastsCount}</div><div class="label">Forecasts</div></div>
    <div class="metric-tile"><div class="value">${evidenceCount}</div><div class="label">Demand Evidence</div></div>
    <div class="metric-tile"><div class="value">${docsCount}</div><div class="label">Curriculum Documents</div></div>
  `;

  $('quickStats').innerHTML = `
    <p style="font-size:13px;"><span class="status-dot online"></span> System Online</p>
    <p style="font-size:13px;color:var(--muted);margin-top:6px;">Skills: ${skillsCount} &middot; Recommendations: ${recsCount} &middot; Documents: ${docsCount}</p>
    <p style="font-size:13px;color:var(--muted);">Avg alignment confidence: ${avgAlignConf ? pct(avgAlignConf) : 'N/A'}</p>
  `;

  // Threshold compliance (from gates)
  if (modelReady.gates && modelReady.gates.length) {
    $('thresholdSection').style.display = 'block';
    const ready = modelReady.ready_gates || 0;
    const blocked = modelReady.blocked_gates || 0;
    const total = ready + blocked;
    const pctReady = total > 0 ? (ready / total) * 100 : 0;
    let html = `${thresholdBar(pctReady, 'Pipeline Readiness (' + ready + '/' + total + ' gates passed)')}`;
    html += '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:8px;margin-top:8px;">';
    for (const gate of modelReady.gates) {
      const dot = gate.status === 'ready' ? 'online' : 'offline';
      html += `<div style="font-size:12px;background:var(--surface);border:1px solid var(--line);border-radius:6px;padding:8px 10px;">
        <span class="status-dot ${dot}"></span><strong>${gate.key}</strong>
        <p style="color:var(--muted);margin-top:2px;">${gate.message}</p>
      </div>`;
    }
    html += '</div>';
    $('thresholdContent').innerHTML = html;
  }
}

async function loadReadiness() {
  if (!auth.isAuthenticated()) return;
  try {
    const res = await auth.fetch(API_ENDPOINTS.INGESTION.READINESS);
    if (!res.ok) return;
    const data = await res.json();
    $('readinessSection').style.display = 'block';

    // Source categories
    const cats = data.category_counts || {};
    let html = '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:10px;margin-bottom:14px;">';
    for (const [key, val] of Object.entries(cats)) {
      html += `<div class="metric-tile" style="padding:12px;"><div class="value" style="font-size:20px;">${val}</div><div class="label">${key}</div></div>`;
    }
    html += '</div>';

    // Phase status
    html += `<p style="font-size:13px;color:var(--muted);margin-bottom:8px;"><strong>Phase:</strong> ${data.phase || 'N/A'}</p>`;

    // Latest jobs summary
    const jobs = data.latest_jobs || [];
    if (jobs.length) {
      html += '<table><thead><tr><th>Type</th><th>Status</th><th>Records</th><th>Date</th></tr></thead><tbody>';
      for (const j of jobs.slice(0, 6)) {
        const dot = j.status === 'completed' ? 'online' : j.status === 'failed' ? 'offline' : 'warning';
        html += `<tr><td style="font-weight:600;">${j.job_type}</td>
          <td><span class="status-dot ${dot}"></span>${j.status}</td>
          <td>${j.records_seen || 0}</td>
          <td>${j.created_at ? new Date(j.created_at).toLocaleDateString() : '-'}</td></tr>`;
      }
      html += '</tbody></table>';
    }
    $('readinessContent').innerHTML = html;
  } catch {}
}

async function loadOperations() {
  if (!auth.isAuthenticated()) return;

  // Backup info
  try {
    const res = await auth.fetch(API_ENDPOINTS.OPERATIONS.BACKUPS);
    if (res.ok) {
      const data = await res.json();
      const manifestCount = data.manifest_count ?? data.manifestCount ?? 0;
      const snapshots = data.snapshot_counts || {};
      const totalRecords = fmt(snapshots.raw_ingestion_records ?? null, '0');
      const audits = fmt(snapshots.audit_events ?? null, '0');
      const quality = data.quality_score != null ? (data.quality_score * 100).toFixed(0) + '%' : 'N/A';
      $('backupInfo').innerHTML = `
        <p style="font-size:13px;"><span class="status-dot online"></span> ${manifestCount} backup manifest${manifestCount !== 1 ? 's' : ''}</p>
        <p style="font-size:13px;color:var(--muted);margin-top:4px;">${totalRecords} records &middot; ${audits} audit events</p>
        <p style="font-size:13px;color:var(--muted);">Quality: ${quality} &middot; Mode: ${data.backup_mode || 'N/A'}</p>
      `;
    }
  } catch {
    $('backupInfo').innerHTML = '<p style="font-size:13px;color:var(--muted);">Backup data unavailable.</p>';
  }

  // Model readiness (already loaded above, just display status)
  try {
    const res = await auth.fetch(API_ENDPOINTS.PREDICTIVE.MODEL_READINESS);
    if (res.ok) {
      const data = await res.json();
      const gates = data.gates || [];
      const readyGates = data.ready_gates || 0;
      const totalGates = readyGates + (data.blocked_gates || 0);
      const maturity = data.model_maturity || 'unknown';
      let maturityLabel = maturity.replace(/_/g, ' ');
      const dot = readyGates === totalGates && totalGates > 0 ? 'online' : 'warning';
      $('modelReadinessInfo').innerHTML = `
        <p style="font-size:13px;"><span class="status-dot ${dot}"></span> ${readyGates}/${totalGates} gates ready (${maturityLabel})</p>
        <p style="font-size:13px;color:var(--muted);margin-top:4px;">Alignment: ${data.current_alignment_model || 'N/A'}</p>
        <p style="font-size:13px;color:var(--muted);">Forecast: ${data.current_forecast_model || 'N/A'}</p>
      `;
    }
  } catch {
    $('modelReadinessInfo').innerHTML = '<p style="font-size:13px;color:var(--muted);">Model readiness data unavailable.</p>';
  }
}

loadMetrics();
loadReadiness();
loadOperations();