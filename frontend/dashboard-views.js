// dashboard-views.js - All view rendering functions
import { $, paginate, renderPagination, renderKeyValueRows, renderBars, renderEmpty, decisionEmptyState, formatNumber, percent, escapeHtml, statusBadge, statusTone, priorityTone, skillName, countBy, average, formatFileSize, hideSpinner } from './dashboard-utils.js?v=20260825b';
import { state, titles, setStatus, clearStatus, getJson, postJson, postForm, actions } from './dashboard-state.js?v=20260921-registry1';
import { API_ENDPOINTS } from './config.js?v=20260825b';

    function renderExecutive() {
      const isViewer = document.body.classList.contains('viewer-audience');
      const isDecisionAudience = isViewer || document.body.classList.contains('analyst-audience');
      const avgAlignment = average(state.alignmentScores.map((item) => Number(item.alignment_score || 0)));
      const metricDocs = $('metricDocuments');
      const curriculumProgrammes = state.curriculumHierarchy?.programmes || [];
      if (metricDocs) metricDocs.textContent = formatNumber((state.documents || []).length + curriculumProgrammes.length);
      $('metricSkills').textContent = isViewer && !state.skillsSummary.mappings ? '-' : formatNumber(state.skillsSummary.mappings || 0);
      $('metricAlignment').textContent = isViewer && !state.alignmentScores.length ? '-' : percent(avgAlignment);
      $('metricPending').textContent = formatNumber(state.recommendations.filter((item) => item.status === 'pending_review').length);

      const priorityCounts = countBy(state.recommendations, 'priority');
      $('recommendationCount').textContent = `${state.recommendations.length} total`;
      renderBars('recommendationPriorityBars', [
        ['High', priorityCounts.high || 0, 'bad'],
        ['Medium', priorityCounts.medium || 0, 'warn'],
        ['Low', priorityCounts.low || 0, 'good'],
      ]);
      if (isDecisionAudience && !state.recommendations.length) {
        $('recommendationPriorityBars').innerHTML = '<div class="empty">No published recommendations are available yet.</div>';
      }

      const recommendationRows = state.recommendationStatusFilter === 'all'
        ? state.recommendations
        : (state.recommendationGroups.length ? state.recommendationGroups : state.recommendations.filter((item) => item.status === 'pending_review'));
      renderRecommendationRows('latestRecommendations', recommendationRows);
    }

    function renderCurriculum() {
      const versions = state.documentDetails.flatMap((detail) => detail?.versions || []);
      const documentChunks = versions.reduce((sum, item) => sum + Number(item.chunk_count || 0), 0);
      const docs = state.documents || [];
      const programmes = state.curriculumHierarchy?.programmes || [];
      const modules = state.curriculumHierarchy?.modules || [];
      $('curriculumDocuments').textContent = formatNumber(docs.length + programmes.length);
      $('curriculumVersions').textContent = formatNumber(programmes.length || versions.length);
      $('curriculumChunks').textContent = formatNumber(modules.length || documentChunks);
      const quality = state.curriculumQuality || {};
      const qualityValue = quality.average_quality_score ?? quality.quality_score;
      const avgQuality = typeof qualityValue === 'number' ? percent(qualityValue) : (modules.length || docs.length ? 'normalised' : '-');
      $('curriculumAvgQuality').textContent = avgQuality;
      const curriculumDates = [...docs.map((item) => item.created_at), ...programmes.map((item) => item.created_at || item.updated_at)].filter(Boolean);
      const lastDate = curriculumDates.length ? curriculumDates.reduce((a, b) => new Date(a) > new Date(b) ? a : b) : null;
      $('curriculumLastIngestion').textContent = lastDate ? new Date(lastDate).toLocaleDateString() : '-';
      renderCurriculumQualityNotes();
      if (state.selectedCurriculumDoc !== null) {
        const detailPanel = $('curriculumDetailPanel');
        const listPanel = $('curriculumListPanel');
        if (detailPanel) detailPanel.style.display = 'block';
        if (listPanel) listPanel.style.display = 'none';
        renderCurriculumJobs();
        return;
      }
      const detailPanel = $('curriculumDetailPanel');
      const listPanel = $('curriculumListPanel');
      if (detailPanel) detailPanel.style.display = 'none';
      if (listPanel) listPanel.style.display = '';
      renderCurriculumRows('curriculumTable', [...docs, ...curriculumProgrammeRows()]);
      renderCurriculumJobs();
    }

    function renderSkills() {
      const summary = state.skillsSummary || {};
      const hasSummary = Object.keys(summary).length > 0;
      $('skillTotal').textContent = hasSummary ? formatNumber(summary.skills || 0) : '-';
      $('skillCurriculumMappings').textContent = hasSummary ? formatNumber(summary.curriculum_mappings || 0) : '-';
      $('skillLabourMappings').textContent = hasSummary ? formatNumber(summary.labour_market_mappings || 0) : '-';
      const latestGap = state.skillGapSummary?.total_gap_candidates ?? state.alignmentScores[0]?.missing_skill_count ?? null;
      $('skillGapCount').textContent = latestGap !== null ? formatNumber(latestGap) : '-';
      renderSkillGapRows('skillGapRows', state.skillGapSummary?.gaps || []);
      const gaps = state.skillGapSummary;
      $('skillGapCaption').textContent = gaps ? `${formatNumber(gaps.gaps_returned || 0)} shown from ${formatNumber(gaps.total_gap_candidates || 0)} findings` : 'No gap analysis run yet.';
    }

    function forecastSkillLabel(item) {
      const apiName = item?.skill_name || item?.canonical_skill_name || item?.esco_label;
      if (apiName) return String(apiName).trim();
      return skillName(item?.skill_id, state.skills);
    }

    function uniqueForecastsBySkill(rows = []) {
      const latestBySkill = new Map();
      rows.forEach((item) => {
        const label = forecastSkillLabel(item);
        const key = item.skill_id || item.skill_key || label.toLowerCase() || item.forecast_id;
        const existing = latestBySkill.get(key);
        if (!existing) {
          latestBySkill.set(key, item);
          return;
        }
        const existingTime = existing.created_at ? new Date(existing.created_at).getTime() : 0;
        const candidateTime = item.created_at ? new Date(item.created_at).getTime() : 0;
        if (candidateTime > existingTime) latestBySkill.set(key, item);
      });
      return Array.from(latestBySkill.values());
    }

    function renderForecasts() {
      const isViewer = document.body.classList.contains('viewer-audience');
      const uniqueForecasts = uniqueForecastsBySkill(state.forecasts);
      const forecasts = isViewer
        ? uniqueForecasts.filter((item) => {
            const name = forecastSkillLabel(item);
            return name && name.toLowerCase() !== 'unmapped skill';
          })
        : uniqueForecasts;
      const hasForecasts = forecasts.length > 0;
      if (hasForecasts) {
        const increasing = forecasts.filter((item) => item.trend_direction === 'increasing').length;
        const confidence = average(forecasts.map((item) => Number(item.confidence_score || 0)));
        $('forecastCount').textContent = formatNumber(forecasts.length);
        $('forecastIncreasing').textContent = formatNumber(increasing);
        $('forecastConfidence').textContent = percent(confidence);
      } else {
        $('forecastCount').textContent = '-';
        $('forecastIncreasing').textContent = '-';
        $('forecastConfidence').textContent = '-';
      }
      {
        const readiness = state.modelReadiness || {};
        $('modelMaturity').textContent = readiness.model_maturity || '-';
        $('modelMaturityCaption').textContent = `${readiness.ready_gates || 0} ready, ${readiness.blocked_gates || 0} blocked`;
        const xgbTs = state.xgboostLastTrained || readiness.xgboost_last_trained;
        const lstmTs = state.lstmLastTrained || readiness.lstm_last_trained;
        const xgbLastTrained = $('xgboostLastTrained');
        if (xgbLastTrained && xgbTs) xgbLastTrained.textContent = `Last trained: ${new Date(xgbTs).toLocaleString()}`;
        const lstmLastTrained = $('lstmLastTrained');
        if (lstmLastTrained && lstmTs) lstmLastTrained.textContent = `Last trained: ${new Date(lstmTs).toLocaleString()}`;
      }
      renderForecastQuality();
      renderModelReadiness();
      renderModelDatasetSnapshot();
      renderModelMetrics();
      renderForecastRows('forecastRows', forecasts);
      renderAdzunaTrialOutlook();
    }


    function renderForecastQuality() {
      const target = $('forecastQualityPanel');
      if (!target) return;
      hideSpinner('spinnerForecastQuality');
      const summary = state.forecastQuality;
      if (!summary) {
        target.className = 'empty';
        target.textContent = 'Load quality report to review forecast and recommendation quality.';
        return;
      }
      const forecast = summary.forecast_evaluation || {};
      const registry = summary.model_registry || {};
      const ranking = summary.recommendation_ranking || {};
      const explainability = summary.explainability || {};
      target.className = '';
      target.innerHTML = `
        <div class="metrics">
          <div class="metric"><span>Overall Quality Score</span><strong>${percent(summary.score || 0)}</strong><small>${escapeHtml(summary.status || 'unknown')}</small></div>
          <div class="metric"><span>Forecast Quality</span><strong>${percent(forecast.quality_score || 0)}</strong><small>${formatNumber(forecast.forecast_count || 0)} forecasts</small></div>
          <div class="metric"><span>Registry Quality</span><strong>${percent(registry.quality_score || 0)}</strong><small>${escapeHtml(registry.model_maturity || '-')}</small></div>
          <div class="metric"><span>Ranking Quality</span><strong>${percent(ranking.quality_score || 0)}</strong><small>${formatNumber(ranking.recommendation_count || 0)} recommendations</small></div>
          <div class="metric"><span>Explainability</span><strong>${percent(explainability.quality_score || 0)}</strong><small>${formatNumber(explainability.explanation_count || 0)} explanations</small></div>
        </div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>Area</th><th>Evidence</th><th>Issues</th></tr></thead>
            <tbody>
              <tr><td>Forecast evaluation</td><td>${formatNumber(forecast.evaluated_count || 0)} evaluated, avg confidence ${percent(forecast.average_confidence || 0)}</td><td>${escapeHtml((forecast.issues || []).join(' | ') || 'No issues returned')}</td></tr>
              <tr><td>Model registry</td><td>${formatNumber(registry.ready_gates || 0)} ready gates, ${formatNumber(registry.registry_report_count || 0)} registry reports</td><td>${escapeHtml((registry.issues || []).join(' | ') || 'No issues returned')}</td></tr>
              <tr><td>Recommendation ranking</td><td>${formatNumber(ranking.ranked_count || 0)} ranked, avg priority ${percent(ranking.average_priority_score || 0)}</td><td>${escapeHtml((ranking.issues || []).join(' | ') || 'No issues returned')}</td></tr>
              <tr><td>Explainability reports</td><td>${percent(explainability.explainability_share || 0)} recent recommendations explained</td><td>${escapeHtml((explainability.issues || []).join(' | ') || 'No issues returned')}</td></tr>
            </tbody>
          </table>
        </div>
      `;
    }

    function renderIngestionQuality() {
      if (!$('dataOperations') && !$('qualityConnectors')) return;
      const summaries = Object.values(state.qualitySummaries || {});
      const cleaned = summaries.reduce((sum, item) => (
        sum + Object.values(item.cleaned_records || {}).reduce((inner, value) => inner + Number(value || 0), 0)
      ), 0);
      const failed = summaries.reduce((sum, item) => sum + Number((item.checks || {}).failed || 0), 0);
      const scoreValues = summaries
        .filter((item) => item.average_quality_score !== null && item.average_quality_score !== undefined)
        .map((item) => Number(item.average_quality_score))
        .filter((item) => Number.isFinite(item));
      const ops = state.ingestionOperationsSummary || {};
      $('qualityConnectors').textContent = formatNumber(ops.connector_types ?? state.connectorDefinitions.length);
      $('qualityNormalisers').textContent = formatNumber(ops.normalisers ?? state.normaliserDefinitions.length);
      $('qualityEducationContext').textContent = formatNumber(
        ops.education_context ?? state.ingestionSources.filter((item) => item.source_category === 'higher_education_context').length
      );
      $('qualityContracts').textContent = formatNumber(ops.contracts ?? state.ingestionContracts.length);
      $('qualityCleaned').textContent = formatNumber(ops.cleaned_records ?? cleaned);
      $('qualityTrendFacts').textContent = formatNumber(ops.labour_trend_facts ?? state.labourTrendSummary.total_trends ?? 0);
      $('qualitySignals').textContent = formatNumber(ops.canonical_signals ?? state.labourTrendSummary.total_signals ?? 0);
      $('qualityFailureEvents').textContent = formatNumber(ops.failure_events ?? state.ingestionFailures.length);
      $('qualityFailed').textContent = formatNumber(ops.failed_checks ?? failed);
      $('qualityScore').textContent = ops.average_quality !== null && ops.average_quality !== undefined
        ? percent(Number(ops.average_quality) / 100)
        : (scoreValues.length ? percent(average(scoreValues)) : '-');
      renderIngestionBlueprintRows('ingestionBlueprintRows');
      renderQualityJobRows('qualityJobRows', state.ingestionJobs.slice(0, 20));
      renderPipelineRunRows('pipelineRunRows', state.pipelineRuns);
      renderConnectorCatalogRows('connectorCatalogRows', state.connectorDefinitions);
      renderNormaliserRows('normaliserRows', state.normaliserDefinitions);
      renderSourceConnectorRows('sourceConnectorRows', state.ingestionSources);
      renderFailureRows('failureRows', state.ingestionFailures);
      renderQualityContractRows('qualityContractRows', state.ingestionContracts);
      renderQualityCheckRows('qualityCheckRows', state.qualityChecks.slice(0, 20));
      renderIngestionDataQuality();
      renderSecurityReadiness();
      renderDeploymentReadiness();
    }

    function qualityMetric(label, section, field = 'quality_score') {
      const value = section?.[field];
      const display = typeof value === 'number' ? percent(value) : '-';
      return `<div class="metric"><span>${escapeHtml(label)}</span><strong>${escapeHtml(display)}</strong><small>${escapeHtml((section?.issues || [])[0] || 'No priority issue loaded')}</small></div>`;
    }

    function renderSkillsValidity() {
      const target = $('skillsValidityPanel');
      if (!target) return;
      const summary = state.skillsValidity;
      const calibration = state.alignmentCalibration || {};
      if (!summary) {
        target.className = 'empty';
        target.textContent = 'Load skills status to see ESCO coverage and alignment readiness.';
        return;
      }
      const counts = summary.counts || {};
      const coverage = summary.coverage || {};
      const actions = summary.next_actions || [];
      const issues = summary.issues || [];
      const acct = state.escoAccounting || null;
      const acctRows = acct && Array.isArray(acct.file_accounting) ? acct.file_accounting : [];
      const escoAccountingSection = acct ? `
        <section class="technical-work-queue" aria-label="ESCO import accounting">
          <div style="width:100%">
            <span class="technical-work-queue__label">ESCO import accounting &mdash; measured ACA partial subset</span>
            <p>${escapeHtml((acct.subset_disclosure || {}).statement || 'Live per-file accounting for the supplied bundle.')}</p>
            <div class="table-wrap">
              <table>
                <thead><tr><th>File</th><th>Received</th><th>Landed</th><th>Skills</th><th>Occupations</th><th>Collections</th><th>Links</th><th>Reconciles</th></tr></thead>
                <tbody>${acctRows.map((r) => `<tr>
                  <td><code style="font-size:11px">${escapeHtml(r.filename || '-')}</code></td>
                  <td>${formatNumber(r.received_rows || 0)}</td>
                  <td>${formatNumber((r.landed || {}).total || 0)}</td>
                  <td>${formatNumber((r.landed || {}).skills || 0)}</td>
                  <td>${formatNumber((r.landed || {}).occupations || 0)}</td>
                  <td>${formatNumber((r.landed || {}).collection_memberships || 0)}</td>
                  <td>${formatNumber((r.landed || {}).occupation_skill_links || 0)}</td>
                  <td>${r.reconciles === true ? statusBadge('yes', 'good') : r.reconciles === false ? statusBadge('short', 'warn') : '<small>n/a (hierarchy/reference)</small>'}</td>
                </tr>`).join('')}</tbody>
              </table>
            </div>
            <p><small>All selected files reconcile: <strong>${(acct.subset_disclosure || {}).all_selected_files_reconcile ? 'yes' : 'no'}</strong>. Shortfalls are within-file duplicate conceptUri rows (deduplicated by the importer). Hierarchy/reference files update existing rows and are not separately countable. Canonical catalogue: ${formatNumber((acct.canonical_invariance || {}).canonical_skills || 0)} skills (unchanged).</small></p>
          </div>
        </section>` : '';
      target.className = '';
      target.innerHTML = `
        <div class="metrics">
          <div class="metric"><span>Overall Score</span><strong>${percent(summary.score || 0)}</strong><small>${escapeHtml(summary.status || 'unknown')}</small></div>
          <div class="metric"><span>ESCO Coverage</span><strong>${percent(coverage.esco_skill_coverage || 0)}</strong><small>${formatNumber(counts.esco_skills || 0)} ESCO records</small></div>
          <div class="metric"><span>Semantic Share</span><strong>${percent(coverage.semantic_mapping_share || 0)}</strong><small>${formatNumber(counts.semantic_mappings || 0)} semantic mappings</small></div>
          <div class="metric"><span>Human Review</span><strong>${formatNumber(counts.needs_review_mappings || 0)}</strong><small>${formatNumber(counts.low_confidence_mappings || 0)} low confidence</small></div>
          <div class="metric"><span>Calibration</span><strong>${percent(coverage.calibrated_alignment_share || 0)}</strong><small>${formatNumber(counts.calibrated_alignments || 0)} calibrated scores</small></div>
        </div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>Validity Area</th><th>Current Evidence</th><th>Interpretation</th></tr></thead>
            <tbody>
              <tr><td>ESCO import</td><td>${formatNumber(counts.esco_skills || 0)} ESCO rows, ${formatNumber(counts.skills || 0)} canonical skills</td><td>${escapeHtml(coverage.esco_skill_coverage >= 0.5 ? 'Coverage is becoming usable.' : 'Import a fuller ESCO export or add local skill mappings.')}</td></tr>
              <tr><td>Semantic matching</td><td>${formatNumber(counts.semantic_mappings || 0)} semantic mappings</td><td>${escapeHtml(coverage.semantic_mapping_share > 0 ? 'Semantic baseline is active.' : 'Run extraction with semantic matching enabled.')}</td></tr>
              <tr><td>Human review</td><td>${formatNumber(counts.approved_mappings || 0)} approved, ${formatNumber(counts.candidate_mappings || 0)} candidate</td><td>${escapeHtml((counts.low_confidence_mappings || 0) ? 'Review low-confidence mappings before formal reporting.' : 'No low-confidence backlog reported.')}</td></tr>
              <tr><td>Alignment calibration</td><td>${formatNumber(calibration.calibrated_total_estimate || counts.calibrated_alignments || 0)} calibrated of ${formatNumber(counts.alignment_scores || 0)}</td><td>${escapeHtml(calibration.mean_abs_model_expert_delta != null ? `Mean model/expert delta ${percent(calibration.mean_abs_model_expert_delta)}` : 'Capture expert alignment scores for representative programmes.')}</td></tr>
            </tbody>
          </table>
        </div>
        <section class="technical-work-queue" aria-label="Skills model preparation work">
          <div>
            <span class="technical-work-queue__label">Current limitation</span>
            <strong>${escapeHtml(issues[0] || 'No blocking skills-evidence limitation is currently reported.')}</strong>
            <p>This describes model and evidence readiness; it is not an alignment finding.</p>
          </div>
          <div>
            <span class="technical-work-queue__label">Data Scientist work queue</span>
            ${actions.length
              ? `<ol>${actions.map((action) => `<li>${escapeHtml(action)}</li>`).join('')}</ol>`
              : '<p class="technical-work-queue__ready">No skills-evidence preparation task is currently outstanding.</p>'}
          </div>
        </section>
        ${escoAccountingSection}
      `;
    }

    function renderIngestionDataQuality() {
      const target = $('ingestionDataQualityPanel');
      if (!target) return;
      const summary = state.ingestionDataQuality;
      if (!summary) {
        target.className = 'empty';
        target.textContent = 'Load ingestion data quality summary to see current scores and next actions.';
        return;
      }
      const curriculum = summary.curriculum_extraction_quality || {};
      const jobs = summary.job_data_cleaning_quality || {};
      const mapping = summary.stats_che_canonical_mapping_quality || {};
      const review = summary.review_queue_quality || {};
      const actions = summary.next_actions || [];
      target.className = '';
      target.innerHTML = `
        <div class="metrics">
          ${qualityMetric('Overall', summary, 'overall_quality_score')}
          ${qualityMetric('Curriculum', curriculum)}
          ${qualityMetric('Job Cleaning', jobs)}
          ${qualityMetric('StatsSA/CHE Mapping', mapping)}
          ${qualityMetric('Review Queue', review)}
        </div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>Area</th><th>Key Counts</th><th>Priority Issues</th></tr></thead>
            <tbody>
              <tr><td>Curriculum extraction</td><td>${formatNumber(curriculum.modules || 0)} modules, ${formatNumber(curriculum.chunks || 0)} chunks, ${formatNumber(curriculum.curriculum_skill_mappings || 0)} mappings</td><td>${escapeHtml((curriculum.issues || []).join(' | ') || 'No issues loaded')}</td></tr>
              <tr><td>Job data cleaning</td><td>${formatNumber(jobs.job_postings || 0)} jobs, ${formatNumber(jobs.cleaned_job_records || 0)} cleaned, ${formatNumber(jobs.duplicate_job_id_groups || 0)} duplicate groups</td><td>${escapeHtml((jobs.issues || []).join(' | ') || 'No issues loaded')}</td></tr>
              <tr><td>StatsSA/CHE canonical mapping</td><td>${formatNumber(mapping.extracted_tables || 0)} tables, ${formatNumber(mapping.extracted_rows || 0)} rows, ${formatNumber(mapping.unknown_row_count || 0)} unknown rows</td><td>${escapeHtml((mapping.issues || []).join(' | ') || 'No issues loaded')}</td></tr>
              <tr><td>Review queue</td><td>${formatNumber(review.queued_records || 0)} queued, ${formatNumber(review.low_confidence_records || 0)} low confidence, ${formatNumber(review.corrected_records || 0)} corrected</td><td>${escapeHtml((review.issues || []).join(' | ') || 'No issues loaded')}</td></tr>
            </tbody>
          </table>
        </div>
        <p><strong>Next actions:</strong> ${escapeHtml(actions.join(' | ') || 'No next actions returned')}</p>
        <div class="actions"><button class="btn" id="remapTableRowsBtn">Remap Extracted Table Rows</button></div>
      `;
      const remapButton = $('remapTableRowsBtn');
      if (remapButton) remapButton.addEventListener('click', () => actions.remapTableRows());
    }

    function renderGovernance() {
      const isViewer = document.body.classList.contains('viewer-audience');
      $('governanceReviews').textContent = formatNumber(state.recommendationReviews.length);
      $('governanceFeedback').textContent = formatNumber(state.recommendationFeedback.length);
      $('governanceHistory').textContent = formatNumber(state.recommendationHistory.length);
      const lifecycleCounts = { Pending: 0, Approved: 0, Rejected: 0, Modified: 0 };
      state.recommendations.forEach((item) => {
        const status = String(item.status || '').toLowerCase();
        if (status.includes('modified')) lifecycleCounts.Modified += 1;
        else if (status === 'approved' || status === 'active') lifecycleCounts.Approved += 1;
        else if (status === 'rejected') lifecycleCounts.Rejected += 1;
        else lifecycleCounts.Pending += 1;
      });
      const lifecycleRows = Object.entries(lifecycleCounts)
        .filter(([, value]) => value > 0)
        .map(([label, value]) => [
          label === 'Pending' && Object.values(lifecycleCounts).filter(Boolean).length === 1
            ? 'Current Queue: Pending Review'
            : label,
          value,
          label === 'Approved' ? 'good' : label === 'Rejected' ? 'bad' : 'warn',
        ]);
      renderBars('statusBars', lifecycleRows);
      if (isViewer && !state.recommendations.length) {
        $('statusBars').innerHTML = '<div class="empty">No decisions have been recorded yet.</div>';
      }
      renderGovernanceRows('governanceRows', state.recommendationHistory);
    }

    function renderReports() {
      const body = $('generatedReportRows');
      if (!body) return;
      const isAnalyst = document.body.classList.contains('analyst-audience');
      const analystTypes = new Set([
        'processing_readiness',
        'ingestion_quality',
        'forecast_quality',
        'curriculum_alignment',
        'skill_gap',
        'executive_summary',
        'governance_audit',
      ]);
      const reports = isAnalyst
        ? state.generatedReports.filter((item) => analystTypes.has(String(item.report_type || '').toLowerCase()))
        : state.generatedReports;
      if (!reports.length) {
        return renderEmpty(body, 5, isAnalyst
          ? { title: 'No Analyst evidence snapshots have been saved yet.', action: 'Generate an eligible quality or decision report to preserve a point-in-time record.' }
          : decisionEmptyState('reports'));
      }
      body.innerHTML = reports.slice(0, 20).map((item) => `
        <tr>
          <td>${escapeHtml(item.title || item.report_id)}</td>
          <td>${escapeHtml(item.report_type)}</td>
          <td>${escapeHtml(item.generated_by || '-')}</td>
          <td>${escapeHtml(new Date(item.created_at).toLocaleString())}</td>
          <td><button class="btn" data-report-detail="${escapeHtml(item.report_id)}">View</button></td>
        </tr>
      `).join('');
      body.querySelectorAll('[data-report-detail]').forEach((button) => {
        button.addEventListener('click', async () => {
          const target = $('generatedReportDetailPanel');
          if (target) {
            target.className = '';
            target.textContent = 'Loading saved evidence snapshot...';
          }
          const detail = await getJson(API_ENDPOINTS.ANALYTICS.REPORT_DETAIL(button.dataset.reportDetail), null, 30000);
          if (!target) return;
          if (!detail) {
            target.className = 'empty';
            target.textContent = 'This saved report could not be loaded.';
            return;
          }
          target.className = '';
          target.innerHTML = `
            <div class="panel-head"><h3>${escapeHtml(detail.title || 'Saved evidence snapshot')}</h3><small>Immutable point-in-time record</small></div>
            <div class="report-snapshot-meta">
              <div><strong>Type</strong><br>${escapeHtml(detail.report_type || '-')}</div>
              <div><strong>Generated by</strong><br>${escapeHtml(detail.generated_by || '-')}</div>
              <div><strong>Created</strong><br>${escapeHtml(detail.created_at ? new Date(detail.created_at).toLocaleString() : '-')}</div>
            </div>
            ${detail.notes ? `<p><strong>Notes:</strong> ${escapeHtml(detail.notes)}</p>` : ''}
            <h4>Summary</h4>
            <pre class="report-snapshot-json">${escapeHtml(JSON.stringify(detail.summary || {}, null, 2))}</pre>
            <details><summary>Show full captured payload</summary><pre class="report-snapshot-json">${escapeHtml(JSON.stringify(detail.payload || {}, null, 2))}</pre></details>
          `;
          target.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        });
      });
    }

    function renderRecommendationRows(id, rows) {
      const body = $(id);
      const isViewer = document.body.classList.contains('viewer-audience');
      const isDecisionAudience = isViewer || document.body.classList.contains('analyst-audience');
      const sourceRows = Array.isArray(rows) ? rows : [];
      const filter = String(state.recommendationSearchFilter || '').trim().toLowerCase();
      const filtered = filter ? sourceRows.filter((row) => {
        const item = row.representative || row.recommendation || row;
        const meta = item.recommendation_metadata || {};
        return [item.title, item.status, item.priority, row.programme, row.module_label, meta.programme, meta.module_label]
          .some((value) => String(value || '').toLowerCase().includes(filter));
      }) : sourceRows;
      const result = paginate(filtered, state.recPage, 10);
      if (!result.items.length) {
        renderPagination('recommendationPagination', 1, 1, () => {});
        return renderEmpty(body, 6, filter
          ? { title: 'No recommendations match this filter', action: 'Clear or change the search text to see the review queue.' }
          : isDecisionAudience
            ? { title: 'No published recommendations are available yet.' }
            : decisionEmptyState('recommendations'));
      }
      body.innerHTML = result.items.map((row) => {
        const item = row.representative || row.recommendation || row;
        const meta = item.recommendation_metadata || {};
        const programme = row.programme || meta.programme || 'Programme not assigned';
        const moduleLabel = row.module_label || meta.module_label || 'Programme-level / multiple modules';
        const groupedCount = row.recommendation_count || meta.group_recommendation_count || 1;
        const evidenceCount = meta.skill_demand_evidence_count || meta.labour_evidence_count || 0;
        return `
        <tr>
          <td>${escapeHtml(item.title || 'Untitled recommendation')}<br><small>${escapeHtml(programme)} &middot; ${escapeHtml(moduleLabel)}${groupedCount > 1 ? ` &middot; ${formatNumber(groupedCount)} grouped` : ''}</small></td>
          <td>${statusBadge(item.priority, priorityTone(item.priority))}<br><small>${percent(item.priority_score || row.highest_priority_score || 0)}</small></td>
          <td>${statusBadge(item.status, statusTone(item.status))}</td>
          <td>${formatNumber(evidenceCount)}</td>
          <td>${percent(item.confidence_score || 0)}</td>
          <td><button class="btn" data-dossier-id="${escapeHtml(item.recommendation_id)}">Dossier</button></td>
        </tr>`;
      }).join('');
      body.querySelectorAll('[data-dossier-id]').forEach((button) => {
        button.addEventListener('click', () => actions.loadRecommendationDossier(button.dataset.dossierId));
      });
      renderPagination('recommendationPagination', result.page, result.pages, (page) => {
        state.recPage = page;
        const source = state.recommendationStatusFilter === 'all'
          ? state.recommendations
          : (state.recommendationGroups.length ? state.recommendationGroups : state.recommendations.filter((item) => item.status === 'pending_review'));
        renderRecommendationRows('latestRecommendations', source);
      });
    }

    function renderRecommendationDossier() {
      const dossier = state.selectedRecommendationDossier;
      const target = $('recommendationDossier');
      if (!dossier) {
        $('dossierCaption').textContent = 'Select a recommendation';
        target.className = 'empty';
        target.textContent = 'Select a recommendation to review its evidence, forecast, explanations, and decision history.';
        return;
      }

      const recommendation = dossier.recommendation || {};
      const skill = dossier.skill || {};
      const summary = dossier.evidence_summary || {};
      const signalKeys = summary.canonical_signal_keys || [];
      const topEvidence = (dossier.demand_evidence || []).slice(0, 5);
      const explanations = dossier.explanations || [];
      $('dossierCaption').textContent = `${recommendation.priority || 'priority'} priority`;
      target.className = '';
      target.innerHTML = `
        <div class="grid">
          <div class="span-5">
            <h3>${escapeHtml(recommendation.title || 'Recommendation')}</h3>
            <p>${escapeHtml(recommendation.description || '')}</p>
            <p><strong>Skill:</strong> ${escapeHtml(skill.name || 'Unmapped skill')}</p>
            <p><strong>Status:</strong> ${statusBadge(recommendation.status, statusTone(recommendation.status))}</p>
            <div class="actions">
              <button class="btn primary" data-review-action="approve" data-review-id="${escapeHtml(recommendation.recommendation_id)}">Approve</button>
              <button class="btn danger" data-review-action="reject" data-review-id="${escapeHtml(recommendation.recommendation_id)}">Reject</button>
              <button class="btn" data-lineage-id="${escapeHtml(recommendation.recommendation_id)}">Lineage</button>
              <button class="btn" data-dossier-export="json" data-report-id="${escapeHtml(recommendation.recommendation_id)}">JSON</button>
              <button class="btn" data-dossier-export="csv" data-report-id="${escapeHtml(recommendation.recommendation_id)}">CSV</button>
            </div>
          </div>
          <div class="span-7">
            <div class="metrics">
              <div class="metric"><span>Demand Evidence</span><strong>${formatNumber(summary.skill_demand_evidence_count || 0)}</strong><small>Skill-signal links</small></div>
              <div class="metric"><span>Demand Score</span><strong>${percent(summary.skill_demand_score || 0)}</strong><small>Weighted evidence</small></div>
              <div class="metric"><span>Reviews</span><strong>${formatNumber(summary.review_count || 0)}</strong><small>Human decisions</small></div>
            </div>
          </div>
          <div class="span-12">
            <p><strong>Canonical signals:</strong> ${signalKeys.length ? signalKeys.map((key) => statusBadge(key, 'good')).join(' ') : '-'}</p>
            <div id="lineageSummary" class="empty">Open lineage to trace this recommendation back to source records and processing events.</div>
          </div>
          <div class="span-6">
            <h3>Top Evidence</h3>
            <div class="table-wrap">
              <table>
                <thead><tr><th>Context</th><th>Score</th><th>Confidence</th></tr></thead>
                <tbody>${topEvidence.length ? topEvidence.map((item) => `
                  <tr>
                    <td>${escapeHtml(item.matched_context)}</td>
                    <td>${percent(item.demand_score || 0)}</td>
                    <td>${percent(item.confidence_score || 0)}</td>
                  </tr>
                `).join('') : '<tr><td colspan="3">No demand evidence available.</td></tr>'}</tbody>
              </table>
            </div>
          </div>
          <div class="span-6">
            <h3>Explanations</h3>
            <div class="table-wrap">
              <table>
                <thead><tr><th>Type</th><th>Explanation</th></tr></thead>
                <tbody>${explanations.length ? explanations.map((item) => `
                  <tr>
                    <td>${escapeHtml(item.explanation_type)}</td>
                    <td>${escapeHtml(item.explanation_text)}</td>
                  </tr>
                `).join('') : '<tr><td colspan="2">No explanations available.</td></tr>'}</tbody>
              </table>
            </div>
          </div>
        </div>
      `;
      target.querySelectorAll('[data-review-action]').forEach((button) => {
        button.addEventListener('click', () => actions.reviewRecommendation(button.dataset.reviewId, button.dataset.reviewAction));
      });
      target.querySelectorAll('[data-dossier-export]').forEach((button) => {
          button.addEventListener('click', () => actions.exportDossierReport(button.dataset.reportId, button.dataset.dossierExport));
      });
      target.querySelectorAll('[data-lineage-id]').forEach((button) => {
          button.addEventListener('click', () => actions.loadRecommendationLineage(button.dataset.lineageId));
      });
    }

    function curriculumProgrammeRows() {
      const programmes = state.curriculumHierarchy?.programmes || [];
      const modules = state.curriculumHierarchy?.modules || [];
      const moduleCounts = modules.reduce((acc, item) => {
        const key = item.programme_id || item.program_id || item.qualification_id || item.programme_code || item.course_code;
        if (key) acc[key] = (acc[key] || 0) + 1;
        return acc;
      }, {});
      return programmes.map((programme, index) => {
        const key = programme.programme_id || programme.program_id || programme.qualification_id || programme.programme_code || programme.course_code || String(index);
        return {
          document_id: null,
          synthetic_id: 'programme-' + key,
          title: programme.title || programme.name || programme.programme_name || programme.qualification_title || programme.course_title || 'Imported programme',
          faculty: programme.faculty || programme.faculty_name || programme.institution || 'CPUT',
          programme: programme.qualification_type || programme.programme_type || programme.nqf_level || programme.department || '-',
          created_at: programme.created_at || programme.updated_at || programme.imported_at || new Date().toISOString(),
          status: programme.status || 'active',
          type: 'Programme',
          module_count: moduleCounts[key] || Number(programme.module_count || programme.modules_count || 0),
        };
      });
    }

    function renderCurriculumQualityNotes() {
      const target = $('curriculumQualityNotes');
      if (!target) return;
      const quality = state.curriculumQuality;
      if (!quality) {
        target.className = 'empty';
        target.textContent = 'Curriculum quality summary is unavailable. Refresh the page or check the API connection.';
        return;
      }
      const issues = quality.issues || [];
      const zeroModules = quality.zero_module_programmes || [];
      const moduleCompleteness = quality.module_completeness || {};
      const summaryItems = [
        `${formatNumber(quality.programmes || 0)} programmes`,
        `${formatNumber(quality.modules || 0)} modules`,
        `${formatNumber(quality.chunks || 0)} evidence chunks`,
        `${formatNumber(quality.curriculum_skill_mappings || 0)} curriculum-skill mappings`,
      ];
      const notes = issues.length
        ? issues.map((issue) => `<li class="quality-warning">${escapeHtml(issue)}</li>`).join('')
        : '<li class="quality-ready">No curriculum completeness warning is currently reported.</li>';
      const completenessBars = Object.entries(moduleCompleteness).map(([key, value]) => {
        const label = key.replace(/^with_/, '').replaceAll('_', ' ');
        const score = Math.max(0, Math.min(100, Number(value?.percent || 0)));
        const tone = score < 80 ? 'needs-attention' : score < 100 ? 'in-progress' : 'complete';
        return `<div class="quality-progress-item ${tone}">
          <div class="quality-progress-label"><span>${escapeHtml(label)}</span><strong>${score.toFixed(0)}%</strong></div>
          <div class="quality-progress-track" role="progressbar" aria-label="${escapeHtml(label)} completeness" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${score.toFixed(0)}">
            <span class="quality-progress-fill" style="width:${score}%"></span>
          </div>
        </div>`;
      }).join('');
      target.className = 'quality-notes';
      target.innerHTML = `
        <p><strong>Current evidence:</strong> ${summaryItems.map(escapeHtml).join(' &middot; ')}</p>
        <ul class="quality-warning-list">${notes}</ul>
        ${completenessBars ? `<section class="quality-completeness" aria-labelledby="moduleCompletenessHeading"><h4 id="moduleCompletenessHeading">Module metadata completeness</h4><div class="quality-progress-grid">${completenessBars}</div></section>` : ''}
        ${zeroModules.length ? `<p><strong>Programmes requiring module review:</strong> ${zeroModules.slice(0, 8).map((item) => escapeHtml(item.programme_name || 'Unnamed programme')).join(', ')}${zeroModules.length > 8 ? ` and ${zeroModules.length - 8} more` : ''}</p>` : ''}
      `;
    }

    function renderCurriculumRows(id, rows) {
      const body = $(id);
      if (state.selectedCurriculumDoc !== null) return;
      const filter = state.curriculumSearchFilter;
      const statusFilter = state.curriculumStatusFilter;
      let filtered = rows;
      if (filter) {
        const lower = filter.toLowerCase();
        filtered = filtered.filter((r) =>
          (r.title || '').toLowerCase().includes(lower) ||
          (r.faculty || '').toLowerCase().includes(lower) ||
          (r.programme || '').toLowerCase().includes(lower) ||
          (r.department || '').toLowerCase().includes(lower)
        );
      }
      if (statusFilter) {
        filtered = filtered.filter((r) => (r.status || '').toLowerCase() === statusFilter.toLowerCase());
      }
      const result = paginate(filtered, state.curriculumPage, 15);
      if (!result.items.length) {
        $('curriculumTableCaption').textContent = '0 curriculum records shown';
        renderPagination('curriculumPagination', 1, 1, () => {});
        const message = filter || statusFilter
          ? {
              title: 'No records found',
              reason: 'No curriculum records match the current search or status filter.',
              action: 'Try adjusting your filters to see more results.',
            }
          : {
              title: 'No curriculum records available',
              reason: 'No curriculum evidence has been uploaded yet.',
              action: 'An authorised Analyst or Administrator can upload evidence in Data Operations.',
            };
        return renderEmpty(body, 8, message);
      }
      const detailMap = {};
      state.documentDetails.forEach((d, i) => { if (d) detailMap[d.document?.document_id || state.documents[i]?.document_id] = d; });
      body.innerHTML = result.items.map((doc) => {
        const det = doc.document_id ? detailMap[doc.document_id] : null;
        const versions = det?.versions || [];
        const chunkCount = doc.type === 'Programme' ? Number(doc.module_count || 0) : versions.reduce((sum, v) => sum + Number(v.chunk_count || 0), 0);
        const rowType = doc.type || 'Document';
        const action = doc.document_id ? `<button class="btn" data-curriculum-view="${doc.document_id}">View</button>` : 'Imported';
        const facultyDisplay = doc.faculty || 'Unassigned';
        const programmeDisplay = doc.programme || 'Unassigned';
        const extractionStatus = versions[versions.length - 1]?.extraction_status || doc.extraction_status || '';
        const zeroReason = ['pending', 'queued', 'running', 'processing'].includes(String(extractionStatus).toLowerCase())
          ? 'Pending extraction'
          : (doc.type === 'Programme' ? 'No module data in source' : 'No extracted chunks');
        const countDisplay = chunkCount > 0
          ? formatNumber(chunkCount)
          : `<span title="${escapeHtml(zeroReason)}">0 <small>(${escapeHtml(zeroReason)})</small></span>`;
        return `
          <tr class="curriculum-record-row">
            <td><strong>${escapeHtml(doc.title)}</strong></td>
            <td title="${doc.faculty ? '' : 'Assign in Data Operations > Subject Profile Validation'}">${escapeHtml(facultyDisplay)}</td>
            <td title="${doc.programme ? '' : 'Assign in Data Operations > Subject Profile Validation'}">${escapeHtml(programmeDisplay)}</td>
            <td>${new Date(doc.created_at).toLocaleDateString()}</td>
            <td>${escapeHtml(rowType)}</td>
            <td>${countDisplay}</td>
            <td>${statusBadge(doc.status, doc.status === 'active' ? 'good' : doc.status === 'archived' ? 'warn' : '')}</td>
            <td>${action}</td>
          </tr>
        `;
      }).join('');
      const idx = state.documents.findIndex((d) => d.document_id === result.items[0]?.document_id);
      $('curriculumTableCaption').textContent = `${formatNumber(filtered.length)} curriculum record${filtered.length !== 1 ? 's' : ''} shown`;
      renderPagination('curriculumPagination', result.page, result.pages, (page) => {
        state.curriculumPage = page;
        renderCurriculumRows(id, [...(state.documents || []), ...curriculumProgrammeRows()]);
      });
      body.querySelectorAll('[data-curriculum-view]').forEach((btn) => {
        btn.addEventListener('click', () => actions.showCurriculumDetail(btn.dataset.curriculumView));
      });
    }

    function renderCurriculumJobs() {
      const body = $('curriculumJobRows');
      if (!body) return;
      const curriculumJobIds = new Set();
      state.documentDetails.forEach((det) => {
        if (!det) return;
        (det.versions || []).forEach((v) => { if (v.job_id) curriculumJobIds.add(String(v.job_id)); });
      });
      const jobs = state.ingestionJobs.filter((j) => curriculumJobIds.has(String(j.job_id))).slice(0, 10);
      if (!jobs.length) return renderEmpty(body, 5, 'No curriculum ingestion jobs recorded yet.');
      body.innerHTML = jobs.map((job) => `
        <tr>
          <td><code>${String(job.job_id || '').slice(0, 8)}</code></td>
          <td>${escapeHtml(job.source_name || job.source_key || job.parameters?.source_name || job.parameters?.filename || job.job_type || 'Unassigned source')}</td>
          <td>${statusBadge(job.status, job.status === 'completed' ? 'good' : job.status === 'failed' ? 'bad' : job.status === 'running' ? 'warn' : '')}</td>
          <td>${formatNumber(job.records_loaded ?? job.records_seen ?? job.progress_current ?? 0)}</td>
          <td>${job.created_at ? new Date(job.created_at).toLocaleString() : '-'}</td>
        </tr>
      `).join('');
    }

    function renderSkillMappingRows(id, rows) {
      const body = $(id);
      const isViewer = document.body.classList.contains('viewer-audience');
      const isDecisionAudience = isViewer || document.body.classList.contains('analyst-audience');
      const filter = state.skillMappingSearchFilter;
      const filtered = filter ? rows.filter((r) =>
        (r.source_domain || '').toLowerCase().includes(filter) ||
        (r.matched_text || '').toLowerCase().includes(filter)
      ) : rows;
      const result = paginate(filtered, state.skillMappingPage, 12);
      if (!result.items.length) return renderEmpty(body, 5, filter
        ? { title: 'No mappings match this filter', action: 'Clear or change the search term.' }
        : isDecisionAudience
          ? { title: 'No reviewed skill mappings are available yet.' }
          : decisionEmptyState('skillMappings'));
      body.innerHTML = result.items.map((item) => `
        <tr>
          <td>${escapeHtml(item.source_domain)}</td>
          <td>${escapeHtml(item.matched_text)}</td>
          <td>${percent(item.confidence_score || 0)}</td>
        </tr>
      `).join('');
      renderPagination('skillMappingPagination', result.page, result.pages, (page) => {
        state.skillMappingPage = page;
        renderSkillMappingRows('skillMappingRows', state.skillMappings);
      });
    }

    function renderSkillGapRows(id, rows) {
      const body = $(id);
      const isViewer = document.body.classList.contains('viewer-audience');
      const isDecisionAudience = isViewer || document.body.classList.contains('analyst-audience');
      const filter = state.skillGapSearchFilter;
      const typeFilter = state.skillGapTypeFilter;
      let filtered = rows;
      if (filter) {
        const lower = filter.toLowerCase();
        filtered = filtered.filter((r) =>
          (r.skill_name || '').toLowerCase().includes(lower) ||
          (r.skill_key || '').toLowerCase().includes(lower)
        );
      }
      if (typeFilter) {
        filtered = filtered.filter((r) => (r.gap_type || '') === typeFilter);
      }
      const result = paginate(filtered, state.skillGapPage, 12);
      if (!result.items.length) {
        const msg = filter || typeFilter
          ? { title: 'No gaps match this filter', action: 'Clear or change the gap filters.' }
          : isDecisionAudience
            ? { title: 'No validated alignment findings are available yet.' }
            : decisionEmptyState('skillGaps');
        return renderEmpty(body, 6, msg);
      }
      body.innerHTML = result.items.map((item) => {
        const recCount = Number(item.pending_recommendations || 0);
        const recommendationText = recCount > 0
          ? `<a href="recommendations.html" style="color:var(--accent);text-decoration:none;font-weight:600">${formatNumber(recCount)} pending</a>`
          : 'No pending review';
        const whyText = item.why_this_skill_matters || 'Open Details to inspect the evidence behind this gap.';
        return `
          <tr>
            <td>${escapeHtml(item.skill_name || item.skill_key || '-') }<br><small>${escapeHtml(item.skill_key || item.skill_id || '')}</small><br><small>${escapeHtml(whyText)}</small></td>
            <td>${statusBadge(item.gap_type || 'gap', item.gap_type === 'missing' ? 'bad' : item.gap_type === 'weak_alignment' ? 'warn' : 'good')}<br><small>Coverage ${percent(item.coverage_ratio || 0)}</small></td>
            <td>${percent(item.skill_demand_score || 0)}<br><small>${formatNumber(item.skill_demand_evidence_count || 0)} evidence records</small></td>
            <td>${item.forecast_trend ? statusBadge(item.forecast_trend, item.forecast_trend === 'increasing' ? 'warn' : item.forecast_trend === 'decreasing' ? 'bad' : 'good') : '-'}<br><small>${item.forecast_value === null || item.forecast_value === undefined ? '' : formatNumber(item.forecast_value)}</small></td>
            <td>${recommendationText}</td>
            <td><button class="btn sm" data-skill-gap-detail="${escapeHtml(item.skill_id)}" data-version-id="${escapeHtml(item.version_id || '')}">Details</button></td>
          </tr>
        `;
      }).join('');
      body.querySelectorAll('[data-skill-gap-detail]').forEach((button) => {
        button.addEventListener('click', () => actions.loadSkillGapEvidence(button.dataset.skillGapDetail, button.dataset.versionId || null));
      });
      renderPagination('skillGapPagination', result.page, result.pages, (page) => {
        state.skillGapPage = page;
        renderSkillGapRows('skillGapRows', state.skillGapSummary?.gaps || []);
      });
    }

    function evidenceCard(title, rows, renderer) {
      return `
        <div class="panel span-4">
          <div class="panel-head"><h3>${escapeHtml(title)}</h3><small>${formatNumber(rows.length)} records</small></div>
          ${rows.length ? rows.slice(0, 8).map(renderer).join('') : '<p><small>No evidence loaded for this source category yet.</small></p>'}
        </div>
      `;
    }

    function renderSkillGapEvidence(detail) {
      const target = $('skillGapEvidencePanel');
      const section = $('skillGapEvidenceSection');
      if (!target || !section) return;
      section.classList.remove('hidden');
      if (!detail?.found) {
        target.className = 'empty';
        target.textContent = 'No evidence details are available for this gap yet.';
        return;
      }
      const groups = detail.source_groups || {};
      target.className = '';
      $('skillGapEvidenceCaption').textContent = `${detail.skill?.name || 'Skill'} evidence grouped by curriculum, job trends, and current jobs`;
      target.innerHTML = `
        <div class="panel">
          <div class="panel-head"><h3>${escapeHtml(detail.skill?.name || 'Skill evidence')}</h3><small>${escapeHtml(detail.skill?.skill_key || '')}</small></div>
          <p>${statusBadge(detail.gap_type || 'finding', detail.gap_type === 'missing' ? 'bad' : detail.gap_type === 'weak_alignment' ? 'warn' : 'good')} ${escapeHtml(detail.why_this_skill_matters || 'Evidence is available for review.')}</p>
          <p>${statusBadge('curriculum')} ${formatNumber(detail.counts?.curriculum || 0)} ${statusBadge('job trends')} ${formatNumber(detail.counts?.job_trends || 0)} ${statusBadge('regional jobs')} ${formatNumber(detail.counts?.current_jobs || 0)}</p>
          <p><small>Curriculum scope: ${escapeHtml(detail.curriculum_scope || 'validated curriculum evidence')} · Regional scope: ${escapeHtml(detail.regional_job_insights?.regional_scope || 'Western Cape / South Africa')}</small></p>
        </div>
        <div class="grid">
          ${evidenceCard('Curriculum Evidence', groups.curriculum || [], (item) => `
            <p>${statusBadge('curriculum')} ${escapeHtml(item.document_title || item.source_entity_type || 'Curriculum source')}<br>
            <small>${escapeHtml([item.programme, item.module, item.page_start ? `page ${item.page_start}` : ''].filter(Boolean).join(' / ') || '-')}</small><br>
            <small>${escapeHtml((item.evidence_text || item.matched_text || '').slice(0, 280))}</small></p>
          `)}
          ${evidenceCard('Job Trend Evidence', groups.job_trends || [], (item) => `
            <p>${statusBadge('job trends', 'warn')} ${escapeHtml(item.canonical_name || item.canonical_key || 'Trend signal')}<br>
            <small>${escapeHtml([item.dimension, item.period].filter(Boolean).join(' / ') || '-')} ? demand ${percent(item.demand_score || 0)}</small><br>
            <small>${escapeHtml((item.rationale || item.source_summary || item.matched_context || '').slice(0, 280))}</small></p>
          `)}
          ${evidenceCard('Regional Job Records', groups.current_jobs || [], (item) => `
            <p>${statusBadge('current jobs', 'good')} ${escapeHtml(item.job_title || item.matched_text || 'Job record')}<br>
            <small>${escapeHtml([item.company_or_source, item.region, item.posted_date ? new Date(item.posted_date).toLocaleDateString() : ''].filter(Boolean).join(' / ') || '-')}</small><br>
            <small>${escapeHtml((item.evidence_text || item.matched_text || '').slice(0, 280))}</small>${item.source_url ? `<br><a href="${escapeHtml(item.source_url)}" target="_blank">Source</a>` : ''}</p>
          `)}
        </div>
      `;
    }

    function forecastMethodLabel(method) {
      const raw = String(method || '').trim();
      if (!raw) return '-';
      if (raw === 'canonical_signal_weighted_baseline_v2' || raw.includes('weighted_baseline')) {
        return 'Weighted Baseline';
      }
      if (raw.includes('statistical_baseline')) return 'Statistical Baseline';
      return raw.replaceAll('_', ' ').replace(/\b\w/g, (character) => character.toUpperCase());
    }

    let forecastExplanationPreviousFocus = null;

    function forecastConfidenceInterpretation(confidence) {
      if (confidence >= 0.8) return 'relatively high confidence, while still subject to source and model limitations';
      if (confidence >= 0.6) return 'moderate confidence, indicating some variability or uncertainty in the supporting signals';
      return 'limited confidence, so the projection should be treated as preliminary evidence';
    }

    function openForecastExplanation(forecastId) {
      const modal = $('forecastExplanationModal');
      if (!modal) return;
      const item = state.forecasts.find((row) => String(row.forecast_id) === String(forecastId));
      if (!item) return;
      const label = forecastSkillLabel(item);
      const confidence = Number(item.confidence_score || 0);
      const horizon = Number(item.horizon_periods || 0);
      const method = item.method || 'Method not recorded';
      const direction = item.trend_direction || 'not classified';
      const baseline = Number(item.baseline_value || 0);
      const projected = Number(item.forecast_value || 0);
      const horizonText = horizon ? ` over the next ${horizon} quarter${horizon === 1 ? '' : 's'}` : '';
      const plainText = `This ${direction} projection compares a current demand value of ${formatNumber(baseline)} with a projected value of ${formatNumber(projected)}${horizonText}. It was produced using ${method.replaceAll('_', ' ')}. The ${percent(confidence)} confidence represents ${forecastConfidenceInterpretation(confidence)}.`;

      $('forecastExplanationSkill').textContent = label;
      $('forecastExplanationSkillName').textContent = label;
      $('forecastExplanationMethod').textContent = method;
      $('forecastExplanationConfidence').textContent = percent(confidence);
      $('forecastExplanationDirection').textContent = direction;
      $('forecastExplanationBaseline').textContent = formatNumber(baseline);
      $('forecastExplanationProjected').textContent = formatNumber(projected);
      $('forecastExplanationPlainText').textContent = plainText;
      $('forecastExplanationRawText').textContent = item.explanation || 'No additional model explanation was recorded for this forecast.';
      renderForecastProvenance(item);
      forecastExplanationPreviousFocus = document.activeElement;
      modal.classList.remove('hidden');
      $('forecastExplanationCloseBtn')?.focus();
    }

    function renderForecastProvenance(item) {
      const target = $('forecastExplanationProvenance');
      const wrap = $('forecastExplanationProvenanceWrap');
      if (!target) return;
      const prov = (item.forecast_payload || {}).provenance || null;
      if (!prov) {
        // Graceful fallback for forecasts generated before the dossier was baked in.
        if (wrap) wrap.style.display = 'none';
        return;
      }
      if (wrap) wrap.style.display = '';
      const src = prov.query_source || {};
      const counts = prov.record_counts || {};
      const win = prov.observation_window || {};
      const unc = prov.uncertainty || {};
      const baselines = prov.baselines || {};
      const basisNote = prov.provenance_basis === 'read_time_current_evidence_base'
        ? `<p class="muted" style="margin:0 0 8px;font-size:12px"><strong>Provenance basis:</strong> ${escapeHtml(prov.provenance_note || 'read-time current evidence base')}</p>`
        : `<p class="muted" style="margin:0 0 8px;font-size:12px"><strong>Provenance basis:</strong> generation-time immutable dossier.</p>`;
      const sourceList = Object.entries(src.job_posting_sources || {})
        .map(([name, count]) => `${escapeHtml(name)} (${formatNumber(count)})`).join(', ') || 'unspecified';
      const jobIds = (prov.ingestion_job_ids || []).slice(0, 6)
        .map((id) => `<code style="font-size:11px">${escapeHtml(String(id).slice(0, 12))}…</code>`).join(' ') || 'none referenced';
      const limitations = (prov.known_limitations || []).map((l) => `<li>${escapeHtml(l)}</li>`).join('');
      target.innerHTML = `
        ${basisNote}
        <dl class="forecast-explanation-summary" style="margin:0 0 8px">
          <div><dt>Query / source</dt><dd>${escapeHtml(src.description || '-')}<br><small>Sources: ${sourceList}</small></dd></div>
          <div><dt>Ingestion job IDs</dt><dd>${jobIds}</dd></div>
          <div><dt>Observation range</dt><dd>${escapeHtml(win.earliest_posted_date || 'n/a')} → ${escapeHtml(win.latest_posted_date || 'n/a')}</dd></div>
          <div><dt>Record counts</dt><dd>${formatNumber(counts.job_postings || 0)} postings · ${formatNumber(counts.labour_market_signals || 0)} signals · ${formatNumber(counts.usable_labour_mappings || 0)} mappings</dd></div>
          <div><dt>Method</dt><dd>${escapeHtml(prov.method || '-')} (${escapeHtml(baselines.model_family || '-')})</dd></div>
          <div><dt>Dataset snapshot fingerprint</dt><dd><code style="font-size:11px">${escapeHtml(String(prov.dataset_snapshot_fingerprint || 'n/a').slice(0, 24))}${prov.dataset_snapshot_fingerprint ? '…' : ''}</code></dd></div>
          <div><dt>Explanation fingerprint</dt><dd><code style="font-size:11px">${escapeHtml(String((item.forecast_payload || {}).explanation_fingerprint || 'n/a').slice(0, 24))}…</code></dd></div>
          <div><dt>Uncertainty</dt><dd>${escapeHtml(unc.confidence_basis || '-')} Backtest: ${escapeHtml(unc.backtest_status || '-')}.</dd></div>
        </dl>
        <p style="margin:6px 0"><strong>Deduplication rule:</strong> <small>${escapeHtml(prov.deduplication_rule || '-')}</small></p>
        <p style="margin:6px 0"><strong>Baselines:</strong> <small>naive last-value: ${escapeHtml(baselines.naive_last_value || '-')}; successor candidates: ${escapeHtml((baselines.candidate_successor_models || []).join(', ') || 'none')}.</small></p>
        ${limitations ? `<p style="margin:6px 0"><strong>Known limitations:</strong></p><ul style="margin:0 0 0 18px">${limitations}</ul>` : ''}`;
    }

    function closeForecastExplanation() {
      const modal = $('forecastExplanationModal');
      if (!modal) return;
      modal.classList.add('hidden');
      if (forecastExplanationPreviousFocus?.focus) forecastExplanationPreviousFocus.focus();
      forecastExplanationPreviousFocus = null;
    }

    function renderForecastRows(id, rows) {
      const body = $(id);
      const isViewer = document.body.classList.contains('viewer-audience');
      const isDecisionAudience = isViewer || document.body.classList.contains('analyst-audience');
      const filter = state.forecastSearchFilter;
      let filtered = uniqueForecastsBySkill(rows);
      if (isDecisionAudience) {
        filtered = filtered.filter((item) => {
          const name = forecastSkillLabel(item);
          return name && name.toLowerCase() !== 'unmapped skill';
        });
      }
      if (filter) filtered = filtered.filter((item) => forecastSkillLabel(item).toLowerCase().includes(filter));
      const result = paginate(filtered, state.forecastPage, 15);
      if (!result.items.length) return renderEmpty(body, isDecisionAudience ? 7 : 9, filter
        ? { title: 'No forecasts match this filter', action: 'Clear or change the skill search.' }
        : isDecisionAudience
          ? { title: 'No published demand outlook is available yet.' }
          : decisionEmptyState('forecasts'));
      body.innerHTML = result.items.map((item) => `
        <tr>
          <td><strong>${escapeHtml(forecastSkillLabel(item))}</strong></td>
          <td>${formatNumber(item.baseline_value || 0)}</td>
          <td>${formatNumber(item.forecast_value || 0)}</td>
          <td>${statusBadge(item.trend_direction, item.trend_direction === 'increasing' ? 'warn' : item.trend_direction === 'decreasing' ? 'bad' : 'good')}</td>
          <td>${percent(item.confidence_score || 0)}</td>
          <td class="viewer-hidden analyst-hidden" title="${escapeHtml(item.method || 'Method not recorded')}"><small>${escapeHtml(forecastMethodLabel(item.method))}</small></td>
          <td class="viewer-hidden analyst-hidden"><small>${escapeHtml(item.forecast_type || '-')}</small></td>
          <td><small>${item.created_at ? new Date(item.created_at).toLocaleDateString() : '-'}</small></td>
          <td>${item.explanation ? `<button class="btn sm" type="button" data-forecast-explanation="${escapeHtml(item.forecast_id)}" aria-label="View forecast explanation for ${escapeHtml(forecastSkillLabel(item))}">Explanation</button>` : '<small>-</small>'}</td>
        </tr>
      `).join('');
      renderPagination('forecastPagination', result.page, result.pages, (page) => {
        state.forecastPage = page;
        renderForecastRows('forecastRows', state.forecasts);
      });
    }

    function renderGovernanceRows(id, rows) {
      const body = $(id);
      const filter = state.governanceSearchFilter;
      const filtered = filter ? rows.filter((r) =>
        (r.transition_type || '').toLowerCase().includes(filter) ||
        (r.new_status || '').toLowerCase().includes(filter)
      ) : rows;
      const result = paginate(filtered, state.governancePage, 12);
      if (!result.items.length) return renderEmpty(body, 5, filter
        ? { title: 'No governance events match this filter', action: 'Clear or change the filter.' }
        : decisionEmptyState('governance'));
      body.innerHTML = result.items.map((item) => `
        <tr>
          <td>${escapeHtml(item.transition_type)}</td>
          <td>${statusBadge(item.new_status, statusTone(item.new_status))}</td>
          <td>${escapeHtml(item.change_reason || '-')}</td>
          <td>${escapeHtml(item.changed_by || item.reviewer || item.reviewed_by || '-')}</td>
          <td>${escapeHtml(item.created_at ? new Date(item.created_at).toLocaleDateString() : '-')}</td>
        </tr>
      `).join('');
      renderPagination('governancePagination', result.page, result.pages, (page) => {
        state.governancePage = page;
        renderGovernanceRows('governanceRows', state.recommendationHistory);
      });
    }

    function renderQualityJobRows(id, rows) {
      const body = $(id);
      if (!rows.length) return renderEmpty(body, 8, 'No ingestion jobs have run yet.');
      body.innerHTML = rows.map((job) => {
        const summary = state.qualitySummaries[job.job_id] || {};
        const cleaned = Object.values(summary.cleaned_records || {}).reduce((sum, value) => sum + Number(value || 0), 0);
        const checks = summary.checks || {};
        const checkText = `${checks.passed || 0} pass / ${checks.warning || 0} warn / ${checks.failed || 0} fail`;
        const score = summary.average_quality_score === null || summary.average_quality_score === undefined ? '-' : percent(summary.average_quality_score);
        const canRetry = ['failed', 'completed_with_errors', 'retry_scheduled'].includes(job.status);
        return `
          <tr>
            <td>${escapeHtml(job.job_type)}<br><small>${escapeHtml(job.job_id)}</small></td>
            <td>${statusBadge(job.status, statusTone(job.status))}</td>
            <td>${formatNumber(job.attempt_number || 1)} / ${formatNumber(job.max_attempts || 1)}${job.next_retry_at ? `<br><small>${escapeHtml(new Date(job.next_retry_at).toLocaleString())}</small>` : ''}</td>
            <td>${formatNumber(job.records_loaded || job.records_seen || 0)}</td>
            <td>${formatNumber(cleaned)}</td>
            <td>${escapeHtml(checkText)}</td>
            <td>${escapeHtml(score)}</td>
            <td>
              <div class="actions">
                <button class="btn" data-quality-run="${escapeHtml(job.job_id)}">Run</button>
                <button class="btn" data-trend-run="${escapeHtml(job.job_id)}">Trends</button>
                ${canRetry ? `<button class="btn" data-job-retry="${escapeHtml(job.job_id)}">Retry</button>` : ''}
                <button class="btn" data-signal-run>Signals</button>
                <button class="btn" data-demand-evidence-run>Evidence</button>
              </div>
            </td>
          </tr>
        `;
      }).join('');
      body.querySelectorAll('[data-quality-run]').forEach((button) => {
        button.addEventListener('click', () => actions.runQuality(button.dataset.qualityRun));
      });
      body.querySelectorAll('[data-trend-run]').forEach((button) => {
        button.addEventListener('click', () => actions.runTrendNormalisation(button.dataset.trendRun));
      });
      body.querySelectorAll('[data-job-retry]').forEach((button) => {
        button.addEventListener('click', () => actions.retryJob(button.dataset.jobRetry));
      });
      body.querySelectorAll('[data-signal-run]').forEach((button) => {
        button.addEventListener('click', () => actions.runSignalGeneration());
      });
      body.querySelectorAll('[data-demand-evidence-run]').forEach((button) => {
        button.addEventListener('click', () => actions.runDemandEvidenceGeneration());
      });
    }

    function renderIngestionBlueprintRows(id) {
      renderKeyValueRows(id, [
        ['Tenant and source ownership', `${formatNumber(state.ingestionSources.filter((item) => item.tenant_id).length)} tenant sources, ${formatNumber(state.ingestionSources.filter((item) => !item.tenant_id).length)} shared sources`, statusBadge('implemented', 'good')],
        ['Connector abstraction', `${formatNumber(state.connectorDefinitions.length)} connector definitions`, statusBadge('implemented', 'good')],
        ['Higher education context', `${formatNumber(state.ingestionSources.filter((item) => item.source_category === 'higher_education_context').length)} CHE/context source registered`, statusBadge('implemented', 'good')],
        ['Resilience and failed handling', `${formatNumber(state.ingestionFailures.length)} failure events, ${formatNumber(state.ingestionJobs.filter((job) => job.status === 'retry_scheduled').length)} scheduled retries`, statusBadge('implemented', 'good')],
        ['Normaliser registry', `${formatNumber(state.normaliserDefinitions.length)} normalisers, versioned cleaned-record metadata`, statusBadge('implemented', 'good')],
        ['Contracts and quality checks', `${formatNumber(state.ingestionContracts.length)} contracts, ${formatNumber(state.qualityChecks.length)} recent checks loaded`, statusBadge('implemented', 'good')],
        ['Pipeline orchestration', `${formatNumber(state.pipelineRuns.length)} recorded full pipeline runs`, statusBadge(state.pipelineRuns.length ? 'available' : 'ready', state.pipelineRuns.length ? 'good' : 'warn')],
      ]);
    }

    function renderConnectorCatalogRows(id, rows) {
      const body = $(id);
      if (!rows.length) return renderEmpty(body, 5, 'No connector definitions are registered yet.');
      body.innerHTML = rows.slice(0, 20).map((item) => `
        <tr>
          <td>${escapeHtml(item.name)}<br><small>${escapeHtml(item.connector_key)}</small></td>
          <td>${escapeHtml(item.connector_family)}</td>
          <td>${statusBadge(item.ingestion_mode, item.ingestion_mode === 'streaming' ? 'warn' : 'good')}</td>
          <td>${escapeHtml(item.source_format)}</td>
          <td><button class="btn" data-connector-edit="${escapeHtml(item.connector_key)}">Edit</button></td>
        </tr>
      `).join('');
      body.querySelectorAll('[data-connector-edit]').forEach((button) => {
        button.addEventListener('click', () => actions.editConnector(button.dataset.connectorEdit));
      });
    }

    function renderNormaliserRows(id, rows) {
      const body = $(id);
      if (!rows.length) return renderEmpty(body, 5, 'No normaliser definitions are registered yet.');
      body.innerHTML = rows.slice(0, 20).map((item) => `
        <tr>
          <td>${escapeHtml(item.name)}<br><small>${escapeHtml(item.normaliser_key)} v${escapeHtml(item.version)}</small></td>
          <td>${escapeHtml(item.input_format)}</td>
          <td>${escapeHtml(item.output_record_type)}</td>
          <td><small>${escapeHtml(item.description || 'Versioned payload transformation')}</small></td>
          <td>${statusBadge(item.status, statusTone(item.status))}</td>
        </tr>
      `).join('');
    }

    function renderQualityContractRows(id, rows) {
      const body = $(id);
      if (!rows.length) return renderEmpty(body, 4, 'No ingestion contracts have been created yet.');
      body.innerHTML = rows.map((item) => `
        <tr>
          <td>${escapeHtml(item.contract_key)}<br><small>v${escapeHtml(item.version)}</small></td>
          <td>${escapeHtml(item.record_type)}</td>
          <td>${statusBadge(item.status, statusTone(item.status))}</td>
          <td>
            <div class="actions">
              <button class="btn" data-contract-drift="${escapeHtml(item.contract_id)}">Drift</button>
              <button class="btn" data-contract-edit="${escapeHtml(item.contract_id)}">Edit</button>
              <button class="btn" data-contract-clone="${escapeHtml(item.contract_id)}">Clone</button>
            </div>
          </td>
        </tr>
      `).join('');
      body.querySelectorAll('[data-contract-drift]').forEach((button) => {
        button.addEventListener('click', () => actions.loadContractDrift(button.dataset.contractDrift));
      });
      body.querySelectorAll('[data-contract-edit]').forEach((button) => {
        button.addEventListener('click', () => actions.editContract(button.dataset.contractEdit));
      });
      body.querySelectorAll('[data-contract-clone]').forEach((button) => {
        button.addEventListener('click', () => actions.cloneContract(button.dataset.contractClone));
      });
    }

    function renderSourceConnectorRows(id, rows) {
      const body = $(id);
      if (!rows.length) return renderEmpty(body, 4, 'No source connectors have been registered yet.');
      body.innerHTML = rows.slice(0, 10).map((item) => `
        <tr>
          <td>${escapeHtml(item.name)}<br><small>${escapeHtml(item.connector_type)}</small></td>
          <td>${statusBadge(item.is_authorised ? item.status : 'unauthorised', item.is_authorised && item.status === 'active' ? 'good' : 'warn')}<br>${statusBadge(item.circuit_state || 'closed', item.circuit_state === 'open' ? 'bad' : 'good')}</td>
          <td>${escapeHtml(item.refresh_policy || '-')}${item.normaliser_key ? `<br><small>${escapeHtml(item.normaliser_key)}</small>` : ''}</td>
          <td>
            <button class="btn" data-source-toggle="${escapeHtml(item.source_id)}" data-source-action="${item.is_authorised && item.status === 'active' ? 'disable' : 'enable'}">${item.is_authorised && item.status === 'active' ? 'Disable' : 'Enable'}</button>
          </td>
        </tr>
      `).join('');
      body.querySelectorAll('[data-source-toggle]').forEach((button) => {
        button.addEventListener('click', () => actions.toggleSource(button.dataset.sourceToggle, button.dataset.sourceAction));
      });
    }

    function renderFailureRows(id, rows) {
      const body = $(id);
      if (!rows.length) return renderEmpty(body, 5, 'No failed ingestion events have been recorded yet.');
      body.innerHTML = rows.slice(0, 20).map((item) => `
        <tr>
          <td>${escapeHtml(new Date(item.event_time).toLocaleString())}<br><small>${escapeHtml(item.job_id)}</small></td>
          <td>${escapeHtml(item.failure_stage)}</td>
          <td>${statusBadge(item.failure_category, item.failure_category === 'validation' ? 'warn' : 'bad')}</td>
          <td>${statusBadge(item.retryable, item.retryable === 'true' ? 'warn' : '')}${item.next_retry_at ? `<br><small>${escapeHtml(new Date(item.next_retry_at).toLocaleString())}</small>` : ''}</td>
          <td>${escapeHtml(item.message)}</td>
        </tr>
      `).join('');
    }

    function renderPipelineRunRows(id, rows) {
      const body = $(id);
      if (!rows.length) return renderEmpty(body, 6, 'No full pipeline runs have been recorded yet.');
      body.innerHTML = rows.slice(0, 10).map((item) => {
        const stages = item.summary?.stages || {};
        const stageCount = item.summary?.stage_count ?? Object.keys(stages).length;
        const reportCount = stages.reports?.reports_generated ?? 0;
        const jobId = item.summary?.job_id || '-';
        return `
          <tr>
            <td>${escapeHtml((item.pipeline_run_id || '').slice(0, 8))}<br><small>${escapeHtml(jobId)}</small></td>
            <td>${statusBadge(item.status, statusTone(item.status))}</td>
            <td>${escapeHtml(item.triggered_by || '-')}</td>
            <td>${escapeHtml(item.started_at ? new Date(item.started_at).toLocaleString() : '-')}</td>
            <td>${formatNumber(stageCount)}</td>
            <td>${formatNumber(reportCount)} reports<br><small>${escapeHtml(item.error_summary || 'completed stages recorded')}</small></td>
          </tr>
        `;
      }).join('');
    }

    function renderQualityCheckRows(id, rows) {
      const body = $(id);
      if (!rows.length) return renderEmpty(body, 4, 'No quality checks are available yet.');
      body.innerHTML = rows.map((item) => `
        <tr>
          <td>${statusBadge(item.status, item.status === 'passed' ? 'good' : item.status === 'warning' ? 'warn' : 'bad')}</td>
          <td>${statusBadge(item.severity, item.severity === 'error' ? 'bad' : item.severity === 'warning' ? 'warn' : '')}</td>
          <td>${escapeHtml(item.message)}</td>
          <td>${escapeHtml(item.check_metadata?.rule_key || '-')}</td>
        </tr>
      `).join('');
    }

    function renderProcessingPhase() {
      const body = $('processingRows');
      if (!body) return;
      const summary = state.processingSummary;
      if (!summary) return renderEmpty(body, 4, 'Processing summary has not been loaded yet.');
      const readiness = summary.readiness || {};
      const counts = summary.counts || {};
      const warnings = (readiness.checks || []).filter((item) => item.status === 'warning' || item.status === 'blocking');
      const canonicalCounts = [
        `Cleaned: ${formatNumber(counts.cleaned_records || 0)}`,
        `Trends: ${formatNumber(counts.labour_market_trends || 0)}`,
        `Signals: ${formatNumber(counts.labour_market_signals || 0)}`,
        `Skill evidence: ${formatNumber(counts.skill_demand_evidence || 0)}`,
        `Alignments: ${formatNumber(counts.alignment_scores || 0)}`,
        `Forecasts: ${formatNumber(counts.forecasts || 0)}`,
        `Recommendations: ${formatNumber(counts.recommendations || 0)}`,
      ].join(' | ');
      const latestReports = (summary.latest_processing_reports || []).slice(0, 3).map((report) => `${report.report_type}: ${String(report.report_id || '').slice(0, 8)}`).join(' | ');
      body.innerHTML = `
        <tr>
          <td>${statusBadge(readiness.status || 'unknown', readiness.status === 'blocked' ? 'bad' : readiness.status === 'ready' ? 'good' : 'warn')}<br><small>${formatNumber(readiness.ready_checks || 0)} ready, ${formatNumber(readiness.warning_checks || 0)} warnings, ${formatNumber(readiness.blocking_checks || 0)} blocking</small></td>
          <td><small>${escapeHtml(canonicalCounts)}</small></td>
          <td><small>${escapeHtml(warnings.map((item) => `${item.key}: ${item.message}`).join(' | ') || 'No processing warnings')}</small></td>
          <td><small>${escapeHtml((readiness.next_focus || []).join(' | '))}</small><br><small>${escapeHtml(latestReports || 'No processing reports archived yet')}</small></td>
        </tr>
      `;
      const processingCaption = $('processingCaption');
      if (processingCaption) processingCaption.textContent = summary.latest_report_id ? `Latest processing report ${summary.latest_report_id}` : 'Processing summary loaded';
    }

    function renderOperationalJobRows() {
      const body = $('operationalJobRows');
      if (!body) return;
      const jobPrefix = body.dataset.jobPrefix || '';
      const rows = (state.operationalJobs || []).filter(
        (job) => !jobPrefix || String(job.job_type || '').startsWith(jobPrefix)
      );
      if (!rows.length) {
        return renderEmpty(body, 7, 'No durable operational jobs have been submitted yet.');
      }
      body.innerHTML = rows.map((job) => {
        const total = Number(job.progress_total || 100);
        const current = Number(job.progress_current || 0);
        const progress = total > 0 ? Math.round((current / total) * 100) : 0;
        const canRetry = ['failed', 'cancelled'].includes(job.status);
        const canCancel = ['queued', 'running', 'retry_scheduled'].includes(job.status);
        const publicError = job.error_summary
          ? (String(job.job_type || '').includes('restore')
              ? 'Restore test could not create or validate the temporary database. Check restore authority and server logs.'
              : String(job.job_type || '').includes('rollback')
                ? 'Rollback rehearsal did not complete. Check the prerequisite report and server logs.'
                : 'The operation did not complete. Check the prerequisite report and server logs.')
          : '';
        return `
          <tr>
            <td><code>${escapeHtml(String(job.job_id || '').slice(0, 8))}</code><br><small>${escapeHtml(job.job_type || '-')}</small></td>
            <td>${statusBadge(job.status, statusTone(job.status))}</td>
            <td>${formatNumber(progress)}%<br><small>${escapeHtml(job.progress_message || '-')}</small></td>
            <td>${formatNumber(job.attempt_number || 0)} / ${formatNumber(job.max_attempts || 0)}</td>
            <td>${escapeHtml(job.requested_by || '-')}</td>
            <td>${escapeHtml(job.started_at ? new Date(job.started_at).toLocaleString() : '-')}<br><small>${escapeHtml(job.completed_at ? new Date(job.completed_at).toLocaleString() : '')}</small></td>
            <td>
              ${canRetry ? `<button class="btn" data-operational-retry="${job.job_id}">Retry</button>` : ''}
              ${canCancel ? `<button class="btn danger" data-operational-cancel="${job.job_id}">Cancel</button>` : ''}
              ${publicError ? `<br><small>${escapeHtml(publicError)}</small>` : ''}
            </td>
          </tr>
        `;
      }).join('');
      body.querySelectorAll('[data-operational-retry]').forEach((button) =>
        button.addEventListener('click', () => actions.retryOperationalJob(button.dataset.operationalRetry))
      );
      body.querySelectorAll('[data-operational-cancel]').forEach((button) =>
        button.addEventListener('click', () => actions.cancelOperationalJob(button.dataset.operationalCancel))
      );
      const trainingPanel = $('trainingJobsPanel');
      if (trainingPanel && jobPrefix === 'model.train.') {
        trainingPanel.className = '';
        trainingPanel.innerHTML = rows.slice(0, 5).map((job) => {
          const total = Number(job.progress_total || 100);
          const current = Number(job.progress_current || 0);
          const progress = total > 0 ? Math.round((current / total) * 100) : 0;
          return `<p><strong>${escapeHtml(String(job.job_type || '').replace('model.train.', '').toUpperCase())}</strong> ${statusBadge(job.status, statusTone(job.status))} · ${formatNumber(progress)}% · job <code>${escapeHtml(String(job.job_id || '').slice(0, 8))}</code><br><small>${escapeHtml(job.progress_message || 'No progress message')} · ${escapeHtml(job.completed_at ? new Date(job.completed_at).toLocaleString() : 'in progress')}</small></p>`;
        }).join('');
      }
    }

    function renderContractOps() {
      const target = $('contractOpsPanel');
      if (!target) return;
      const contract = state.selectedContract;
      if (!contract) {
        target.className = 'empty';
        target.textContent = 'Select Drift or Edit from a contract row.';
        return;
      }
      const drift = state.selectedContractDrift;
      target.className = '';
      target.innerHTML = `
        <div class="panel">
          <div class="panel-head"><h3>${escapeHtml(contract.name)}</h3><small>${escapeHtml(contract.contract_key)} v${escapeHtml(contract.version)}</small></div>
          <p><strong>Record type:</strong> ${escapeHtml(contract.record_type)} ${statusBadge(contract.status, statusTone(contract.status))}</p>
          <p><strong>Expected schema:</strong> <code>${escapeHtml(JSON.stringify(contract.schema_definition || {}))}</code></p>
          <p><strong>Cleaning profile:</strong> <code>${escapeHtml(JSON.stringify(contract.cleaning_profile || {}))}</code></p>
          <p><strong>Quality thresholds:</strong> <code>${escapeHtml(JSON.stringify(contract.quality_thresholds || {}))}</code></p>
          ${drift ? `
            <p><strong>Drift:</strong> ${statusBadge(drift.status, drift.status === 'stable' ? 'good' : 'warn')} ${percent(drift.drift_score || 0)} across ${formatNumber(drift.records_checked)} records</p>
            <p><strong>Missing:</strong> ${escapeHtml((drift.missing_fields || []).map((item) => `${item.field} (${item.count})`).join(', ') || '-')}</p>
            <p><strong>Unexpected:</strong> ${escapeHtml((drift.unexpected_fields || []).map((item) => `${item.field} (${item.count})`).join(', ') || '-')}</p>
          ` : '<p>Run Drift to compare recent payloads to the contract.</p>'}
        </div>
      `;
    }

    function reviewSourceCategory(record) {
      const category = record.source_category || record.normalised_payload?.source_category || record.raw_payload?.source_category || 'unknown';
      if (category === 'labour_market_trends') return { label: 'job trends', tone: 'warn' };
      if (category === 'current_jobs' || category === 'job_board') return { label: 'current jobs', tone: 'good' };
      if (category === 'curriculum') return { label: 'curriculum', tone: '' };
      return { label: category, tone: '' };
    }

    function renderReviewRecordRows() {
      const body = $('reviewRecordRows');
      if (!state.reviewRecords.length) return renderEmpty(body, 5, 'No rejected/noisy rows loaded yet.');
      body.innerHTML = state.reviewRecords.slice(0, 50).map((record) => {
        const category = reviewSourceCategory(record);
        const payload = record.normalised_payload || record.raw_payload || {};
        const quality = payload.quality_score === undefined ? '' : ` ? quality ${percent(payload.quality_score || 0)}`;
        const confidence = payload.confidence_score === undefined ? '' : ` ? confidence ${percent(payload.confidence_score || 0)}`;
        return `
          <tr>
            <td>${escapeHtml(record.record_id)}<br><small>${escapeHtml(record.source_name || record.source_record_id || '-')}</small></td>
            <td>${statusBadge(category.label, category.tone)}<br><small>${escapeHtml(record.record_type)}${escapeHtml(quality + confidence)}</small></td>
            <td>${statusBadge(record.validation_status, statusTone(record.validation_status))}</td>
            <td><small>${escapeHtml(JSON.stringify(payload).slice(0, 260))}</small></td>
            <td>
              <div class="actions">
                <button class="btn" data-review-record="${escapeHtml(record.record_id)}" data-review-status="approved">Approve</button>
                <button class="btn" data-review-correct="${escapeHtml(record.record_id)}">Correct</button>
                <button class="btn" data-review-record="${escapeHtml(record.record_id)}" data-review-status="noise">Noise</button>
                <button class="btn" data-review-record="${escapeHtml(record.record_id)}" data-review-status="rejected">Reject</button>
              </div>
            </td>
          </tr>
        `;
      }).join('');
      body.querySelectorAll('[data-review-record]').forEach((button) => {
        button.addEventListener('click', () => actions.reviewRecord(button.dataset.reviewRecord, button.dataset.reviewStatus));
      });
      body.querySelectorAll('[data-review-correct]').forEach((button) => {
        button.addEventListener('click', () => actions.correctRecord(button.dataset.reviewCorrect));
      });
    }

    function renderModelReadiness() {
      const readiness = state.modelReadiness || {};
      const target = $('modelReadinessPanel');
      if (!target) return;
      const maturity = $('modelMaturity');
      const caption = $('modelMaturityCaption');
      const xgbTs = $('xgboostLastTrained');
      const lstmTs = $('lstmLastTrained');
      if (maturity) maturity.textContent = readiness.model_maturity || '-';
      if (caption) caption.textContent = `${readiness.ready_gates || 0} ready gates, ${readiness.blocked_gates || 0} blocked`;
      const xgb = state.xgboostLastTrained || readiness.xgboost_last_trained;
      const lstm = state.lstmLastTrained || readiness.lstm_last_trained;
      if (xgbTs && xgb) xgbTs.textContent = `Last trained: ${new Date(xgb).toLocaleString()}`;
      if (lstmTs && lstm) lstmTs.textContent = `Last trained: ${new Date(lstm).toLocaleString()}`;
      const gates = readiness.gates || [];
      target.innerHTML = `
        <div class="kv-grid">
          <div><strong>Alignment baseline</strong><span>${escapeHtml(readiness.current_alignment_model || '-')}</span></div>
          <div><strong>Forecast baseline</strong><span>${escapeHtml(readiness.current_forecast_model || '-')}</span></div>
          <div><strong>XGBoost</strong><span>${escapeHtml(readiness.xgboost_status || '-')}</span></div>
          <div><strong>LSTM</strong><span>${escapeHtml(readiness.lstm_status || '-')}</span></div>
        </div>
        <div class="table-wrap" style="margin-top:12px">
          <table><thead><tr><th>Gate</th><th>Status</th><th>Requirement</th></tr></thead><tbody>
            ${gates.map((gate) => `<tr><td>${escapeHtml(gate.key)}</td><td>${statusBadge(gate.status, gate.status === 'ready' ? 'good' : 'warn')}</td><td>${escapeHtml(gate.message)}</td></tr>`).join('')}
          </tbody></table>
        </div>
      `;
    }

    function renderSecurityReadiness() {
      const target = $('securityReadinessPanel');
      if (!target) return;
      const summary = state.securityReadiness;
      if (!summary) {
        target.className = 'empty';
        target.textContent = 'Load security and operations readiness report.';
        return;
      }
      const rbac = summary.rbac_tenant_hardening || {};
      const credentials = summary.credential_security || {};
      const scheduler = summary.scheduler || {};
      const monitoring = summary.monitoring || {};
      const backups = summary.backups || {};
      target.className = '';
      target.innerHTML = `
        <div class="metrics">
          <div class="metric"><span>Overall Score</span><strong>${percent(summary.score || 0)}</strong><small>${escapeHtml(summary.status || 'unknown')}</small></div>
          <div class="metric"><span>RBAC/Tenants</span><strong>${percent(rbac.quality_score || 0)}</strong><small>${formatNumber(rbac.active_roles || 0)} roles, ${formatNumber(rbac.active_tenants || 0)} tenants</small></div>
          <div class="metric"><span>Credentials</span><strong>${percent(credentials.quality_score || 0)}</strong><small>${formatNumber(credentials.credentialed_sources || 0)} credentialed sources</small></div>
          <div class="metric"><span>Scheduler</span><strong>${percent(scheduler.quality_score || 0)}</strong><small>${formatNumber(scheduler.scheduled_sources || 0)} scheduled sources</small></div>
          <div class="metric"><span>Monitoring</span><strong>${percent(monitoring.quality_score || 0)}</strong><small>${formatNumber(monitoring.failure_events || 0)} failure events</small></div>
          <div class="metric"><span>Backups</span><strong>${percent(backups.quality_score || 0)}</strong><small>${formatNumber(backups.manifest_count || 0)} manifests</small></div>
        </div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>Area</th><th>Current State</th><th>Issues</th></tr></thead>
            <tbody>
              <tr><td>RBAC / tenant</td><td>${formatNumber(rbac.active_user_roles || 0)} active user roles, ${formatNumber(rbac.tenant_sources || 0)} tenant sources</td><td>${escapeHtml((rbac.issues || []).join(' | ') || 'No issues returned')}</td></tr>
              <tr><td>Credential security</td><td>${formatNumber(credentials.fernet_encrypted_sources || 0)} Fernet, ${formatNumber(credentials.signed_fallback_sources || 0)} fallback</td><td>${escapeHtml((credentials.issues || []).join(' | ') || 'No issues returned')}</td></tr>
              <tr><td>Scheduler</td><td>${formatNumber(scheduler.due_sources || 0)} due, ${formatNumber(scheduler.retry_scheduled_jobs || 0)} retry scheduled</td><td>${escapeHtml((scheduler.issues || []).join(' | ') || 'No issues returned')}</td></tr>
              <tr><td>Monitoring</td><td>${formatNumber(monitoring.ingestion_jobs || 0)} jobs, ${percent(monitoring.failure_rate || 0)} failure rate</td><td>${escapeHtml((monitoring.issues || []).join(' | ') || 'No issues returned')}</td></tr>
              <tr><td>Backups</td><td>${escapeHtml(backups.backup_mode || '-')}, latest ${escapeHtml(backups.latest_manifest || 'none')}</td><td>${escapeHtml((backups.issues || []).join(' | ') || 'No issues returned')}</td></tr>
            </tbody>
          </table>
        </div>
        ${(summary.next_actions || []).length ? `
          <div class="operation-worklist">
            <strong>Administrator work queue</strong>
            <ul>${summary.next_actions.map((item) => `<li>${escapeHtml(item)}</li>`).join('')}</ul>
          </div>` : ''}
      `;
    }

    function renderDeploymentReadiness() {
      const target = $('deploymentReadinessPanel');
      if (!target) return;
      const summary = state.deploymentReadiness;
      if (!summary) {
        target.className = 'empty';
        target.textContent = 'Load deployment and UAT readiness report.';
        return;
      }
      const deployment = summary.deployment || {};
      const secrets = summary.managed_secrets || {};
      const nginx = summary.nginx_https || {};
      const uat = summary.uat || {};
      const docs = summary.documentation || {};
      target.className = '';
      target.innerHTML = `
        <div class="metrics">
          <div class="metric"><span>Overall Score</span><strong>${percent(summary.score || 0)}</strong><small>${escapeHtml(summary.status || 'unknown')}</small></div>
          <div class="metric"><span>Deployment</span><strong>${percent(deployment.quality_score || 0)}</strong><small>Docker/Compose assets</small></div>
          <div class="metric"><span>Managed Secrets</span><strong>${percent(secrets.quality_score || 0)}</strong><small>Injection and rotation controls</small></div>
          <div class="metric"><span>TLS Configuration</span><strong>${percent(nginx.quality_score || 0)}</strong><small>Template plus installed certificate files</small></div>
          <div class="metric"><span>UAT</span><strong>${percent(uat.quality_score || 0)}</strong><small>Automated and manual checks</small></div>
          <div class="metric"><span>Final Docs</span><strong>${percent(docs.quality_score || 0)}</strong><small>A-F readiness package</small></div>
        </div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>Area</th><th>Current State</th><th>Issues</th></tr></thead>
            <tbody>
              <tr><td>Container/server deployment</td><td>${escapeHtml(JSON.stringify(deployment.compose_services || {}))}</td><td>${escapeHtml((deployment.issues || []).join(' | ') || 'No issues returned')}</td></tr>
              <tr><td>Managed secrets</td><td>${escapeHtml(JSON.stringify(secrets.checks || {}))}</td><td>${escapeHtml((secrets.issues || []).join(' | ') || secrets.note || 'No issues returned')}</td></tr>
              <tr><td>TLS and reverse proxy</td><td>${escapeHtml(JSON.stringify(nginx.checks || {}))}</td><td>${escapeHtml((nginx.issues || []).join(' | ') || nginx.certificate_note || 'Configuration evidence loaded; verify the live HTTPS endpoint separately.')}</td></tr>
              <tr><td>UAT scripts</td><td>${escapeHtml(JSON.stringify(uat.checks || {}))}</td><td>${escapeHtml((uat.issues || []).join(' | ') || 'No issues returned')}</td></tr>
              <tr><td>Final documentation</td><td>${escapeHtml(JSON.stringify(docs.checks || {}))}</td><td>${escapeHtml((docs.issues || []).join(' | ') || 'No issues returned')}</td></tr>
            </tbody>
          </table>
        </div>
        ${(summary.next_actions || []).length ? `
          <div class="operation-worklist">
            <strong>Release work queue</strong>
            <ul>${summary.next_actions.map((item) => `<li>${escapeHtml(item)}</li>`).join('')}</ul>
          </div>` : ''}
      `;
    }

    function renderPortalUat() {
      const target = $('portalUatPanel');
      if (!target) return;
      const run = state.portalUat;
      if (!run || run.result === 'not_run') {
        target.className = 'empty';
        target.textContent = 'No portal acceptance run has been recorded yet. Select Run Portal UAT.';
        return;
      }
      const summary = run.summary || {};
      const renderChecks = (checks) => (checks || []).map((item) => {
        const tone = item.status === 'passed' ? 'good' : item.status === 'expected_block' ? 'warn' : 'bad';
        const label = item.status === 'expected_block' ? 'safely blocked' : item.status;
        return `<tr>
          <td><strong>${escapeHtml(item.name || item.key)}</strong><br><small>${escapeHtml(item.key)}</small></td>
          <td>${statusBadge(label, tone)}</td>
          <td>${escapeHtml(item.evidence || '-')}</td>
          <td>${escapeHtml(item.user_action || (item.status === 'failed' ? 'Resolve before sign-off.' : 'No action required.'))}</td>
        </tr>`;
      }).join('');
      target.className = '';
      target.innerHTML = `
        <div class="metrics">
          <div class="metric"><span>Result</span><strong>${escapeHtml(run.result || 'unknown')}</strong><small>Report ${escapeHtml(String(run.report_id || '').slice(0, 8))}</small></div>
          <div class="metric"><span>Passed</span><strong>${formatNumber(summary.passed || 0)}</strong><small>Functional controls</small></div>
          <div class="metric"><span>Safe Blocks</span><strong>${formatNumber(summary.expected_blocks || 0)}</strong><small>Expected failure behavior</small></div>
          <div class="metric"><span>Failed</span><strong>${formatNumber(summary.failed || 0)}</strong><small>Must resolve</small></div>
        </div>
        <p class="decision-limitation"><strong>Interpretation:</strong> ${escapeHtml(run.interpretation || '')}</p>
        <h3>Golden path</h3>
        <div class="table-wrap"><table>
          <thead><tr><th>Check</th><th>Result</th><th>Evidence</th><th>User action</th></tr></thead>
          <tbody>${renderChecks(run.golden_path)}</tbody>
        </table></div>
        <h3 style="margin-top:16px">Failure path</h3>
        <div class="table-wrap"><table>
          <thead><tr><th>Check</th><th>Result</th><th>Evidence</th><th>User action</th></tr></thead>
          <tbody>${renderChecks(run.failure_path)}</tbody>
        </table></div>
        <p><strong>Evidence hash:</strong> <code>${escapeHtml(run.payload_hash || '-')}</code></p>
      `;
    }

    function renderConnectorOps() {
      const target = $('connectorOpsPanel');
      if (!target) return;
      const source = state.selectedSource;
      if (!source) {
        target.className = 'empty';
        target.textContent = 'Select Health, Enable, Disable, Schedule, Auth, or Files from a source row.';
        return;
      }
      const health = state.selectedSourceHealth;
      const history = state.selectedSourceHealthHistory;
      const files = state.selectedSourceFiles || [];
      target.className = '';
      target.innerHTML = `
        <div class="grid">
          <div class="panel span-6">
            <div class="panel-head"><h3>${escapeHtml(source.name)}</h3><small>${escapeHtml(source.source_key)}</small></div>
            <p>${statusBadge(source.status, statusTone(source.status))} ${statusBadge(source.source_category)} ${statusBadge(source.source_scope)}</p>
            <p><strong>Schedule:</strong> ${escapeHtml(JSON.stringify((source.config || {}).schedule || {}))}</p>
            <p><strong>Retry:</strong> ${escapeHtml(JSON.stringify(source.retry_policy || {}))}</p>
            <p><strong>Auth:</strong> ${escapeHtml(source.auth_config && Object.keys(source.auth_config).length ? 'configured' : 'not configured')}</p>
          </div>
          <div class="panel span-6">
            <div class="panel-head"><h3>Health</h3><small>${health?.checked_at ? escapeHtml(new Date(health.checked_at).toLocaleString()) : 'Not checked this session'}</small></div>
            <p>${health ? statusBadge(health.status, health.status === 'healthy' ? 'good' : 'warn') : statusBadge('not checked')}</p>
            <p>${escapeHtml(health?.message || 'Run Health to test reachability and storage availability.')}</p>
          </div>
          <div class="panel span-6">
            <div class="panel-head"><h3>Health History</h3><small>${formatNumber(history?.recent_jobs?.length || 0)} recent jobs</small></div>
            ${(history?.recent_jobs || []).slice(0, 5).map((job) => `<p>${statusBadge(job.status, statusTone(job.status))} ${escapeHtml(job.job_type)} ${formatNumber(job.records_loaded)} loaded</p>`).join('') || '<p>No history loaded.</p>'}
          </div>
          <div class="panel span-6">
            <div class="panel-head"><h3>File Archive</h3><small>${formatNumber(files.length)} source files/records</small></div>
            ${files.slice(0, 6).map((file) => `<p>${statusBadge(file.freshness_status, file.freshness_status === 'fresh' ? 'good' : 'warn')} ${escapeHtml(file.source_file || file.storage_uri || file.content_hash || '-')}<br><small>${formatNumber(file.record_count)} records, ${formatNumber(file.duplicate_count)} duplicates</small>${file.storage_uri ? `<br><a class="btn" href="${API_ENDPOINTS.INGESTION.FILE_DOWNLOAD}?storage_uri=${encodeURIComponent(file.storage_uri)}" target="_blank">Download</a>` : ''}</p>`).join('') || '<p>No file archive loaded.</p>'}
          </div>
        </div>
      `;
    }

    function renderLineageSummary(lineage) {
      const target = $('lineageSummary');
      if (!target || !lineage) return;
      const summary = lineage.summary || {};
      const stages = Array.from(new Set((lineage.lineage_events || []).map((item) => item.processing_stage))).slice(0, 8);
      target.className = '';
      target.innerHTML = `
        <div class="metrics">
          <div class="metric"><span>Lineage Nodes</span><strong>${formatNumber(summary.node_count || 0)}</strong><small>Trace graph</small></div>
          <div class="metric"><span>Lineage Edges</span><strong>${formatNumber(summary.edge_count || 0)}</strong><small>Relationships</small></div>
          <div class="metric"><span>Processing Events</span><strong>${formatNumber(summary.lineage_event_count || 0)}</strong><small>Audit lineage</small></div>
        </div>
        <p><strong>Processing stages:</strong> ${stages.length ? stages.map((stage) => statusBadge(stage, 'good')).join(' ') : '-'}</p>
      `;
    }



    function renderModelDatasetSnapshot() {
      const target = $('modelDatasetSnapshotPanel');
      const leakageTarget = $('modelLeakagePanel');
      if (!target && !leakageTarget) return;
      const snapshot = state.modelDatasetSnapshot;
      if (!snapshot) {
        const lstmButton = $('trainLstmBtn');
        if (lstmButton) lstmButton.disabled = true;
        if (target) {
          target.className = 'empty';
          target.textContent = 'No dataset snapshot recorded yet. Create a snapshot before training candidate models.';
        }
        if (leakageTarget) {
          leakageTarget.className = 'empty';
          leakageTarget.innerHTML = '<strong>Fold-safe preprocessing enforced.</strong> VIF feature filtering and class weighting are fitted only on each training fold/window. Validation and holdout rows are transform-only. A locked reviewed dataset is still required to produce run-specific evidence.';
        }
        return;
      }
      const lstmButton = $('trainLstmBtn');
      if (lstmButton) {
        const snapshotType = String(snapshot.model_type || '').toLowerCase();
        lstmButton.disabled = snapshotType !== 'general' && snapshotType !== 'lstm';
      }
      if (target) {
        target.className = '';
        target.innerHTML = `
          <div class="metrics">
            <div class="metric"><span>Fingerprint</span><strong>${escapeHtml(String(snapshot.dataset_fingerprint || '').slice(0, 12))}</strong><small>${escapeHtml(snapshot.snapshot_version || '-')}</small></div>
            <div class="metric"><span>Observation Window</span><strong>${escapeHtml((snapshot.min_observation_date || '-').slice(0, 10))}</strong><small>to ${escapeHtml((snapshot.max_observation_date || '-').slice(0, 10))}</small></div>
            <div class="metric"><span>Raw Records</span><strong>${formatNumber(snapshot.raw_records_count || 0)}</strong><small>job postings + raw ingestion</small></div>
            <div class="metric"><span>Cleaned Records</span><strong>${formatNumber(snapshot.cleaned_records_count || 0)}</strong><small>model-ready records</small></div>
          </div>
          <table>
            <tbody>
              <tr><th>Model type</th><td>${escapeHtml(snapshot.model_type || '-')}</td><td>${statusBadge(snapshot.leakage_checks?.status || 'unknown', snapshot.leakage_checks?.warnings?.length ? 'warn' : 'good')}</td></tr>
              <tr><th>Curriculum</th><td>${formatNumber(snapshot.curriculum_summary?.modules_included_count || 0)} modules</td><td>${formatNumber(snapshot.curriculum_summary?.programmes_included_count || 0)} programme values</td></tr>
              <tr><th>Labour market</th><td>${formatNumber(snapshot.labour_market_summary?.job_postings_count || 0)} job postings</td><td>${formatNumber(snapshot.labour_market_summary?.canonical_signals_count || 0)} canonical signals</td></tr>
              <tr><th>Split policy</th><td colspan="2">${escapeHtml(snapshot.split_policy?.split_strategy || '-')} - shuffle=${escapeHtml(String(snapshot.split_policy?.shuffle ?? false))}</td></tr>
              <tr><th>Target</th><td colspan="2">${escapeHtml(snapshot.target_construction?.target_name || '-')} - ${escapeHtml(snapshot.target_construction?.phase3_warning || snapshot.target_construction?.current_implementation || '')}</td></tr>
            </tbody>
          </table>
        `;
      }
      if (leakageTarget) {
        const warnings = snapshot.leakage_checks?.warnings || [];
        leakageTarget.className = warnings.length ? '' : 'empty';
        leakageTarget.innerHTML = warnings.length
          ? `<ul>${warnings.map((item) => `<li>${escapeHtml(item)}</li>`).join('')}</ul><p><strong>Required safeguards:</strong> ${escapeHtml(snapshot.split_policy?.preprocessing || 'Fit preprocessing on training folds only')}.</p>`
          : 'No leakage warnings detected in the current snapshot metadata. Keep chronological split and fold-scoped preprocessing enforced during evaluation.';
      }
    }

    function renderModelMetrics() {
      const metrics = state.modelMetrics;
      const target = $('modelMetricsPanel');
      if (!target) return;
      if (!metrics || (!metrics.xgboost && !metrics.lstm)) {
        target.className = 'empty';
        target.textContent = 'No trained model metrics yet. Train a model to see performance metrics.';
        return;
      }
      target.className = '';
      const xgb = metrics.xgboost || {};
      const lstm = metrics.lstm || {};
      const fmt = (value, digits = 4) => value == null || Number.isNaN(Number(value)) ? '-' : Number(value).toFixed(digits);
      const pctValue = (value) => value == null || Number.isNaN(Number(value)) ? '-' : `${(Number(value) * 100).toFixed(1)}%`;
      const xgbF1 = fmt(xgb.f1_score);
      const xgbAuc = fmt(xgb.roc_auc);
      const xgbPrauc = fmt(xgb.pr_auc);
      const xgbBalanced = fmt(xgb.balanced_accuracy);
      const xgbBrier = fmt(xgb.brier_score);
      const xgbTrain = xgb.training_samples || '-';
      const xgbValidation = xgb.validation_samples || '-';
      const xgbTest = xgb.test_samples || '-';
      const xgbTrainedAt = xgb.trained_at ? new Date(xgb.trained_at).toLocaleString() : '-';
      const cvFolds = xgb.cv_fold_metrics || xgb.timeseries_cv_folds || [];
      const cvMeanF1 = fmt(xgb.cv_mean_f1);
      const cvStdF1 = fmt(xgb.cv_std_f1);
      const cvWorstF1 = fmt(xgb.cv_worst_f1);
      const cvMeanAuc = fmt(xgb.cv_mean_roc_auc);
      const cm = xgb.confusion_matrix || {};
      const targetDef = xgb.target_definition || {};
      const baselines = xgb.baseline_comparisons || xgb.baselines || {};
      const thresholdRows = (xgb.threshold_sensitivity || []).filter((row) => row.status === 'evaluated').slice(0, 8);
      const operatingRows = (xgb.validation_threshold_sensitivity || []).slice(0, 8);
      const featureRows = (xgb.feature_importance || []).slice(0, 10);
      const explainability = xgb.explainability || {};
      const shapRows = (explainability.global_shap_summary || []).slice(0, 10);
      const explainabilityLimits = explainability.limitations || [];
      const fairnessAudit = xgb.fairness_audit || {};
      const fairnessChecks = fairnessAudit.checks || [];
      const fairnessLimits = fairnessAudit.limitations || [];
      const leakageRows = xgb.leakage_risks || [];
      const preprocessingEvidence = xgb.preprocessing_evidence || {};
      const calibrationEvidence = xgb.calibration_evidence || {};
      const calibrationBins = calibrationEvidence.reliability_bins || [];
      const promotionGate = xgb.promotion_gate || {};
      const registryIdentity = xgb.registry_identity || {};

      const lstmRmse = fmt(lstm.rmse);
      const lstmMae = fmt(lstm.mae);
      const lstmSmape = lstm.smape != null ? `${Number(lstm.smape).toFixed(2)}%` : '-';
      const lstmMape = lstm.mape != null ? `${Number(lstm.mape).toFixed(2)}%` : '-';
      const lstmDirection = lstm.direction_accuracy != null ? pctValue(lstm.direction_accuracy) : '-';
      const lstmBaseRmse = fmt(lstm.baseline_rmse);
      const lstmImprove = lstm.rmse_improvement_pct != null ? `${Number(lstm.rmse_improvement_pct).toFixed(1)}%` : '-';
      const lstmTrainedAt = lstm.trained_at ? new Date(lstm.trained_at).toLocaleString() : '-';
      const lstmCvFolds = lstm.walk_forward_backtest_folds || lstm.timeseries_cv_folds || [];
      const cvMeanRmse = fmt(lstm.cv_mean_rmse);
      const cvStdRmse = fmt(lstm.cv_std_rmse);
      const cvWorstRmse = fmt(lstm.cv_worst_rmse);
      const cvMeanMae = fmt(lstm.cv_mean_mae);
      const cvMeanSmape = lstm.cv_mean_smape != null ? `${Number(lstm.cv_mean_smape).toFixed(2)}%` : '-';
      const cvWorstSmape = lstm.cv_worst_smape != null ? `${Number(lstm.cv_worst_smape).toFixed(2)}%` : '-';
      const lstmBaselines = lstm.baseline_comparisons || {};
      const lstmWarnings = lstm.readiness_warnings || [];
      const lstmGate = lstm.promotion_gate || {};

      const f1Tone = xgb.f1_score != null && xgb.f1_score >= 0.8 ? 'good' : xgb.f1_score != null && xgb.f1_score >= 0.5 ? 'warn' : 'bad';
      const aucTone = xgb.roc_auc != null && xgb.roc_auc >= 0.85 ? 'good' : xgb.roc_auc != null && xgb.roc_auc >= 0.6 ? 'warn' : 'bad';
      const rmseTone = lstm.rmse != null && lstm.rmse <= 0.12 ? 'good' : lstm.rmse != null && lstm.rmse <= 0.3 ? 'warn' : 'bad';
      const smapeTone = lstm.smape != null && lstm.smape <= 15 ? 'good' : lstm.smape != null && lstm.smape <= 30 ? 'warn' : 'bad';

      const baselineTable = Object.entries(baselines).length ? `
        <div style="margin-top:12px">
          <p><strong>Baseline comparison:</strong> candidate must beat transparent/simple baselines before promotion.</p>
          <div class="table-wrap"><table><thead><tr><th>Baseline</th><th>F1</th><th>ROC-AUC</th><th>PR-AUC</th><th>Balanced Acc.</th><th>Brier</th></tr></thead><tbody>
            ${Object.entries(baselines).map(([name, row]) => `<tr><td>${escapeHtml(name.replaceAll('_', ' '))}</td><td>${fmt(row?.f1_score ?? row?.f1)}</td><td>${fmt(row?.roc_auc)}</td><td>${fmt(row?.pr_auc)}</td><td>${fmt(row?.balanced_accuracy)}</td><td>${fmt(row?.brier_score)}</td></tr>`).join('')}
          </tbody></table></div>
        </div>` : '';

      const xgbIdentityBanner = registryIdentity.matched ? `
        <div class="candidate-identity" style="margin:8px 0 12px;padding:10px 12px;border:1px solid #cbd5e1;border-left:4px solid ${registryIdentity.lifecycle_state === 'candidate' ? '#d97706' : '#2563eb'};border-radius:6px;background:#f8fafc">
          <p style="margin:0 0 4px"><strong>Registered candidate:</strong> ${escapeHtml(registryIdentity.model_version || '-')} · ${statusBadge(registryIdentity.lifecycle_state || 'unknown', registryIdentity.lifecycle_state === 'active' ? 'good' : 'warn')}${registryIdentity.experimental_uat ? ' · ' + statusBadge('experimental UAT', 'warn') : ''}</p>
          <p style="margin:0 0 4px"><code style="font-size:11px">entry ${escapeHtml(String(registryIdentity.registry_entry_id || '-').slice(0, 18))}…</code> · dataset fingerprint <code style="font-size:11px">${escapeHtml(String(registryIdentity.dataset_fingerprint || '-').slice(0, 16))}…</code> ${registryIdentity.fingerprint_matches_metrics ? statusBadge('fingerprint matches metrics', 'good') : statusBadge('fingerprint mismatch', 'bad')}</p>
          <p style="margin:0"><small>${escapeHtml(registryIdentity.dataset_mode || 'dataset mode not recorded')}${registryIdentity.reviewed_label_snapshot_version ? ' · snapshot ' + escapeHtml(registryIdentity.reviewed_label_snapshot_version) : ''}${registryIdentity.label_provenance ? ' · ' + escapeHtml(registryIdentity.label_provenance) : ''}</small></p>
          ${registryIdentity.experimental_uat ? '<p style="margin:4px 0 0"><small><strong>Disclosure:</strong> trained on researcher-operated technical UAT labels — NOT independent expert validation. Promotion must remain blocked.</small></p>' : ''}
        </div>` : `
        <div class="candidate-identity" style="margin:8px 0 12px;padding:10px 12px;border:1px solid #fca5a5;border-left:4px solid #dc2626;border-radius:6px;background:#fef2f2">
          <p style="margin:0"><strong>No matching registry candidate.</strong> ${escapeHtml(registryIdentity.reason || 'These metrics are not linked to a registered candidate; treat as historical/unverified.')}</p>
        </div>`;

      target.innerHTML = `
        <div class="grid">
          <div class="panel span-12">
            <div class="panel-head"><h3>XGBoost Alignment Candidate</h3><small>Trained: ${escapeHtml(xgbTrainedAt)} | candidate only | ${escapeHtml(xgb.phase || 'validation')}</small></div>
            ${xgbIdentityBanner}
            <div class="metrics">
              <div class="metric"><span>F1 Score</span><strong>${statusBadge(xgbF1, f1Tone)}</strong><small>Holdout operating threshold ${fmt(xgb.operating_threshold, 2)}</small></div>
              <div class="metric"><span>ROC-AUC</span><strong>${statusBadge(xgbAuc, aucTone)}</strong><small>Probability ranking quality</small></div>
              <div class="metric"><span>PR-AUC</span><strong>${escapeHtml(xgbPrauc)}</strong><small>Imbalance-sensitive ranking</small></div>
              <div class="metric"><span>Balanced Accuracy</span><strong>${escapeHtml(xgbBalanced)}</strong><small>Class-balance corrected</small></div>
              <div class="metric"><span>Brier Score</span><strong>${escapeHtml(xgbBrier)}</strong><small>Calibration error</small></div>
              <div class="metric"><span>Target Threshold</span><strong>${fmt(targetDef.selected_target_threshold ?? xgb.threshold, 2)}</strong><small>${escapeHtml(xgb.threshold_method || 'validation selected')}</small></div>
            </div>
            <p><strong>Target definition:</strong> ${escapeHtml(targetDef.continuous_target || 'Continuous alignment score in [0,1]')} Binary classification is used only for review prioritisation. Fixed cosine 0.75 and full-dataset median thresholds are rejected as final evidence unless validated.</p>
            <p><strong>Dataset split:</strong> ${formatNumber(xgbTrain + xgbTest)} locked rows in total = ${formatNumber(xgbTrain)} non-holdout rows + ${formatNumber(xgbTest)} final holdout rows. The ${formatNumber(xgbValidation)} threshold-validation rows are a subset of the ${formatNumber(xgbTrain)} non-holdout rows; after selecting the operating threshold, all ${formatNumber(xgbTrain)} non-holdout rows are refitted into the final candidate. <strong>Promotion:</strong> ${statusBadge(promotionGate.status || 'candidate only', promotionGate.status?.includes('blocked') ? 'warn' : 'good')} ${escapeHtml(promotionGate.reason || 'Explicit approval required before promotion.')}</p>
            <div class="table-wrap"><table><thead><tr><th>TN</th><th>FP</th><th>FN</th><th>TP</th><th>Total</th><th>Expected</th><th>Check</th></tr></thead><tbody>
              <tr><td>${formatNumber(cm.true_negative || 0)}</td><td>${formatNumber(cm.false_positive || 0)}</td><td>${formatNumber(cm.false_negative || 0)}</td><td>${formatNumber(cm.true_positive || 0)}</td><td>${formatNumber(cm.total || 0)}</td><td>${formatNumber(cm.expected_total || xgbTest)}</td><td>${statusBadge(cm.denominator_check === false ? 'failed' : 'passed', cm.denominator_check === false ? 'bad' : 'good')}</td></tr>
            </tbody></table></div>
            ${baselineTable}
            ${Object.keys(calibrationEvidence).length ? `
            <div style="margin-top:12px">
              <p><strong>Holdout calibration:</strong> ${statusBadge(calibrationEvidence.status || 'not available', calibrationEvidence.status === 'passed' ? 'good' : 'warn')} ECE ${fmt(calibrationEvidence.expected_calibration_error)}, maximum gap ${fmt(calibrationEvidence.maximum_calibration_error)}, Brier ${fmt(calibrationEvidence.brier_score)}, n=${formatNumber(calibrationEvidence.sample_count || 0)}.</p>
              ${calibrationBins.length ? `<div class="table-wrap"><table><thead><tr><th>Probability bin</th><th>Rows</th><th>Mean probability</th><th>Observed positive rate</th><th>Gap</th></tr></thead><tbody>
                ${calibrationBins.map((row) => `<tr><td>${fmt(row.lower, 2)}-${fmt(row.upper, 2)}</td><td>${formatNumber(row.count)}</td><td>${fmt(row.mean_probability)}</td><td>${fmt(row.observed_positive_rate)}</td><td>${fmt(row.absolute_gap)}</td></tr>`).join('')}
              </tbody></table></div>` : ''}
            </div>` : ''}
            ${cvFolds.length ? `
            <div style="margin-top:12px">
              <p><strong>Chronological CV:</strong> Mean F1 ${escapeHtml(cvMeanF1)}, Std ${escapeHtml(cvStdF1)}, Worst ${escapeHtml(cvWorstF1)}, Mean AUC ${escapeHtml(cvMeanAuc)}</p>
              <div class="table-wrap"><table><thead><tr><th>Fold</th><th>F1</th><th>Precision</th><th>Recall</th><th>ROC-AUC</th><th>PR-AUC</th><th>Train</th><th>Test</th></tr></thead><tbody>
                ${cvFolds.map(f => `<tr><td>${f.fold}</td><td>${fmt(f.f1_score ?? f.f1)}</td><td>${fmt(f.precision)}</td><td>${fmt(f.recall)}</td><td>${fmt(f.roc_auc)}</td><td>${fmt(f.pr_auc)}</td><td>${formatNumber(f.train_size || 0)}</td><td>${formatNumber(f.test_size || 0)}</td></tr>`).join('')}
              </tbody></table></div>
            </div>` : ''}
            ${thresholdRows.length ? `
            <div style="margin-top:12px">
              <p><strong>Target threshold sensitivity:</strong> evaluated thresholds across the continuous alignment score.</p>
              <div class="table-wrap"><table><thead><tr><th>Target threshold</th><th>Positive rate</th><th>Mean F1</th><th>Std F1</th><th>Worst F1</th><th>Mean ROC-AUC</th></tr></thead><tbody>
                ${thresholdRows.map(r => `<tr><td>${fmt(r.target_threshold, 2)}</td><td>${pctValue(r.positive_rate)}</td><td>${fmt(r.mean_f1)}</td><td>${fmt(r.std_f1)}</td><td>${fmt(r.worst_f1)}</td><td>${fmt(r.mean_roc_auc)}</td></tr>`).join('')}
              </tbody></table></div>
            </div>` : ''}
            ${operatingRows.length ? `
            <div style="margin-top:12px">
              <p><strong>Operating threshold sensitivity:</strong> validation objective is ${escapeHtml(xgb.operating_threshold_objective || 'declared validation objective')}.</p>
              <div class="table-wrap"><table><thead><tr><th>Probability threshold</th><th>F1</th><th>Precision</th><th>Recall</th><th>Balanced Acc.</th></tr></thead><tbody>
                ${operatingRows.map(r => `<tr><td>${fmt(r.threshold, 2)}</td><td>${fmt(r.f1_score ?? r.f1)}</td><td>${fmt(r.precision)}</td><td>${fmt(r.recall)}</td><td>${fmt(r.balanced_accuracy)}</td></tr>`).join('')}
              </tbody></table></div>
            </div>` : ''}
            ${featureRows.length ? `<p><strong>Top feature importance:</strong> ${featureRows.map((row) => `${escapeHtml(row.feature)} (${fmt(row.importance, 3)})`).join(', ')}</p>` : ''}
            ${shapRows.length ? `
            <div style="margin-top:12px">
              <p><strong>Global SHAP summary:</strong> mean absolute contribution for this candidate.</p>
              <div class="table-wrap"><table><thead><tr><th>Feature</th><th>Mean |SHAP|</th></tr></thead><tbody>
                ${shapRows.map((row) => `<tr><td>${escapeHtml(row.feature_name || row.feature || '-')}</td><td>${fmt(row.mean_abs_shap ?? row.shap_value)}</td></tr>`).join('')}
              </tbody></table></div>
            </div>` : ''}
            <p><strong>Explainability:</strong> ${statusBadge(explainability.feature_labels_verified ? 'feature labels verified' : 'feature labels pending', explainability.feature_labels_verified ? 'good' : 'warn')} ${statusBadge(explainability.local_explanations_available ? 'local explanations available' : 'local explanations limited', explainability.local_explanations_available ? 'good' : 'warn')}</p>
            ${explainabilityLimits.length ? `<p><strong>Explainability limits:</strong> ${explainabilityLimits.map((item) => escapeHtml(item)).join(' | ')}</p>` : ''}
            <div style="margin-top:12px">
              <p><strong>Fairness / subgroup assessment:</strong> ${statusBadge(fairnessAudit.status || 'not available', fairnessAudit.status === 'passed' ? 'good' : 'warn')} ${escapeHtml(fairnessAudit.assessment_type || 'contextual subgroup monitoring')}</p>
              <p>Groups used: ${escapeHtml((fairnessAudit.groups_used || []).join(', ') || 'none')} — protected attribute assessment: ${escapeHtml(fairnessAudit.protected_attribute_assessment || 'not available')}.</p>
              ${fairnessChecks.length ? `<div class="table-wrap"><table><thead><tr><th>Group A</th><th>Group B</th><th>Rate A</th><th>Rate B</th><th>Difference</th><th>Status</th></tr></thead><tbody>
                ${fairnessChecks.slice(0, 8).map((row) => `<tr><td>${escapeHtml(row.group_a_label || '-')}</td><td>${escapeHtml(row.group_b_label || '-')}</td><td>${fmt(row.group_a_rate)}</td><td>${fmt(row.group_b_rate)}</td><td>${fmt(row.disparity)}</td><td>${statusBadge(row.passed ? 'ok' : 'review', row.passed ? 'good' : 'warn')}</td></tr>`).join('')}
              </tbody></table></div>` : ''}
              ${fairnessLimits.length ? `<p><strong>Fairness limits:</strong> ${fairnessLimits.map((item) => escapeHtml(item)).join(' | ')}</p>` : ''}
            </div>
            ${Object.keys(preprocessingEvidence).length ? `<p><strong>Preprocessing isolation:</strong> ${escapeHtml(preprocessingEvidence.cross_validation || '-')} · holdout fit rows ${formatNumber(preprocessingEvidence.holdout_rows_used_during_fit || 0)} · transform-only ${escapeHtml(String(preprocessingEvidence.holdout_transform_only === true))}</p>` : ''}
            ${leakageRows.length ? `<p><strong>Leakage / validity warnings:</strong> ${leakageRows.map((item) => escapeHtml(item)).join(' | ')}</p>` : ''}
          </div>
          <div class="panel span-12">
            <div class="panel-head"><h3>LSTM Forecast Candidate</h3><small>Trained: ${escapeHtml(lstmTrainedAt)} | ${escapeHtml(lstm.maturity_status || 'experimental')} | v${escapeHtml(lstm.model_version || '-')}</small></div>
            <div class="metrics">
              <div class="metric"><span>RMSE</span><strong>${statusBadge(lstmRmse, rmseTone)}</strong><small>Holdout error</small></div>
              <div class="metric"><span>MAE</span><strong>${escapeHtml(lstmMae)}</strong><small>Mean absolute error</small></div>
              <div class="metric"><span>SMAPE</span><strong>${statusBadge(lstmSmape, smapeTone)}</strong><small>Safe around zero values</small></div>
              <div class="metric"><span>MAPE</span><strong>${escapeHtml(lstmMape)}</strong><small>Only non-zero actuals</small></div>
              <div class="metric"><span>Direction</span><strong>${escapeHtml(lstmDirection)}</strong><small>Trend direction accuracy</small></div>
              <div class="metric"><span>Best Baseline</span><strong>${escapeHtml(lstm.best_baseline || '-')}</strong><small>RMSE ${escapeHtml(lstmBaseRmse)}, improvement ${escapeHtml(lstmImprove)}</small></div>
            </div>
            <p><strong>Forecast setup:</strong> horizon ${formatNumber(lstm.forecast_horizon || 1)}, sequence length ${formatNumber(lstm.sequence_length || 0)}. ${escapeHtml(lstm.scaling_policy || 'Scaling policy not recorded.')}</p>
            <p><strong>Promotion:</strong> ${statusBadge(lstmGate.status || 'candidate only', lstmGate.status?.includes('blocked') ? 'warn' : 'good')} ${escapeHtml(lstmGate.reason || 'Explicit approval required before promotion.')}</p>
            ${Object.entries(lstmBaselines).length ? `
            <div style="margin-top:12px">
              <p><strong>Forecast baselines:</strong> LSTM must beat transparent statistical baselines before it can be considered for promotion.</p>
              <div class="table-wrap"><table><thead><tr><th>Baseline</th><th>RMSE</th><th>MAE</th><th>SMAPE</th><th>MAPE</th><th>Direction</th></tr></thead><tbody>
                ${Object.entries(lstmBaselines).map(([name, row]) => `<tr><td>${escapeHtml(name.replaceAll('_', ' '))}</td><td>${fmt(row?.rmse)}</td><td>${fmt(row?.mae)}</td><td>${row?.smape != null ? Number(row.smape).toFixed(2) + '%' : '-'}</td><td>${row?.mape != null ? Number(row.mape).toFixed(2) + '%' : '-'}</td><td>${row?.direction_accuracy != null ? pctValue(row.direction_accuracy) : '-'}</td></tr>`).join('')}
              </tbody></table></div>
            </div>` : ''}
            ${lstmCvFolds.length ? `
            <div style="margin-top:12px">
              <p><strong>Walk-forward backtesting (${lstmCvFolds.length} folds):</strong> Mean RMSE ${escapeHtml(cvMeanRmse)}, Std ${escapeHtml(cvStdRmse)}, Worst RMSE ${escapeHtml(cvWorstRmse)}, Mean MAE ${escapeHtml(cvMeanMae)}, Mean SMAPE ${escapeHtml(cvMeanSmape)}, Worst SMAPE ${escapeHtml(cvWorstSmape)}</p>
              <div class="table-wrap"><table><thead><tr><th>Fold</th><th>RMSE</th><th>MAE</th><th>SMAPE</th><th>MAPE</th><th>Direction</th><th>Train</th><th>Test</th></tr></thead><tbody>
                ${lstmCvFolds.map(f => `<tr><td>${f.fold}</td><td>${fmt(f.rmse)}</td><td>${fmt(f.mae)}</td><td>${f.smape != null ? Number(f.smape).toFixed(2) + '%' : '-'}</td><td>${f.mape != null ? Number(f.mape).toFixed(2) + '%' : '-'}</td><td>${f.direction_accuracy != null ? pctValue(f.direction_accuracy) : '-'}</td><td>${formatNumber(f.train_size || 0)}</td><td>${formatNumber(f.test_size || 0)}</td></tr>`).join('')}
              </tbody></table></div>
            </div>` : ''}
            ${lstmWarnings.length ? `<p><strong>Readiness warnings:</strong> ${lstmWarnings.map((item) => escapeHtml(item)).join(' | ')}</p>` : ''}
          </div>
        </div>
      `;
    }


    function renderModelRegistry() {
      const panel = $('modelRegistryPanel');
      const gatesPanel = $('promotionGatesPanel');
      if (!panel) return;
      const entries = state.modelRegistryEntries || [];
      if (!entries.length) {
        panel.className = 'empty';
        panel.textContent = 'No model registry entries have been recorded yet. Train a candidate to create one.';
        if (gatesPanel) gatesPanel.innerHTML = '<div class="promo-gate pending"><span class="gate-icon">●</span> Select a model candidate to inspect promotion gates.</div>';
        return;
      }
      panel.className = '';
      panel.innerHTML = `
        <div class="table-wrap"><table><thead><tr><th>Model</th><th>Version</th><th>State</th><th>Fingerprint</th><th>Trained</th><th>Actions</th></tr></thead><tbody>
          ${entries.map((entry) => {
            const selected = state.selectedModelRegistryEntry?.entry_id === entry.entry_id;
            return `<tr style="${selected ? 'background:#eff6ff' : ''}"><td>${escapeHtml(entry.model_type || '-')}</td><td>${escapeHtml(entry.model_version || '-')}</td><td><span class="lifecycle-badge lifecycle-${escapeHtml(entry.lifecycle_state || 'draft')}">${escapeHtml(entry.lifecycle_state || '-')}</span></td><td>${escapeHtml((entry.dataset_fingerprint || '').slice(0, 12) || '-')}</td><td>${entry.trained_at ? new Date(entry.trained_at).toLocaleString() : '-'}</td><td><button class="btn sm" data-model-registry-select="${escapeHtml(entry.entry_id)}">Select</button></td></tr>`;
          }).join('')}
        </tbody></table></div>
      `;
      panel.querySelectorAll('[data-model-registry-select]').forEach((button) => {
        button.addEventListener('click', () => {
          state.selectedModelRegistryEntry = entries.find((entry) => entry.entry_id === button.dataset.modelRegistrySelect) || null;
          renderModelRegistry();
        });
      });

      const selected = state.selectedModelRegistryEntry || entries[0];
      if (!state.selectedModelRegistryEntry) state.selectedModelRegistryEntry = selected;
      const gates = selected.promotion_gates || {};
      if (gatesPanel) {
        const gatesNotChecked = gates.status === 'not_checked' && !Object.values(gates).some((value) => value && typeof value === 'object');
        const gateEntries = gatesNotChecked ? [] : Object.entries(gates).filter(([, value]) => value && typeof value === 'object');
        gatesPanel.innerHTML = gateEntries.length
          ? gateEntries.map(([name, gate]) => `<div class="promo-gate ${gate.passed ? 'passed' : 'failed'}"><span class="gate-icon">${gate.passed ? '✓' : '!'}</span><div><strong>${escapeHtml(name.replaceAll('_', ' '))}</strong><br><small>${escapeHtml(gate.message || '')}</small></div></div>`).join('')
          : `<div class="promo-gate pending"><span class="gate-icon">●</span><div><strong>Gates not checked</strong><br><small>${escapeHtml(gates.message || 'Select Check Gates to calculate promotion readiness.')}</small></div></div>`;
      }
      const checkBtn = $('checkModelGatesBtn');
      const testsBtn = $('recordModelTestsBtn');
      const evaluateBtn = $('evaluateModelBtn');
      const approveBtn = $('approveModelBtn');
      const promoteBtn = $('promoteModelBtn');
      const rejectBtn = $('rejectModelBtn');
      const rollbackBtn = $('rollbackModelBtn');
      if (checkBtn) checkBtn.disabled = !['candidate', 'evaluated', 'approved'].includes(selected.lifecycle_state);
      if (testsBtn) testsBtn.disabled = !['candidate', 'evaluated'].includes(selected.lifecycle_state);
      if (evaluateBtn) evaluateBtn.disabled = selected.lifecycle_state !== 'candidate';
      if (approveBtn) approveBtn.disabled = selected.lifecycle_state !== 'evaluated';
      if (promoteBtn) promoteBtn.disabled = !(selected.lifecycle_state === 'approved');
      if (rejectBtn) rejectBtn.disabled = !['candidate', 'evaluated', 'approved'].includes(selected.lifecycle_state);
      if (rollbackBtn) rollbackBtn.disabled = !selected.model_type;
      const status = $('promotionStatus');
      if (status) {
        status.innerHTML = `<strong>Selected:</strong> ${escapeHtml(selected.model_type)} ${escapeHtml(selected.model_version)} — ${statusBadge(selected.lifecycle_state || 'unknown', selected.lifecycle_state === 'active' ? 'good' : selected.lifecycle_state === 'rejected' ? 'bad' : 'warn')}`;
      }
    }


async function renderAdzunaTrialOutlook() {
      const target = $('adzunaTrialOutlookPanel');
      if (!target) return;
      try {
        const data = await getJson(API_ENDPOINTS.LABOUR_MARKET.SKILL_PIPELINE_TRIAL_SIGNALS, { signals: [] });
        const signals = Array.isArray(data.signals) ? data.signals : [];
        if (!signals.length) {
          target.className = 'empty';
          target.textContent = 'No labour demand signals yet. Run the Labour-market Skill Pipeline, review mappings in Skills Alignment, then generate labour demand signals.';
          return;
        }
        const count = Number(data.total_signal_count || signals.length);
        target.className = '';
        const sourceLabelFor = (label) => (label === 'ADZUNA_TRIAL_NOT_EMPIRICAL' ? 'Adzuna' : label);
        target.innerHTML = `
          <p class="muted" style="margin-bottom:8px"><strong>${count}</strong> labour demand signals generated from approved mappings on imported job-posting evidence.</p>
          <div class="table-wrap">
            <table>
              <thead><tr><th>Skill name</th><th>Demand value</th><th>Period</th><th>Source</th><th>Evidence count</th><th>Unit</th></tr></thead>
              <tbody>
                ${signals.map((item) => `<tr>
                  <td><strong>${escapeHtml(item.skill_name || '-')}</strong></td>
                  <td>${formatNumber(item.normalised_value ?? item.demand_value ?? 0)}</td>
                  <td>${escapeHtml(item.period || '-')}</td>
                  <td><small>${escapeHtml(Object.keys(item.source_counts || {}).map(sourceLabelFor).join(', ') || '-')}</small></td>
                  <td>${formatNumber(item.evidence_count || 0)}</td>
                  <td><small>${escapeHtml(item.unit || '-')}${item.normalised_from_legacy_unit ? ` <span class="muted" title="Display unit normalised from legacy source unit '${escapeHtml(item.raw_unit || '')}'; source/licence provenance retained in the evidence dossier">(normalised)</span>` : ''}</small></td>
                </tr>`).join('')}
              </tbody>
            </table>
          </div>
          <p class="muted" style="margin-top:8px;font-size:12px;color:#526985">Adzuna South Africa data used under written academic research permission. Source: <a href="https://www.adzuna.co.za" target="_blank" rel="noopener">https://www.adzuna.co.za</a></p>`;
      } catch (error) {
        target.className = 'empty';
        target.textContent = `Unable to load labour demand signals: ${error.message}`;
      }
    }


    window.addEventListener('labour-signals-updated', () => {
      if ($('adzunaTrialOutlookPanel')) renderAdzunaTrialOutlook();
    });


    export { renderExecutive, renderCurriculum, renderSkills, renderForecasts, renderForecastQuality, renderIngestionQuality, qualityMetric, renderSkillsValidity, renderIngestionDataQuality, renderGovernance, renderReports, renderRecommendationRows, renderRecommendationDossier, renderCurriculumRows, renderCurriculumJobs, renderSkillMappingRows, renderSkillGapRows, evidenceCard, renderSkillGapEvidence, renderForecastRows, openForecastExplanation, closeForecastExplanation, renderGovernanceRows, renderQualityJobRows, renderIngestionBlueprintRows, renderConnectorCatalogRows, renderNormaliserRows, renderQualityContractRows, renderSourceConnectorRows, renderFailureRows, renderPipelineRunRows, renderQualityCheckRows, renderProcessingPhase, renderOperationalJobRows, renderContractOps, reviewSourceCategory, renderReviewRecordRows, renderLineageSummary, renderModelReadiness, renderSecurityReadiness, renderDeploymentReadiness, renderPortalUat, renderConnectorOps, renderModelDatasetSnapshot, renderModelMetrics, renderModelRegistry, renderAdzunaTrialOutlook };


