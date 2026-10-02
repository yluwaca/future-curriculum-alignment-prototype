// dashboard-actions.js - All async action handlers
import { $, showToast, showSpinner, hideSpinner, renderPagination, renderKeyValueRows, renderBars, renderEmpty, formatNumber, percent, escapeHtml, statusBadge, statusTone, priorityTone, skillName, countBy, average, formatFileSize, toCsv, download, showConfirm, setupSearch } from './dashboard-utils.js?v=20260825b';
import { state, titles, setStatus, clearStatus, getJson, postJson, postForm, resetPages, renderAll, renderUser, actions } from './dashboard-state.js?v=20260921-registry1';
import { API_ENDPOINTS } from './config.js?v=20260920-assisted1';
import { auth } from './auth.js';
import { renderSidebar, setNavigationUser } from './shared-nav.js';
import { renderExecutive, renderCurriculum, renderSkills, renderForecasts, renderForecastQuality, renderIngestionQuality, qualityMetric, renderSkillsValidity, renderIngestionDataQuality, renderGovernance, renderReports, renderRecommendationRows, renderRecommendationDossier, renderCurriculumRows, renderCurriculumJobs, renderSkillMappingRows, renderSkillGapRows, evidenceCard, renderSkillGapEvidence, renderForecastRows, renderGovernanceRows, renderQualityJobRows, renderIngestionBlueprintRows, renderConnectorCatalogRows, renderNormaliserRows, renderQualityContractRows, renderSourceConnectorRows, renderFailureRows, renderPipelineRunRows, renderQualityCheckRows, renderProcessingPhase, renderOperationalJobRows, renderContractOps, reviewSourceCategory, renderReviewRecordRows, renderLineageSummary, renderModelDatasetSnapshot, renderModelMetrics, renderModelRegistry, renderSecurityReadiness, renderDeploymentReadiness, renderPortalUat } from './dashboard-views.js?v=20260921-registry1';


    const SKILLS_BASE = API_ENDPOINTS.SKILLS.GOVERNANCE_WORKBENCH.replace('/governance/workbench', '');

    function asItems(payload) {
      if (Array.isArray(payload)) return payload;
      if (Array.isArray(payload?.items)) return payload.items;
      if (Array.isArray(payload?.jobs)) return payload.jobs;
      if (Array.isArray(payload?.sources)) return payload.sources;
      if (Array.isArray(payload?.contracts)) return payload.contracts;
      if (Array.isArray(payload?.failures)) return payload.failures;
      if (Array.isArray(payload?.connectors)) return payload.connectors;
      if (Array.isArray(payload?.normalisers)) return payload.normalisers;
      return [];
    }

    async function trainModel(modelType) {
      const usesReviewedLabelSnapshot = modelType === 'xgboost';
      const snapshotType = String(state.modelDatasetSnapshot?.model_type || '').toLowerCase();
      const hasCompatibleSnapshot = usesReviewedLabelSnapshot
        ? Boolean(state.alignmentLabelSnapshot)
        : Boolean(state.modelDatasetSnapshot)
          && (snapshotType === 'general' || snapshotType === modelType);
      if (!hasCompatibleSnapshot) {
        const message = `Create a reproducible ${modelType.toUpperCase()}-compatible dataset snapshot before starting candidate training.`;
        showToast(message, 'error');
        setStatus(message, 'error');
        return;
      }
      if (usesReviewedLabelSnapshot && !state.alignmentLabelSnapshot) {
        const message = 'XGBoost needs a locked independently reviewed label dataset. Complete and lock expert reviews in Data Operations first.';
        showToast(message, 'error');
        setStatus(message, 'error');
        return;
      }
      const spinnerId = modelType === 'xgboost' ? 'xgboostSpinner' : 'lstmSpinner';
      const lastTrainedId = modelType === 'xgboost' ? 'xgboostLastTrained' : 'lstmLastTrained';
      const btnId = modelType === 'xgboost' ? 'trainXgboostBtn' : 'trainLstmBtn';
      const endpoint = modelType === 'xgboost' ? API_ENDPOINTS.PREDICTIVE.TRAIN_XGBOOST : API_ENDPOINTS.PREDICTIVE.TRAIN_LSTM;
      const btn = $(btnId);
      showSpinner(spinnerId);
      if (btn) btn.disabled = true;
      try {
        const result = await postJson(endpoint, {});
        const operationalJob = result.operational_job || null;
        await refreshOperationalJobs();
        startIngestionMonitor();
        const message = result.coalesced
          ? `An equivalent ${modelType.toUpperCase()} candidate job is already active.`
          : `${modelType.toUpperCase()} candidate training accepted as job ${String(operationalJob?.job_id || 'queued').slice(0, 8)}.`;
        showToast(message, 'ok');
        setStatus(`${message} Training will continue if Model Lab is closed.`, 'ok');
      } catch (error) {
        showToast(`${modelType.toUpperCase()} training failed: ${error.message || 'API error'}`, 'error');
      } finally {
        hideSpinner(spinnerId);
        if (btn) {
          const currentSnapshotType = String(state.modelDatasetSnapshot?.model_type || '').toLowerCase();
          const compatible = modelType === 'xgboost'
            ? Boolean(state.alignmentLabelSnapshot)
            : Boolean(state.modelDatasetSnapshot)
              && (currentSnapshotType === 'general' || currentSnapshotType === modelType);
          btn.disabled = !compatible;
        }
      }
    }

    async function loadDashboard() {
      setStatus('Loading dashboard data...');
      try {
        state.user = await getJson(API_ENDPOINTS.AUTH.ME, null);
        setNavigationUser(state.user);
        renderSidebar(window.FUTURE_DEFAULT_VIEW || 'executive');
        const dashboardRoles = (state.user?.roles || []).map((role) =>
          String(role).toLowerCase().replaceAll(' ', '_')
        );
        const canUseModelLab = Boolean(state.user?.is_admin)
          || dashboardRoles.includes('admin')
          || dashboardRoles.includes('administrator')
          || dashboardRoles.includes('data_scientist');
        // Render the shell immediately so a slow operational endpoint never
        // leaves the portal looking frozen.
        renderAll();
        setStatus('Loading live dashboard data (0/22)...');
        if ($('operationalJobRows')) {
          const operational = await getJson(
            `${API_ENDPOINTS.OPERATIONS.JOBS}?limit=50`,
            { jobs: [] },
          );
          state.operationalJobs = operational.jobs || [];
        }
        if ($('subjectProfileValidationRows')) {
          await loadSubjectProfiles(false);
        }
        if ($('curriculumEvidenceReviewRows')) {
          state.curriculumEvidenceReviews = await getJson(
            API_ENDPOINTS.CURRICULUM.EVIDENCE_REVIEW_QUEUE,
            { items: [], counts: {} },
          );
        }
        if ($('curriculumGovernanceRows')) {
          await loadCurriculumGovernanceChain();
        }
        if ($('skillMappingReviewRows')) {
          state.skillMappingWorkbench = await getJson(
            API_ENDPOINTS.SKILLS.GOVERNANCE_WORKBENCH,
            { readiness: { counts: {}, coverage: {}, issues: [] }, review_queue: [] },
          );
        }
        if ($('alignmentLabelTaskRows') || $('xgboostDatasetReadiness')) {
          if ($('alignmentLabelTaskRows')) {
            state.alignmentLabelQueue = await getJson(
              API_ENDPOINTS.ALIGNMENT_LABELS.TASKS,
              { items: [], total_tasks: 0, total_labels: 0, status_counts: {} },
            );
          }
          const labelSnapshot = await getJson(
            API_ENDPOINTS.ALIGNMENT_LABELS.LATEST_SNAPSHOT,
            { latest: null },
          );
          state.alignmentLabelSnapshot = labelSnapshot.latest || null;
          if ($('xgboostDatasetReadiness')) {
            await loadXgboostTrainReadiness();
          } else {
            renderXgboostDatasetReadiness();
          }
        }
        if ($('validatedRegenerationReadiness')) {
          state.validatedRegenerationReadiness = await getJson(
            API_ENDPOINTS.PROCESSING.VALIDATED_REGENERATION_READINESS,
            null,
            60000,
          );
          renderValidatedRegenerationReadiness();
        }

        let loadedDashboardRequests = 0;
        const trackedGet = (url, fallback) => getJson(url, fallback, 60000)
          .catch((error) => {
            console.warn('Dashboard request skipped', url, error);
            return fallback;
          })
          .finally(() => {
            loadedDashboardRequests += 1;
            setStatus(`Loading live dashboard data (${loadedDashboardRequests}/22)...`);
          });
        const batch1 = await Promise.all([
          trackedGet(API_ENDPOINTS.CURRICULUM.DOCUMENTS, []),
          trackedGet(API_ENDPOINTS.CURRICULUM.HIERARCHY, { faculties: [], departments: [], programmes: [], modules: [] }),
          trackedGet(API_ENDPOINTS.CURRICULUM.QUALITY_SUMMARY, null),
          trackedGet(API_ENDPOINTS.SKILLS.SUMMARY, {}),
          trackedGet(`${API_ENDPOINTS.SKILLS.LIST}?limit=200`, []),
          trackedGet(`${API_ENDPOINTS.SKILLS.MAPPINGS}?limit=100`, []),
          trackedGet(API_ENDPOINTS.ANALYTICS.SUMMARY, {}),
          trackedGet(`${API_ENDPOINTS.ANALYTICS.ALIGNMENT_SCORES}?limit=10`, []),
          trackedGet(`${API_ENDPOINTS.ANALYTICS.SKILL_GAPS}?limit=8`, { gaps: [] }),
          trackedGet(`${API_ENDPOINTS.ANALYTICS.FORECASTS}?limit=100`, []),
          trackedGet(`${API_ENDPOINTS.ANALYTICS.RECOMMENDATIONS}?limit=100`, []),
          trackedGet(`${API_ENDPOINTS.ANALYTICS.REPORTS}?limit=50`, []),
          trackedGet(`${API_ENDPOINTS.PIPELINE.RUNS}?limit=10`, []),
          trackedGet(API_ENDPOINTS.INGESTION.CONNECTORS, []),
          trackedGet(API_ENDPOINTS.INGESTION.NORMALISERS, []),
          trackedGet(API_ENDPOINTS.INGESTION.SOURCES, []),
          trackedGet(API_ENDPOINTS.INGESTION.JOBS, []),
          trackedGet(API_ENDPOINTS.INGESTION.CONTRACTS, []),
          trackedGet(API_ENDPOINTS.INGESTION.FAILURES, []),
          trackedGet(API_ENDPOINTS.INGESTION.OPERATIONS_SUMMARY, null),
          trackedGet(API_ENDPOINTS.LABOUR_MARKET.TRENDS_SUMMARY, {}),
          trackedGet(API_ENDPOINTS.SEMANTIC.VECTOR_STATUS, null),
          trackedGet(API_ENDPOINTS.PROCESSING.SUMMARY, null),
        ]);
        [state.documents, state.curriculumHierarchy, state.curriculumQuality, state.skillsSummary, state.skills, state.skillMappings,
         state.analyticsSummary, state.alignmentScores, state.skillGapSummary,
         state.forecasts, state.recommendations, state.generatedReports,
         state.pipelineRuns, state.connectorDefinitions, state.normaliserDefinitions,
         state.ingestionSources, state.ingestionJobs, state.ingestionContracts,
         state.ingestionFailures, state.ingestionOperationsSummary, state.labourTrendSummary, state.vectorStatus,
         state.processingSummary] = batch1;

        // Core dashboard values are now usable. Do not let optional detail
        // requests keep Data Operations stuck on a loading message.
        renderAll();
        if ($('operationalJobRows')) renderOperationalJobRows();
        if ($('subjectProfileValidationRows')) renderSubjectProfileValidationRows();
        if ($('curriculumEvidenceReviewRows')) renderCurriculumEvidenceReviewQueue();
        if ($('skillMappingReviewRows')) renderSkillMappingWorkbench();
        if ($('alignmentLabelTaskRows')) renderAlignmentLabelQueue();
        setStatus('Core dashboard loaded. Loading evidence details...', 'ok');

        const optionalDetailTasks = [];
        if (state.documents?.length) {
          optionalDetailTasks.push(Promise.all(
            state.documents.slice(0, 25).map((doc) => getJson(
              API_ENDPOINTS.CURRICULUM.DOCUMENT_DETAIL(doc.document_id),
              null,
              30000,
            ))
          ).then((details) => { state.documentDetails = details; }));
        }
        optionalDetailTasks.push(loadGovernanceDetails().catch((error) => console.warn('Governance details skipped', error)));
        optionalDetailTasks.push(loadQualitySummaries().catch((error) => console.warn('Quality summaries skipped', error)));
        await Promise.allSettled(optionalDetailTasks);
        renderAll();
        if ($('operationalJobRows')) renderOperationalJobRows();
        if ($('subjectProfileValidationRows')) renderSubjectProfileValidationRows();
        if ($('curriculumEvidenceReviewRows')) renderCurriculumEvidenceReviewQueue();
        if ($('skillMappingReviewRows')) renderSkillMappingWorkbench();
        if ($('alignmentLabelTaskRows')) renderAlignmentLabelQueue();
        clearStatus();

        state.modelReadiness = await getJson(API_ENDPOINTS.PREDICTIVE.MODEL_READINESS, null, 60000);
        state.modelMetrics = await getJson(API_ENDPOINTS.PREDICTIVE.MODEL_METRICS, null, 60000);
        if (canUseModelLab) {
          const latestSnapshot = await getJson(API_ENDPOINTS.PREDICTIVE.DATASET_SNAPSHOT_LATEST, { latest: null }, 60000);
          state.modelDatasetSnapshot = latestSnapshot.latest || null;
          const registry = await getJson(
            `${API_ENDPOINTS.PREDICTIVE.MODEL_REGISTRY}?_=${Date.now()}`,
            { entries: [] },
            60000,
          );
          state.modelRegistryEntries = registry.entries || [];
          if (state.modelRegistryEntries.length) {
            const currentId = state.selectedModelRegistryEntry?.entry_id;
            state.selectedModelRegistryEntry = state.modelRegistryEntries.find((entry) => entry.entry_id === currentId) || state.modelRegistryEntries[0];
          } else {
            state.selectedModelRegistryEntry = null;
          }
          if ($('modelRuntimeContinuityPanel')) {
            state.modelRuntimeContinuity = await getJson(
              API_ENDPOINTS.PREDICTIVE.MODEL_RUNTIME_CONTINUITY,
              null,
              60000,
            );
            renderModelRuntimeContinuity();
          }
        } else {
          state.modelDatasetSnapshot = null;
          state.modelRegistryEntries = [];
          state.selectedModelRegistryEntry = null;
          state.modelRuntimeContinuity = null;
        }
        state.forecastQuality = await getJson(API_ENDPOINTS.PREDICTIVE.FORECAST_QUALITY, null, 60000);
        const recGrouped = await getJson(`${API_ENDPOINTS.ANALYTICS.RECOMMENDATIONS_GROUPED}?status=pending_review&limit=50`, { groups: [] });
        state.recommendationGroups = recGrouped.groups || recGrouped;
        state.skillsValidity = await getJson(API_ENDPOINTS.SKILLS.SKILLS_READINESS, null, 60000);
        state.alignmentCalibration = await getJson(API_ENDPOINTS.SKILLS.ALIGNMENT_CALIBRATION, null, 60000);
        hideSpinner('spinnerSkillsValidity');
        renderSkillsValidity();
        if ($('forecast')) renderForecasts();
        if ($('modelLab')) {
          renderModelDatasetSnapshot();
          renderModelMetrics();
          renderModelRegistry();
        }
      } catch (error) {
        console.error('Dashboard load error:', error);
        console.error('Stack:', error?.stack);
        console.error('State snapshot:', JSON.stringify({
          docs: state.documents?.length,
          recs: state.recommendations?.length,
          skills: state.skills?.length,
          jobs: state.ingestionJobs?.length,
          forecasts: state.forecasts?.length,
        }));
        setStatus(`Dashboard error: ${error?.message || error} - check browser console (F12) for details.`, 'error');
      }
    }

    async function loadGovernanceDetails() {
      const targets = [...state.recommendations]
        .sort((a, b) => new Date(b.updated_at || b.created_at || 0) - new Date(a.updated_at || a.created_at || 0))
        .slice(0, 24);
      const bundles = await Promise.all(targets.map(async (item) => ({
        reviews: await getJson(API_ENDPOINTS.ANALYTICS.RECOMMENDATION_REVIEWS(item.recommendation_id), []),
        feedback: await getJson(API_ENDPOINTS.ANALYTICS.RECOMMENDATION_FEEDBACK(item.recommendation_id), []),
        history: await getJson(API_ENDPOINTS.ANALYTICS.RECOMMENDATION_STATUS_HISTORY(item.recommendation_id), []),
      })));
      const newestFirst = (items) => items.sort((a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0));
      state.recommendationReviews = newestFirst(bundles.flatMap((item) => item.reviews));
      state.recommendationFeedback = newestFirst(bundles.flatMap((item) => item.feedback));
      state.recommendationHistory = newestFirst(bundles.flatMap((item) => item.history));
    }

    async function loadQualitySummaries() {
      const targets = state.ingestionJobs.slice(0, 10);
      const summaries = {};
      const results = await Promise.all(targets.map(async (job) => ({
        job,
        summary: await getJson(API_ENDPOINTS.INGESTION.QUALITY_SUMMARY(job.job_id), {
          job_id: job.job_id,
          checks: {},
          cleaned_records: {},
          average_quality_score: null,
        }),
      })));
      for (const result of results) {
        summaries[result.job.job_id] = result.summary;
      }
      state.qualitySummaries = summaries;
      const checkedJob = targets.find((job) => Object.keys(summaries[job.job_id]?.checks || {}).length > 0);
      state.qualityChecks = checkedJob
        ? await getJson(API_ENDPOINTS.INGESTION.QUALITY_CHECKS(checkedJob.job_id), [])
        : [];
      const qualityCheckCaption = $('qualityCheckCaption');
      if (qualityCheckCaption) qualityCheckCaption.textContent = checkedJob ? `Latest checks for ${checkedJob.job_type}` : 'No checked job selected';
    }


    async function createDatasetSnapshot() {
      setStatus('Creating reproducible dataset snapshot...');
      try {
        const snapshot = await postJson(`${API_ENDPOINTS.PREDICTIVE.DATASET_SNAPSHOTS}?model_type=general`, {});
        state.modelDatasetSnapshot = snapshot;
        renderModelDatasetSnapshot();
        setStatus(`Dataset snapshot created: ${String(snapshot.dataset_fingerprint || '').slice(0, 12)}`, 'ok');
        showToast('Dataset snapshot created.', 'ok');
      } catch (error) {
        console.error(error);
        setStatus(`Dataset snapshot could not be created. ${error.message || 'Check API logs.'}`, 'error');
      }
    }



    async function refreshModelRegistry(message = 'Model registry refreshed.') {
      setStatus('Loading model registry...');
      try {
        const registryUrl = `${API_ENDPOINTS.PREDICTIVE.MODEL_REGISTRY}?_=${Date.now()}`;
        const registry = await getJson(registryUrl, { entries: [] }, 60000);
        state.modelRegistryEntries = registry.entries || [];
        state.modelMetrics = await getJson(API_ENDPOINTS.PREDICTIVE.MODEL_METRICS, state.modelMetrics, 60000);
        state.modelReadiness = await getJson(API_ENDPOINTS.PREDICTIVE.MODEL_READINESS, state.modelReadiness, 60000);
        renderModelMetrics();
        if ($('forecast')) {
          renderForecasts();
        } else {
          const xgbTs = state.modelMetrics?.xgboost?.trained_at || state.modelReadiness?.xgboost_last_trained;
          const lstmTs = state.modelMetrics?.lstm?.trained_at || state.modelReadiness?.lstm_last_trained;
          if ($('xgboostLastTrained') && xgbTs) $('xgboostLastTrained').textContent = `Last trained: ${new Date(xgbTs).toLocaleString()}`;
          if ($('lstmLastTrained') && lstmTs) $('lstmLastTrained').textContent = `Last trained: ${new Date(lstmTs).toLocaleString()}`;
        }
        const currentId = state.selectedModelRegistryEntry?.entry_id;
        state.selectedModelRegistryEntry = state.modelRegistryEntries.find((entry) => entry.entry_id === currentId) || state.modelRegistryEntries[0] || null;
        renderModelRegistry();
        if ($('modelRuntimeContinuityPanel')) {
          state.modelRuntimeContinuity = await getJson(
            API_ENDPOINTS.PREDICTIVE.MODEL_RUNTIME_CONTINUITY,
            null,
            60000,
          );
          renderModelRuntimeContinuity();
        }
        setStatus(`${message} (${Number(registry.count ?? state.modelRegistryEntries.length)} entries received; ${state.modelRegistryEntries.length} rendered)`, 'ok');
      } catch (error) {
        console.error(error);
        setStatus('Model registry could not be loaded.', 'error');
      }
    }

    function selectedRegistryEntry() {
      const entry = state.selectedModelRegistryEntry;
      if (!entry) {
        showToast('Select a model registry entry first.', 'error');
        return null;
      }
      return entry;
    }

    async function checkSelectedModelGates() {
      const entry = selectedRegistryEntry();
      if (!entry) return;
      setStatus('Checking promotion gates...');
      try {
        const result = await postJson(API_ENDPOINTS.PREDICTIVE.MODEL_REGISTRY_GATES(entry.entry_id), {});
        const updated = result.entry || { ...entry, promotion_gates: result.gates };
        state.selectedModelRegistryEntry = updated.entry_id ? updated : { ...entry, promotion_gates: result.gates };
        await refreshModelRegistry(`Promotion gates checked. ${result.can_promote ? 'Candidate is promotable after approval.' : 'Some gates still need attention.'}`);
      } catch (error) {
        console.error(error);
        setStatus('Promotion gates could not be checked.', 'error');
      }
    }

    async function recordSelectedModelTestEvidence() {
      const entry = selectedRegistryEntry();
      if (!entry) return;
      const ok = await showConfirm('Record automated tests as passed for this selected candidate? Only do this after the focused backend/frontend validation has been run.');
      if (!ok) return;
      setStatus('Recording automated test evidence...');
      try {
        await postJson(API_ENDPOINTS.PREDICTIVE.MODEL_REGISTRY_TEST_EVIDENCE(entry.entry_id), {
          status: 'passed',
          summary: 'Focused Phase 7 validation recorded from Model Lab.',
          details: { source: 'model_lab_portal' },
        });
        await refreshModelRegistry('Automated test evidence recorded.');
      } catch (error) {
        console.error(error);
        setStatus('Automated test evidence could not be recorded.', 'error');
      }
    }

    async function evaluateSelectedModel() {
      const entry = selectedRegistryEntry();
      if (!entry) return;
      setStatus('Marking model as evaluated...');
      try {
        await postJson(API_ENDPOINTS.PREDICTIVE.MODEL_REGISTRY_EVALUATE(entry.entry_id), {});
        await refreshModelRegistry('Candidate marked as evaluated.');
      } catch (error) {
        console.error(error);
        setStatus('Candidate could not be marked evaluated.', 'error');
      }
    }

    async function approveSelectedModel() {
      const entry = selectedRegistryEntry();
      if (!entry) return;
      const ok = await showConfirm('Approve this evaluated candidate for promotion? This records explicit authorised approval but does not activate it yet.');
      if (!ok) return;
      setStatus('Approving model candidate...');
      try {
        await postJson(API_ENDPOINTS.PREDICTIVE.MODEL_REGISTRY_APPROVE(entry.entry_id), {});
        await refreshModelRegistry('Candidate approved. It can now be promoted to active if all gates pass.');
      } catch (error) {
        console.error(error);
        setStatus('Candidate could not be approved. Check failed gates in Model Lab.', 'error');
      }
    }

    async function promoteSelectedModel() {
      const entry = selectedRegistryEntry();
      if (!entry) return;
      const ok = await showConfirm('Promote this approved model to ACTIVE? The current active model will be retired and preserved for rollback.');
      if (!ok) return;
      setStatus('Promoting model atomically...');
      try {
        await postJson(API_ENDPOINTS.PREDICTIVE.MODEL_REGISTRY_PROMOTE(entry.entry_id), {});
        await refreshModelRegistry('Model promoted to active. Previous active version is preserved for rollback.');
      } catch (error) {
        console.error(error);
        setStatus('Model could not be promoted. Check promotion gates.', 'error');
      }
    }

    async function rejectSelectedModel() {
      const entry = selectedRegistryEntry();
      if (!entry) return;
      const reason = window.prompt('Reason for rejecting this candidate:', 'Does not satisfy promotion gates');
      if (reason === null) return;
      setStatus('Rejecting model candidate...');
      try {
        await postJson(`${API_ENDPOINTS.PREDICTIVE.MODEL_REGISTRY_REJECT(entry.entry_id)}?reason=${encodeURIComponent(reason)}`, {});
        await refreshModelRegistry('Candidate rejected and preserved in registry history.');
      } catch (error) {
        console.error(error);
        setStatus('Candidate could not be rejected.', 'error');
      }
    }

    async function rollbackSelectedModel() {
      const entry = selectedRegistryEntry();
      if (!entry?.model_type) return;
      const ok = await showConfirm(`Rollback active ${entry.model_type} model to the previous retired version?`);
      if (!ok) return;
      setStatus('Rolling back active model...');
      try {
        await postJson(API_ENDPOINTS.PREDICTIVE.MODEL_REGISTRY_ROLLBACK(entry.model_type), {});
        await refreshModelRegistry('Rollback complete. Previous retired model is active again.');
      } catch (error) {
        console.error(error);
        setStatus('Rollback could not be completed. There may be no previous retired model.', 'error');
      }
    }

    async function loadRecommendationDossier(recommendationId) {
      setStatus('Loading recommendation dossier...');
      try {
        state.selectedRecommendationDossier = await getJson(API_ENDPOINTS.ANALYTICS.RECOMMENDATION_DOSSIER(recommendationId), null);
        renderRecommendationDossier();
        clearStatus();
      } catch (error) {
        console.error(error);
        setStatus('Recommendation dossier could not be loaded.', 'error');
      }
    }

    async function showCurriculumDetail(documentId) {
      const idx = state.documents.findIndex((d) => d.document_id === documentId);
      if (idx === -1) return;
      state.selectedCurriculumDoc = idx;
      const doc = state.documents[idx];
      let detail = state.documentDetails[idx];
      if (!detail) {
        detail = await getJson(API_ENDPOINTS.CURRICULUM.DOCUMENT_DETAIL(documentId), null);
        if (detail) state.documentDetails[idx] = detail;
      }
      const versions = detail?.versions || [];
      const chunkCount = versions.reduce((sum, v) => sum + Number(v.chunk_count || 0), 0);
      const totalFileSize = versions.reduce((sum, v) => sum + Number(v.file_size || 0), 0);
      const extractionOk = versions.filter((v) => v.extraction_status === 'completed').length;
      const extractionTotal = versions.length;

      const panel = $('curriculumListPanel');
      const detailPanel = $('curriculumDetailPanel');
      if (panel) panel.style.display = 'none';
      if (detailPanel) detailPanel.style.display = 'block';

      $('curriculumDetailTitle').textContent = escapeHtml(doc.title);
      const content = $('curriculumDetailContent');
      content.innerHTML = `
        <div class="kv-grid" style="margin-bottom:16px">
          <div><strong>Document ID</strong><span><code>${doc.document_id}</code></span></div>
          <div><strong>Status</strong><span>${statusBadge(doc.status, doc.status === 'active' ? 'good' : doc.status === 'archived' ? 'warn' : '')}</span></div>
          <div><strong>Faculty</strong><span>${escapeHtml(doc.faculty || '-')}</span></div>
          <div><strong>Department</strong><span>${escapeHtml(doc.department || '-')}</span></div>
          <div><strong>Programme</strong><span>${escapeHtml(doc.programme || '-')}</span></div>
          <div><strong>Description</strong><span>${escapeHtml(doc.description || '-')}</span></div>
          <div><strong>Document Key</strong><span>${escapeHtml(doc.document_key || '-')}</span></div>
          <div><strong>Created</strong><span>${new Date(doc.created_at).toLocaleString()}</span></div>
          <div><strong>Updated</strong><span>${new Date(doc.updated_at).toLocaleString()}</span></div>
          <div><strong>Created By</strong><span>${escapeHtml(doc.created_by || '-')}</span></div>
        </div>
        <div class="metrics" style="margin-bottom:16px">
          <div class="metric"><span>Versions</span><strong>${formatNumber(versions.length)}</strong><small>Total revisions</small></div>
          <div class="metric"><span>Chunks</span><strong>${formatNumber(chunkCount)}</strong><small>Extracted segments</small></div>
          <div class="metric"><span>File Size</span><strong>${totalFileSize ? formatFileSize(totalFileSize) : '-'}</strong><small>Total across versions</small></div>
          <div class="metric"><span>Extraction</span><strong>${extractionTotal ? percent(extractionOk / extractionTotal) : '-'}</strong><small>${extractionOk}/${extractionTotal} versions completed</small></div>
        </div>
        <h4 style="margin:0 0 10px;font-size:14px;font-weight:600">Version History</h4>
        <div class="table-wrap">
          <table>
            <thead><tr><th>Version</th><th>Filename</th><th>Pages</th><th>Chunks</th><th>Size</th><th>Extraction</th><th>Uploaded</th></tr></thead>
            <tbody>
              ${versions.length ? versions.map((v) => `
                <tr>
                  <td>${formatNumber(v.version_number)}</td>
                  <td>${escapeHtml(v.original_filename || '-')}</td>
                  <td>${formatNumber(v.page_count || 0)}</td>
                  <td>${formatNumber(v.chunk_count || 0)}</td>
                  <td>${v.file_size ? formatFileSize(v.file_size) : '-'}</td>
                  <td>${statusBadge(v.extraction_status, v.extraction_status === 'completed' ? 'good' : v.extraction_status === 'failed' ? 'bad' : 'warn')}</td>
                  <td>${new Date(v.created_at).toLocaleString()}</td>
                </tr>
              `).join('') : '<tr><td colspan="7"><div class="empty">No versions recorded yet.</div></td></tr>'}
            </tbody>
          </table>
        </div>
        ${doc.document_metadata && Object.keys(doc.document_metadata).length ? `
          <details style="margin-top:16px">
            <summary style="cursor:pointer;font-weight:600;font-size:13px;color:var(--text-secondary)">Document Metadata (${Object.keys(doc.document_metadata).length} keys)</summary>
            <pre style="margin:8px 0 0;padding:12px;background:var(--surface-alt);border:1.5px solid var(--border);border-radius:var(--radius-sm);font-size:12px;overflow-x:auto;white-space:pre-wrap">${escapeHtml(JSON.stringify(doc.document_metadata, null, 2))}</pre>
          </details>
        ` : ''}
      `;
    }

    function closeCurriculumDetail() {
      state.selectedCurriculumDoc = null;
      const panel = $('curriculumListPanel');
      const detailPanel = $('curriculumDetailPanel');
      if (panel) panel.style.display = '';
      if (detailPanel) detailPanel.style.display = 'none';
      renderCurriculumRows('curriculumTable', state.documents);
    }

    async function loadSkillGapEvidence(skillId, versionId) {
      setStatus('Loading skill-gap evidence drill-down...');
      const params = new URLSearchParams({ limit: '10' });
      if (versionId) params.set('version_id', versionId);
      state.selectedSkillGapEvidence = await getJson(`${API_ENDPOINTS.ANALYTICS.SKILL_GAP_EVIDENCE(skillId)}?${params.toString()}`, null);
      renderSkillGapEvidence(state.selectedSkillGapEvidence);
      setStatus('Skill-gap evidence loaded.', 'ok');
    }

    function connectorPayloadFromPrompt(existing = {}) {
      const raw = window.prompt('Connector JSON', JSON.stringify({
        connector_key: existing.connector_key || 'new_connector_key',
        name: existing.name || 'New Connector',
        connector_family: existing.connector_family || 'custom',
        ingestion_mode: existing.ingestion_mode || 'manual',
        source_category: existing.source_category || 'curriculum',
        source_format: existing.source_format || 'html',
        normaliser_key: existing.normaliser_key || null,
        is_streaming_capable: Boolean(existing.is_streaming_capable),
        requires_auth: Boolean(existing.requires_auth),
        description: existing.description || '',
        capability_profile: existing.capability_profile || {},
        default_config: existing.default_config || {},
        status: existing.status || 'active',
      }, null, 2));
      return raw === null ? null : JSON.parse(raw);
    }

    async function addConnector() {
      try {
        const payload = connectorPayloadFromPrompt();
        if (!payload) return;
        await postJson(API_ENDPOINTS.INGESTION.CONNECTORS, payload);
        state.connectorDefinitions = asItems(await getJson(API_ENDPOINTS.INGESTION.CONNECTORS, []));
        renderConnectorCatalogRows('connectorCatalogRows', state.connectorDefinitions);
        setStatus('Connector definition created.', 'ok');
      } catch (error) {
        console.error(error);
        setStatus('Connector definition could not be created. Check JSON and unique connector key.', 'error');
      }
    }

    async function editConnector(connectorKey) {
      try {
        const existing = state.connectorDefinitions.find((item) => item.connector_key === connectorKey) || await getJson(API_ENDPOINTS.INGESTION.CONNECTOR_DETAIL(connectorKey), null);
        const payload = connectorPayloadFromPrompt(existing || {});
        if (!payload) return;
        delete payload.connector_key;
        await postJson(API_ENDPOINTS.INGESTION.CONNECTOR_DETAIL(connectorKey), payload, 'PUT');
        state.connectorDefinitions = asItems(await getJson(API_ENDPOINTS.INGESTION.CONNECTORS, []));
        renderConnectorCatalogRows('connectorCatalogRows', state.connectorDefinitions);
        setStatus('Connector definition updated.', 'ok');
      } catch (error) {
        console.error(error);
        setStatus('Connector definition could not be updated. Check JSON and allowed values.', 'error');
      }
    }

    function sourcePayloadFromPrompt(existing = {}) {
      const raw = window.prompt('Source JSON', JSON.stringify({
        source_key: existing.source_key || 'new_source_key',
        name: existing.name || 'New Source',
        source_type: existing.source_type || 'web_page',
        source_category: existing.source_category || 'curriculum',
        connector_type: existing.connector_type || state.connectorDefinitions[0]?.connector_key || 'web_discovery',
        source_scope: existing.source_scope || 'shared',
        ingestion_mode: existing.ingestion_mode || 'manual',
        source_format: existing.source_format || 'html',
        normaliser_key: existing.normaliser_key || null,
        base_url: existing.base_url || '',
        storage_path: existing.storage_path || '',
        refresh_policy: existing.refresh_policy || 'manual',
        retry_policy: existing.retry_policy || { max_attempts: 3, backoff_seconds: 60 },
        owner: existing.owner || '',
        status: existing.status || 'active',
        is_authorised: existing.is_authorised ?? true,
        config: existing.config || {},
        auth_config: existing.auth_config || {},
      }, null, 2));
      return raw === null ? null : JSON.parse(raw);
    }

    async function addSource() {
      try {
        const payload = sourcePayloadFromPrompt();
        if (!payload) return;
        await postJson(API_ENDPOINTS.INGESTION.SOURCES, payload);
        state.ingestionSources = asItems(await getJson(API_ENDPOINTS.INGESTION.SOURCES, []));
        renderSourceConnectorRows('sourceConnectorRows', state.ingestionSources);
        setStatus('Data source created.', 'ok');
      } catch (error) {
        console.error(error);
        setStatus('Data source could not be created. Check JSON, source key, and connector type.', 'error');
      }
    }

    async function toggleSource(sourceId, action) {
      const endpoint = action === 'disable' ? API_ENDPOINTS.INGESTION.SOURCE_DISABLE(sourceId) : API_ENDPOINTS.INGESTION.SOURCE_ENABLE(sourceId);
      await postJson(endpoint, {});
      state.ingestionSources = asItems(await getJson(API_ENDPOINTS.INGESTION.SOURCES, []));
      renderSourceConnectorRows('sourceConnectorRows', state.ingestionSources);
      setStatus(`Source ${action === 'disable' ? 'disabled' : 'enabled'}.`, 'ok');
    }

    async function loadContractDrift(contractId) {
      state.selectedContract = state.ingestionContracts.find((item) => item.contract_id === contractId) || null;
      state.selectedContractDrift = await getJson(API_ENDPOINTS.INGESTION.CONTRACT_DRIFT(contractId), null);
      const contractOpsCaption = $('contractOpsCaption');
      if (contractOpsCaption) contractOpsCaption.textContent = state.selectedContract ? `Contract ${state.selectedContract.contract_key}` : 'Contract drift loaded';
      renderContractOps();
    }

    async function editContract(contractId) {
      const contract = state.ingestionContracts.find((item) => item.contract_id === contractId);
      if (!contract) return;
      const raw = window.prompt('Contract JSON', JSON.stringify({
        name: contract.name,
        description: contract.description || '',
        schema_definition: contract.schema_definition || {},
        cleaning_profile: contract.cleaning_profile || {},
        quality_thresholds: contract.quality_thresholds || {},
        status: contract.status || 'active',
      }, null, 2));
      if (raw === null) return;
      try {
        state.selectedContract = await postJson(API_ENDPOINTS.INGESTION.CONTRACT_DETAIL(contractId), JSON.parse(raw || '{}'), 'PUT');
        state.ingestionContracts = asItems(await getJson(API_ENDPOINTS.INGESTION.CONTRACTS, []));
        renderQualityContractRows('qualityContractRows', state.ingestionContracts);
        renderContractOps();
        setStatus('Contract updated.', 'ok');
      } catch (error) {
        console.error(error);
        setStatus('Contract could not be updated. Check that the JSON is valid.', 'error');
      }
    }

    async function cloneContract(contractId) {
      const version = window.prompt('New contract version, for example 1.1.0', '1.1.0');
      if (!version) return;
      const name = window.prompt('Optional contract name', '');
      try {
        state.selectedContract = await postJson(API_ENDPOINTS.INGESTION.CONTRACT_CLONE(contractId), {
          version,
          name: name || null,
          status: 'draft',
        });
        state.ingestionContracts = asItems(await getJson(API_ENDPOINTS.INGESTION.CONTRACTS, []));
        renderQualityContractRows('qualityContractRows', state.ingestionContracts);
        renderContractOps();
        setStatus(`Contract cloned as version ${version}.`, 'ok');
      } catch (error) {
        console.error(error);
        setStatus('Contract could not be cloned. The version may already exist.', 'error');
      }
    }

    async function loadSkillsValidity() {
      const target = $('skillsValidityPanel');
      if (target) {
        target.className = 'empty';
        target.textContent = 'Loading ESCO skills and alignment status...';
      }
      showSpinner('spinnerSkillsValidity');
      setStatus('Loading ESCO skills and alignment status...');
      state.skillsValidity = await getJson(API_ENDPOINTS.SKILLS.SKILLS_READINESS, null, 60000);
      state.alignmentCalibration = await getJson(API_ENDPOINTS.SKILLS.ALIGNMENT_CALIBRATION, null, 60000);
      try {
        const runs = await getJson(`${SKILLS_BASE}/esco/bundle/runs`, [], 60000);
        const list = Array.isArray(runs) ? runs : (runs.items || []);
        const imported = list.find((b) => b.status === 'imported') || list[0];
        state.escoAccounting = imported
          ? await getJson(`${SKILLS_BASE}/esco/bundle/${imported.bundle_id || imported.id}/status`, null, 60000)
          : null;
      } catch (error) {
        state.escoAccounting = null;
      }
      hideSpinner('spinnerSkillsValidity');
      renderSkillsValidity();
      setStatus(state.skillsValidity ? 'Skills status loaded.' : 'Skills status could not be loaded.', state.skillsValidity ? 'ok' : 'error');
    }

    async function loadIngestionDataQuality() {
      const target = $('ingestionDataQualityPanel');
      if (target) {
        target.className = 'empty';
        target.textContent = 'Loading ingestion data quality summary...';
      }
      showSpinner('spinnerIngestionDataQuality');
      setStatus('Loading ingestion data quality summary...');
      state.ingestionDataQuality = await getJson(API_ENDPOINTS.INGESTION.INGESTION_DATA_QUALITY, null, 60000);
      hideSpinner('spinnerIngestionDataQuality');
      renderIngestionDataQuality();
      setStatus(state.ingestionDataQuality ? 'Ingestion quality summary loaded.' : 'Ingestion quality summary could not be loaded.', state.ingestionDataQuality ? 'ok' : 'error');
    }

    async function remapTableRows() {
      const confirmed = await showConfirm('Remap Table Rows', 'Remap up to 5,000 extracted table rows using the current StatsSA/CHE canonical mapping rules?');
      if (!confirmed) return;
      setStatus('Remapping extracted table rows...');
      try {
        const result = await postJson(`${API_ENDPOINTS.INGESTION.REMAP_TABLE_ROWS}?limit=5000`, {});
        setStatus(`Remapped ${formatNumber(result.rows_updated || 0)} of ${formatNumber(result.rows_checked || 0)} checked rows.`, 'ok');
        await loadIngestionDataQuality();
      } catch (error) {
        console.error(error);
        setStatus('Table row remap failed. Check API logs.', 'error');
      }
    }

    async function loadReviewRows() {
      const params = new URLSearchParams({ limit: '100' });
      const sourceCategory = $('reviewSourceCategory')?.value || '';
      const statusFilter = $('reviewStatusFilter')?.value || '';
      const recordType = ($('reviewRecordType')?.value || '').trim();
      if (sourceCategory) params.set('source_category', sourceCategory);
      if (statusFilter) params.set('status_filter', statusFilter);
      if (recordType) params.set('record_type', recordType);
      if ($('reviewLowConfidence')?.checked) params.set('low_confidence', 'true');
      state.reviewRecords = await getJson(`${API_ENDPOINTS.INGESTION.RECORDS_REVIEW}?${params.toString()}`, []);
      renderReviewRecordRows();
      setStatus(`Loaded ${formatNumber(state.reviewRecords.length)} review records.`, 'ok');
    }

    async function reviewRecord(recordId, reviewStatus) {
      const note = window.prompt(`Reason for marking record as ${reviewStatus}`, '');
      if (note === null) return;
      await postJson(API_ENDPOINTS.INGESTION.RECORD_REVIEW(recordId), { status: reviewStatus, note });
      state.reviewRecords = state.reviewRecords.filter((record) => record.record_id !== recordId);
      renderReviewRecordRows();
      setStatus(`Record marked as ${reviewStatus}.`, 'ok');
    }

    async function correctRecord(recordId) {
      const record = state.reviewRecords.find((item) => item.record_id === recordId);
      const raw = window.prompt('Corrected normalised payload JSON', JSON.stringify(record?.normalised_payload || record?.raw_payload || {}, null, 2));
      if (raw === null) return;
      const note = window.prompt('Correction note', 'Manual correction from review queue');
      if (note === null) return;
      try {
        await postJson(API_ENDPOINTS.INGESTION.RECORD_REVIEW(recordId), {
          status: 'corrected',
          note,
          corrected_payload: JSON.parse(raw || '{}'),
        });
        state.reviewRecords = state.reviewRecords.filter((item) => item.record_id !== recordId);
        renderReviewRecordRows();
        setStatus('Record corrected and removed from review queue.', 'ok');
      } catch (error) {
        console.error(error);
        setStatus('Record could not be corrected. Check that the JSON is valid.', 'error');
      }
    }

    async function refreshProcessingSummary() {
      state.processingSummary = await getJson(API_ENDPOINTS.PROCESSING.SUMMARY, null);
      if ($('validatedRegenerationReadiness')) {
        state.validatedRegenerationReadiness = await getJson(
          API_ENDPOINTS.PROCESSING.VALIDATED_REGENERATION_READINESS,
          null,
        );
        renderValidatedRegenerationReadiness();
      }
      renderProcessingPhase();
      setStatus('Processing summary refreshed.', 'ok');
    }

    function renderValidatedRegenerationReadiness() {
      const target = $('validatedRegenerationReadiness');
      if (!target) return;
      const readiness = state.validatedRegenerationReadiness;
      const buttons = [
        $('runFullProcessingBtn'),
        $('rerunAlignmentBtn'),
        $('rerunForecastsBtn'),
        $('rerunRecommendationsBtn'),
      ].filter(Boolean);
      if (!readiness) {
        target.className = 'empty';
        target.textContent = 'Validated-evidence readiness is unavailable.';
        buttons.forEach((button) => { button.disabled = true; });
        return;
      }
      const ready = readiness.status === 'ready';
      buttons.forEach((button) => {
        button.disabled = !ready;
        button.title = ready ? '' : 'Complete every validated-evidence readiness check first';
      });
      const checks = readiness.checks || [];
      target.className = ready ? '' : 'empty';
      target.innerHTML = `
        <p><strong>Regeneration status:</strong> ${statusBadge(readiness.status || 'unknown', ready ? 'good' : 'warn')}</p>
        <div>${checks.map((check) => statusBadge(
          `${check.key.replaceAll('_', ' ')}: ${formatNumber(check.count || 0)}`,
          check.status === 'ready' ? 'good' : 'warn',
        )).join(' ')}</div>
        <p style="margin-top:8px"><small>Eligible curriculum versions: ${formatNumber((readiness.eligible_curriculum_versions || []).length)}. Latest manifest: ${escapeHtml(readiness.latest_manifest?.payload_hash?.slice(0, 16) || 'none')}.</small></p>
      `;
    }

    async function refreshProcessingOutputs() {
      state.processingSummary = await getJson(API_ENDPOINTS.PROCESSING.SUMMARY, null);
      state.analyticsSummary = await getJson(API_ENDPOINTS.ANALYTICS.SUMMARY, {});
      state.alignmentScores = await getJson(`${API_ENDPOINTS.ANALYTICS.ALIGNMENT_SCORES}?limit=10`, []);
      state.forecasts = await getJson(`${API_ENDPOINTS.ANALYTICS.FORECASTS}?limit=100`, []);
      state.modelReadiness = await getJson(API_ENDPOINTS.PREDICTIVE.MODEL_READINESS, null, 60000);
      state.recommendations = await getJson(`${API_ENDPOINTS.ANALYTICS.RECOMMENDATIONS}?limit=100`, []);
      state.recommendationGroups = (await getJson(`${API_ENDPOINTS.ANALYTICS.RECOMMENDATIONS_GROUPED}?status=pending_review&limit=50`, { groups: [] })).groups || [];
      state.generatedReports = await getJson(`${API_ENDPOINTS.ANALYTICS.REPORTS}?limit=50`, []);
      if ($('executive')) renderExecutive();
      if ($('skills')) renderSkills();
      if ($('forecast')) renderForecasts();
      renderProcessingPhase();
      if ($('reports')) renderReports();
      renderOperationalJobRows();
    }


    async function refreshSkillsData() {
      state.skillsSummary = await getJson(API_ENDPOINTS.SKILLS.SUMMARY, {});
      state.skillMappings = await getJson(`${API_ENDPOINTS.SKILLS.MAPPINGS}?limit=100`, []);
      state.skillGapSummary = await getJson(`${API_ENDPOINTS.ANALYTICS.SKILL_GAPS}?limit=8`, { gaps: [] });
      renderSkills();
    }

    async function refreshForecastData() {
      state.forecasts = await getJson(`${API_ENDPOINTS.ANALYTICS.FORECASTS}?limit=100`, []);
      state.modelReadiness = await getJson(API_ENDPOINTS.PREDICTIVE.MODEL_READINESS, null, 60000);
      state.forecastQuality = await getJson(API_ENDPOINTS.PREDICTIVE.FORECAST_QUALITY, null, 60000);
      renderForecasts();
    }

    async function runForecasts() {
      const confirmed = await showConfirm('Run Forecasts', 'Run forecast generation (alignment + XGBoost/LSTM) against current skill mappings and demand signals?');
      if (!confirmed) return;
      setStatus('Running forecast generation...');
      try {
        await postJson(API_ENDPOINTS.PROCESSING.RUN_FULL, {});
        await refreshForecastData();
        setStatus('Forecast generation completed.', 'ok');
      } catch (error) {
        console.error(error);
        setStatus('Forecast generation failed. Check API logs.', 'error');
      }
    }

    async function runSkillExtraction() {
      const confirmed = await showConfirm('Run Skill Extraction', 'Extract skills from all curriculum documents and labour market data? This will create new skill mappings.');
      if (!confirmed) return;
      setStatus('Running skill extraction...');
      try {
        await postJson(API_ENDPOINTS.SKILLS.EXTRACT_CURRICULUM, {});
        await postJson(API_ENDPOINTS.SKILLS.EXTRACT_LABOUR_MARKET, {});
        await refreshSkillsData();
        setStatus('Skill extraction completed. Refresh to see updated mappings.', 'ok');
      } catch (error) {
        console.error(error);
        setStatus('Skill extraction failed. Check API logs.', 'error');
      }
    }

    async function runGapAnalysis() {
      const confirmed = await showConfirm('Run Gap Analysis', 'Run alignment scoring and gap detection against current curriculum and labour-market mappings?');
      if (!confirmed) return;
      setStatus('Running gap analysis...');
      try {
        await postJson(API_ENDPOINTS.ANALYTICS.GENERATE, {});
        await refreshSkillsData();
        setStatus('Gap analysis completed.', 'ok');
      } catch (error) {
        console.error(error);
        setStatus('Gap analysis failed. Check API logs.', 'error');
      }
    }

    async function loadForecastQuality() {
      const target = $('forecastQualityPanel');
      if (target) {
        target.className = 'empty';
        target.textContent = 'Loading forecast and recommendation quality report...';
      }
      showSpinner('spinnerForecastQuality');
      setStatus('Loading quality report...');
      state.forecastQuality = await getJson(API_ENDPOINTS.PREDICTIVE.FORECAST_QUALITY, null, 60000);
      hideSpinner('spinnerForecastQuality');
      renderForecastQuality();
      setStatus(state.forecastQuality ? 'Quality report loaded.' : 'Quality report could not be loaded.', state.forecastQuality ? 'ok' : 'error');
    }

    async function runProcessingEndpoint(endpoint, label, query = '') {
      setStatus(`${label}...`);
      try {
        const result = await postJson(`${endpoint}${query}`, {});
        const job = result.job;
        await refreshOperationalJobs();
        setStatus(
          result.coalesced
            ? `${label}: an equivalent job is already ${job?.status || 'active'}.`
            : `${label} accepted as job ${String(job?.job_id || '').slice(0, 8)}. It will continue if you leave this page.`,
          'ok',
        );
      } catch (error) {
        console.error(error);
        setStatus(`${label} failed. Check API logs and try again.`, 'error');
      }
    }

    function renderModelRuntimeContinuity() {
      const target = $('modelRuntimeContinuityPanel');
      if (!target) return;
      const continuity = state.modelRuntimeContinuity;
      if (!continuity) {
        target.className = 'empty';
        target.textContent = 'Runtime continuity status is not available.';
        return;
      }
      const models = continuity.models || {};
      target.className = '';
      target.innerHTML = `
        <p><strong>Registry/runtime status:</strong> ${statusBadge(continuity.status || 'unknown', continuity.status === 'passed' ? 'good' : 'bad')}</p>
        <table><thead><tr><th>Model</th><th>Registry version</th><th>Runtime version</th><th>Status</th></tr></thead><tbody>
          ${['xgboost', 'lstm'].map((type) => {
            const row = models[type] || {};
            const hasActiveModel = Boolean(row.registry_model_version);
            const continuityLabel = hasActiveModel ? (row.status || 'unknown') : 'not activated';
            const continuityTone = !hasActiveModel ? 'warn' : row.status === 'matched' ? 'good' : 'bad';
            return `<tr><td>${escapeHtml(type.toUpperCase())}</td><td>${escapeHtml(row.registry_model_version || 'none active')}</td><td>${escapeHtml(row.runtime?.model_version || 'none loaded')}</td><td>${statusBadge(continuityLabel, continuityTone)}</td></tr>`;
          }).join('')}
        </tbody></table>
        <p><small>Startup restoration: ${escapeHtml(continuity.startup_restoration?.status || 'not recorded')} &middot; database constraint: ${escapeHtml(continuity.single_active_constraint || '-')}</small></p>
      `;
    }

    function renderXgboostDatasetReadiness() {
      const target = $('xgboostDatasetReadiness');
      if (!target) return;
      const snapshot = state.alignmentLabelSnapshot;
      const readiness = state.xgboostTrainReadiness;
      const button = $('trainXgboostBtn');
      const canTrain = Boolean(snapshot) && readiness?.status === 'ready';
      if (!snapshot && !readiness) {
        target.className = 'empty';
        target.textContent = 'Blocked: no locked reviewed label dataset. Complete paired UAT reviews in Data Operations, then lock the dataset.';
        if (button) {
          button.disabled = true;
          button.title = 'A locked reviewed label dataset is required';
        }
        return;
      }
      const modeIsUat = (snapshot?.dataset_mode || readiness?.readiness?.dataset_mode) === 'technical_uat_researcher_operated';
      const reasonLines = (readiness?.readiness?.blocked_reasons || [])
        .map((reason) => `<li>${escapeHtml(reason)}</li>`).join('');
      target.className = '';
      target.innerHTML = `
        <div style="margin-bottom:6px"><strong>Training status:</strong> ${statusBadge(String(readiness?.status || 'blocked'), readiness?.status === 'ready' ? 'good' : 'warn')} ${readiness?.message ? escapeHtml(readiness.message) : ''}</div>
        ${reasonLines ? `<ul style="margin:4px 0 0 16px;padding:0">${reasonLines}</ul>` : ''}
        <div style="margin-top:6px">${snapshot
          ? `<strong>Locked dataset:</strong> ${escapeHtml(snapshot.snapshot_version)} · ${formatNumber(snapshot.row_count || 0)} rows · fingerprint <code>${escapeHtml(String(snapshot.dataset_fingerprint || '').slice(0, 16))}</code> · mode ${escapeHtml(snapshot.dataset_mode || 'unknown')}`
          : '<strong>Locked dataset:</strong> none'}</div>
        ${modeIsUat
          ? '<div style="margin-top:6px;font-size:12px;color:#b26a00">Researcher-operated UAT personas (<code>uat_analyst_01</code>/<code>uat_analyst_02</code>) produced this sample — experimental technical-UAT evidence, <strong>not</strong> independent expert labels. An <code>independent_expert_validation</code> mode is reserved for future expert operation.</div>'
          : ''}
        <div style="margin-top:4px;font-size:12px">Training will read only immutable snapshot membership and source evidence.</div>
      `;
      if (button) {
        button.disabled = !canTrain;
        button.title = canTrain ? '' : 'Complete and lock a UAT-reviewed label dataset before candidate training';
      }
    }

    async function loadXgboostTrainReadiness() {
      if (!$('xgboostDatasetReadiness')) return;
      try {
        state.xgboostTrainReadiness = await getJson(API_ENDPOINTS.PREDICTIVE.TRAIN_XGBOOST_READINESS, null);
      } catch (error) {
        state.xgboostTrainReadiness = null;
      }
      renderXgboostDatasetReadiness();
    }

    async function refreshOperationalJobs() {
      if (!$('operationalJobRows')) return;
      const payload = await getJson(
        `${API_ENDPOINTS.OPERATIONS.JOBS}?limit=50`,
        { jobs: [] },
      );
      state.operationalJobs = payload.jobs || [];
      renderOperationalJobRows();
    }


    function subjectProfileStatusTone(status) {
      if (status === 'validated') return 'good';
      if (status === 'rejected') return 'bad';
      if (status === 'changes_required') return 'warn';
      return 'neutral';
    }

    function missingSubjectProfileFields(profile) {
      const required = [
        ['faculty', 'faculty'],
        ['department', 'department'],
        ['programme_name', 'programme'],
        ['subject_code', 'subject code'],
        ['subject_name', 'subject name'],
        ['credits', 'credits'],
        ['nqf_level', 'NQF level'],
      ];
      return required.filter(([key]) => profile[key] === null || profile[key] === undefined || String(profile[key]).trim() === '').map(([, label]) => label);
    }

    function renderSubjectProfileValidationRows() {
      const target = $('subjectProfileValidationRows');
      const summary = $('subjectProfileValidationSummary');
      if (!target) return;
      const profiles = state.subjectProfiles || [];
      const filter = state.subjectProfileStatusFilter || 'active_review';
      const isOutstandingProfile = (profile) => {
        const status = profile.validation_status || 'needs_review';
        return status === 'needs_review' || status === 'changes_required';
      };
      const visibleProfiles = profiles.filter((profile) => {
        const status = profile.validation_status || 'needs_review';
        if (filter === 'all') return true;
        if (filter === 'active_review') return isOutstandingProfile(profile);
        return status === filter;
      });
      const missingCount = profiles.filter((profile) => missingSubjectProfileFields(profile).length).length;
      const validatedCount = profiles.filter((profile) => profile.validation_status === 'validated').length;
      const rejectedCount = profiles.filter((profile) => profile.validation_status === 'rejected').length;
      if (summary) {
        summary.className = profiles.length ? '' : 'empty';
        const label = filter === 'all' ? 'all profiles' : filter === 'active_review' ? 'outstanding profiles' : filter.replaceAll('_', ' ');
        summary.textContent = profiles.length
          ? `${formatNumber(visibleProfiles.length)} ${label} shown · ${formatNumber(profiles.length)} total · ${formatNumber(validatedCount)} validated · ${formatNumber(rejectedCount)} rejected · ${formatNumber(missingCount)} still missing reporting fields`
          : 'No subject profiles have been derived yet. Upload official curriculum documents first.';
      }
      target.innerHTML = visibleProfiles.map((profile) => {
        const missing = missingSubjectProfileFields(profile);
        const hierarchy = [profile.institution, profile.faculty, profile.department].filter(Boolean).join(' / ') || 'Hierarchy not confirmed';
        const subject = [profile.subject_code, profile.subject_name].filter(Boolean).join(' — ') || profile.document_title || 'Unnamed subject';
        return `<tr>
          <td><strong>${escapeHtml(subject)}</strong><br><small>${formatNumber((profile.extracted_skills || profile.skills || []).length)} skills · ${formatNumber((profile.learning_outcomes || profile.outcomes || []).length)} outcomes · ${formatNumber((profile.assessment_evidence || profile.assessments || []).length)} assessments</small></td>
          <td>${escapeHtml(profile.programme_name || 'Programme not confirmed')}<br><small>${escapeHtml(profile.programme_code || profile.qualification_type || '')}</small></td>
          <td>${escapeHtml(hierarchy)}${missing.length ? `<br><small>Missing: ${escapeHtml(missing.join(', '))}</small>` : ''}</td>
          <td>${escapeHtml(profile.subject_year || profile.evidence_year || '-')}</td>
          <td>NQF ${escapeHtml(profile.nqf_level || '-')}<br><small>${escapeHtml(profile.credits || '-')} credits</small></td>
          <td>${statusBadge(profile.validation_status || 'needs_review', subjectProfileStatusTone(profile.validation_status || 'needs_review'))}</td>
          <td><button class="btn subject-profile-edit-btn" data-profile-id="${escapeHtml(profile.profile_id || profile.source_profiles?.[0]?.profile_id || '')}">Validate / edit</button></td>
        </tr>`;
      }).join('') || '<tr><td colspan="7">No subject profiles match the selected filter.</td></tr>';
    }

    async function loadSubjectProfiles(showMessage = true) {
      const summary = $('subjectProfileValidationSummary');
      try {
        const payload = await getJson(API_ENDPOINTS.CURRICULUM.SUBJECT_PROFILES, { items: [] });
        state.subjectProfiles = payload.items || payload.profiles || [];
        renderSubjectProfileValidationRows();
        if (showMessage) setStatus('Subject profiles refreshed.', 'ok');
      } catch (error) {
        state.subjectProfiles = [];
        if (summary) {
          summary.className = 'empty error';
          summary.textContent = `Subject profiles could not be loaded: ${error.message || 'API error'}`;
        }
        if ($('subjectProfileValidationRows')) {
          $('subjectProfileValidationRows').innerHTML = '<tr><td colspan="7">Subject profiles could not be loaded. Please refresh after the backend has restarted.</td></tr>';
        }
      }
    }

    function setSubjectProfileValidationModalStatus(message = '', tone = '') {
      const target = $('subjectProfileValidationModalStatus');
      if (!target) return;
      target.textContent = message;
      target.className = message ? `inline-status show ${tone || ''}`.trim() : 'inline-status';
    }

    function openSubjectProfileValidation(profileId) {
      const profile = (state.subjectProfiles || []).find((entry) =>
        entry.profile_id === profileId || (entry.source_profiles || []).some((source) => source.profile_id === profileId)
      );
      if (!profile) {
        const message = 'Could not open subject profile. Please click Refresh Profiles and try again.';
        showToast(message, 'error');
        setStatus(message, 'error');
        return;
      }
      const editableProfileId = profile.profile_id || profile.source_profiles?.[0]?.profile_id || profileId;
      if (!editableProfileId) {
        const message = 'This subject profile has no editable profile ID yet. Rebuild the subject profile from its curriculum version.';
        showToast(message, 'error');
        setStatus(message, 'error');
        return;
      }
      $('subjectProfileId').value = editableProfileId;
      $('subjectProfileValidationTitle').textContent = `${profile.subject_code || 'Uncoded subject'} · ${profile.subject_name || profile.document_title || 'Subject profile'}`;
      $('subjectProfileInstitution').value = profile.institution || '';
      $('subjectProfileFaculty').value = profile.faculty || '';
      $('subjectProfileDepartment').value = profile.department || '';
      $('subjectProfileProgrammeName').value = profile.programme_name || '';
      $('subjectProfileProgrammeCode').value = profile.programme_code || '';
      $('subjectProfileQualificationType').value = profile.qualification_type || '';
      $('subjectProfileSubjectCode').value = profile.subject_code || '';
      $('subjectProfileSubjectName').value = profile.subject_name || '';
      $('subjectProfileYear').value = profile.subject_year || profile.evidence_year || '';
      $('subjectProfileNqf').value = profile.nqf_level || '';
      $('subjectProfileCredits').value = profile.credits || '';
      $('subjectProfileStatus').value = profile.validation_status || 'needs_review';
      $('subjectProfilePurpose').value = profile.purpose || '';
      $('subjectProfileArticulation').value = profile.articulation || '';
      $('subjectProfileNotes').value = profile.validation_notes || '';
      setSubjectProfileValidationModalStatus('', '');
      $('subjectProfileValidationModal')?.classList.remove('hidden');
    }

    function closeSubjectProfileValidation() {
      setSubjectProfileValidationModalStatus('', '');
      $('subjectProfileValidationModal')?.classList.add('hidden');
    }

    async function submitSubjectProfileValidation() {
      const profileId = $('subjectProfileId')?.value;
      if (!profileId) return;
      const saveButton = $('submitSubjectProfileValidationBtn');
      const payload = {
        institution: $('subjectProfileInstitution')?.value?.trim() || null,
        faculty: $('subjectProfileFaculty')?.value?.trim() || null,
        department: $('subjectProfileDepartment')?.value?.trim() || null,
        programme_name: $('subjectProfileProgrammeName')?.value?.trim() || null,
        programme_code: $('subjectProfileProgrammeCode')?.value?.trim() || null,
        qualification_type: $('subjectProfileQualificationType')?.value?.trim() || null,
        subject_code: $('subjectProfileSubjectCode')?.value?.trim() || null,
        subject_name: $('subjectProfileSubjectName')?.value?.trim() || null,
        subject_year: $('subjectProfileYear')?.value ? Number($('subjectProfileYear').value) : null,
        nqf_level: $('subjectProfileNqf')?.value ? Number($('subjectProfileNqf').value) : null,
        credits: $('subjectProfileCredits')?.value ? Number($('subjectProfileCredits').value) : null,
        purpose: $('subjectProfilePurpose')?.value?.trim() || null,
        articulation: $('subjectProfileArticulation')?.value?.trim() || null,
        validation_status: $('subjectProfileStatus')?.value || 'needs_review',
        validation_notes: $('subjectProfileNotes')?.value?.trim() || null,
      };
      const missing = missingSubjectProfileFields(payload);
      if (payload.validation_status === 'validated' && missing.length) {
        const message = `Cannot mark as validated yet. Please complete: ${missing.join(', ')}.`;
        setSubjectProfileValidationModalStatus(message, 'error');
        showToast(message, 'error');
        return;
      }
      if (payload.validation_status === 'needs_review' && !missing.length) {
        setSubjectProfileValidationModalStatus('This profile has all required fields but is still marked Needs review. Change Validation status to Validated if you want it removed from the outstanding list.', 'warn');
      } else {
        setSubjectProfileValidationModalStatus('Saving subject profile review...', '');
      }
      if (saveButton) {
        saveButton.disabled = true;
        saveButton.textContent = 'Saving...';
      }
      try {
        const saved = await postJson(API_ENDPOINTS.CURRICULUM.SUBJECT_PROFILE(profileId), payload, 'PATCH');
        const updatedProfiles = (state.subjectProfiles || []).map((profile) => {
          const matchesTopLevel = profile.profile_id === profileId;
          const matchesSource = (profile.source_profiles || []).some((source) => source.profile_id === profileId);
          return (matchesTopLevel || matchesSource) ? { ...profile, ...saved } : profile;
        });
        state.subjectProfiles = updatedProfiles;
        renderSubjectProfileValidationRows();
        closeSubjectProfileValidation();
        const statusMessage = saved.validation_status === 'validated'
          ? 'Subject profile validated and removed from the outstanding review list.'
          : `Subject profile saved as ${String(saved.validation_status || 'needs_review').replaceAll('_', ' ')}.`;
        setStatus(statusMessage, 'ok');
        showToast(statusMessage, 'success');
        await loadSubjectProfiles(false);
      } catch (error) {
        const message = `Subject profile could not be saved: ${error.message || 'validation error'}`;
        setSubjectProfileValidationModalStatus(message, 'error');
        setStatus(message, 'error');
        showToast(message, 'error');
      } finally {
        if (saveButton) {
          saveButton.disabled = false;
          saveButton.textContent = 'Save Profile Review';
        }
      }
    }
    function renderCurriculumEvidenceReviewQueue() {
      const target = $('curriculumEvidenceReviewRows');
      const summary = $('curriculumEvidenceReviewSummary');
      if (!target) return;
      const payload = state.curriculumEvidenceReviews || { items: [], counts: {} };
      const counts = payload.counts || {};
      if (summary) {
        summary.className = '';
        summary.textContent = `${payload.total || 0} document versions · ${counts.unreviewed || 0} unreviewed · ${counts.validated || 0} validated · ${counts.changes_required || 0} requiring changes · ${counts.rejected || 0} rejected`;
      }
      target.innerHTML = (payload.items || []).map((item) => {
        const latest = item.latest_review || {};
        return `<tr>
          <td><strong>${escapeHtml(item.title || item.original_filename || 'Untitled')}</strong><br><small>${escapeHtml(item.programme || 'Programme not recorded')}</small></td>
          <td>v${formatNumber(item.version_number || 0)}<br><small>${escapeHtml(item.original_filename || '')}</small></td>
          <td>${formatNumber(item.page_count || 0)} pages · ${formatNumber(item.chunk_count || 0)} chunks<br><small>${escapeHtml(item.extraction_status || 'unknown')}</small></td>
          <td>${statusBadge(item.review_status || 'unreviewed', item.review_status === 'validated' ? 'good' : 'warn')}<br><small>${formatNumber(item.review_count || 0)} review record(s)</small></td>
          <td>${escapeHtml(latest.reviewer_id || 'Not reviewed')}<br><small>${latest.completeness_score == null ? '' : `${formatNumber(latest.completeness_score)}% complete`}</small></td>
          <td><button class="btn curriculum-evidence-review-btn" data-version-id="${escapeHtml(item.version_id)}">Review Evidence</button></td>
        </tr>`;
      }).join('') || '<tr><td colspan="6">No curriculum document versions are available for validation.</td></tr>';
    }

    async function loadCurriculumEvidenceReviews() {
      state.curriculumEvidenceReviews = await getJson(
        API_ENDPOINTS.CURRICULUM.EVIDENCE_REVIEW_QUEUE,
        { items: [], counts: {} },
      );
      renderCurriculumEvidenceReviewQueue();
      setStatus('Curriculum evidence review queue refreshed.', 'ok');
    }

    const curriculumEvidenceCheckIds = [
      'curriculumEvidenceSourceAuthoritative',
      'curriculumEvidenceExtractionComplete',
      'curriculumEvidenceModulesComplete',
      'curriculumEvidenceOutcomesComplete',
    ];

    function calculatedCurriculumEvidenceCompleteness() {
      return curriculumEvidenceCheckIds.reduce((total, id) => total + ($(id)?.checked ? 25 : 0), 0);
    }

    function updateCurriculumEvidenceCompletenessScore() {
      const score = $('curriculumEvidenceReviewScore');
      if (!score) return 0;
      const calculated = calculatedCurriculumEvidenceCompleteness();
      score.value = calculated;
      const help = $('curriculumEvidenceScoreHelp');
      if (help) {
        help.textContent = `Completeness is calculated from the four checks: ${calculated / 25} of 4 selected = ${calculated}%.`;
      }
      return calculated;
    }

    function wireCurriculumEvidenceScoreControls() {
      curriculumEvidenceCheckIds.forEach((id) => {
        const checkbox = $(id);
        if (checkbox && !checkbox.dataset.scoreWired) {
          checkbox.addEventListener('change', updateCurriculumEvidenceCompletenessScore);
          checkbox.dataset.scoreWired = 'true';
        }
      });
      const decision = $('curriculumEvidenceReviewDecision');
      if (decision && !decision.dataset.scoreWired) {
        decision.addEventListener('change', () => {
          if (decision.value === 'validated') {
            updateCurriculumEvidenceCompletenessScore();
          }
        });
        decision.dataset.scoreWired = 'true';
      }
    }

    function renderCurriculumEvidenceChunkPreview(chunks) {
      const target = $('curriculumEvidenceChunkPreview');
      if (!target) return;
      if (!Array.isArray(chunks) || !chunks.length) {
        target.className = 'empty';
        target.innerHTML = 'No extracted chunks are available. Choose <strong>Changes required</strong> unless the source can be reprocessed successfully.';
        return;
      }
      target.className = '';
      target.innerHTML = `
        <div style="font-size:12px;color:#526985;margin-bottom:8px">
          Showing ${formatNumber(chunks.length)} extracted chunk(s). Review the text, page range, module/outcome clues, and completeness before validating.
        </div>
        ${chunks.map((chunk) => {
          const meta = chunk.chunk_metadata || {};
          const page = chunk.page_start || chunk.page_end
            ? `page ${escapeHtml([chunk.page_start, chunk.page_end].filter(Boolean).join('-'))}`
            : 'page not recorded';
          const moduleCode = meta.module_code || meta.module || meta.course_code || '';
          const section = meta.section || meta.heading || meta.outcome_type || '';
          const labels = [page, moduleCode && `module ${moduleCode}`, section].filter(Boolean).join(' | ');
          return `<div style="border:1px solid #d8e1ec;border-radius:10px;padding:10px;margin:8px 0;background:#fff">
            <div style="font-size:12px;color:#526985;margin-bottom:6px"><strong>Chunk ${formatNumber((chunk.chunk_index ?? 0) + 1)}</strong> - ${escapeHtml(labels)}</div>
            <div style="white-space:pre-wrap;line-height:1.45">${escapeHtml(chunk.content || '').slice(0, 2500)}</div>
          </div>`;
        }).join('')}
      `;
    }

    async function openCurriculumEvidenceReview(versionId) {
      const item = (state.curriculumEvidenceReviews?.items || []).find((entry) => entry.version_id === versionId);
      if (!item) return;
      const latest = item.latest_review || {};
      $('curriculumEvidenceReviewVersionId').value = versionId;
      $('curriculumEvidenceReviewDocument').textContent = `${item.title} - version ${item.version_number} - ${item.chunk_count || 0} evidence chunks`;
      $('curriculumEvidenceReviewDecision').value = latest.decision || 'changes_required';
      $('curriculumEvidenceReviewScore').value = latest.completeness_score ?? 0;
      $('curriculumEvidenceSourceAuthoritative').checked = Boolean(latest.source_authoritative);
      $('curriculumEvidenceExtractionComplete').checked = Boolean(latest.extraction_complete);
      $('curriculumEvidenceModulesComplete').checked = Boolean(latest.module_evidence_complete);
      $('curriculumEvidenceOutcomesComplete').checked = Boolean(latest.learning_outcomes_complete);
      wireCurriculumEvidenceScoreControls();
      updateCurriculumEvidenceCompletenessScore();
      $('curriculumEvidenceIssueCodes').value = (latest.issue_codes || item.suggested_issue_codes || []).join(', ');
      $('curriculumEvidenceReviewNotes').value = '';
      setCurriculumEvidenceReviewModalStatus('', '');
      const preview = $('curriculumEvidenceChunkPreview');
      if (preview) {
        preview.className = 'empty';
        preview.textContent = 'Loading extracted evidence chunks...';
      }
      $('curriculumEvidenceReviewModal').classList.remove('hidden');
      try {
        const chunks = await getJson(API_ENDPOINTS.CURRICULUM.VERSION_CHUNKS(versionId), []);
        renderCurriculumEvidenceChunkPreview(chunks);
      } catch (error) {
        const target = $('curriculumEvidenceChunkPreview');
        if (target) {
          target.className = 'empty';
          target.innerHTML = `Could not load extracted chunks: ${escapeHtml(error.message || 'API error')}. Choose <strong>Changes required</strong> until the evidence can be inspected.`;
        }
      }
    }

    function setCurriculumEvidenceReviewModalStatus(message = '', tone = '') {
      const target = $('curriculumEvidenceReviewModalStatus');
      if (!target) return;
      target.textContent = message;
      target.className = message ? `inline-status show ${tone || ''}`.trim() : 'inline-status';
    }

    function closeCurriculumEvidenceReview() {
      setCurriculumEvidenceReviewModalStatus('', '');
      $('curriculumEvidenceReviewModal')?.classList.add('hidden');
    }

    async function submitCurriculumEvidenceReview() {
      const versionId = $('curriculumEvidenceReviewVersionId')?.value;
      const notes = $('curriculumEvidenceReviewNotes')?.value?.trim() || '';
      if (!versionId || notes.length < 10) {
        const message = 'Please provide brief expert notes of at least 10 characters. For rejected or changes-required reviews, state what is wrong or uncertain.';
        setCurriculumEvidenceReviewModalStatus(message, 'error');
        showToast(message, 'error');
        setStatus(message, 'error');
        return;
      }
      const calculatedScore = updateCurriculumEvidenceCompletenessScore();
      const decision = $('curriculumEvidenceReviewDecision')?.value;
      if (decision === 'validated' && calculatedScore < 100) {
        const message = 'Validated evidence requires all four checks. If only 1-3 checks pass, choose Changes required instead and explain what must be fixed.';
        setCurriculumEvidenceReviewModalStatus(message, 'error');
        showToast(message, 'error');
        setStatus(message, 'error');
        return;
      }
      if (decision === 'validated') {
        const issueCodes = $('curriculumEvidenceIssueCodes');
        if (issueCodes && issueCodes.value.trim()) {
          const proceed = await showConfirm(
            'You selected Validated, but issue codes are still present. Clear issue codes for clean audit evidence unless there is still a known issue. Continue saving anyway?',
            'Validated review has issue codes',
          );
          if (!proceed) return;
        }
      }
      setCurriculumEvidenceReviewModalStatus('Saving expert review...', '');
      try {
        await postJson(API_ENDPOINTS.CURRICULUM.EVIDENCE_REVIEWS(versionId), {
          decision,
          source_authoritative: $('curriculumEvidenceSourceAuthoritative').checked,
          extraction_complete: $('curriculumEvidenceExtractionComplete').checked,
          module_evidence_complete: $('curriculumEvidenceModulesComplete').checked,
          learning_outcomes_complete: $('curriculumEvidenceOutcomesComplete').checked,
          completeness_score: calculatedScore,
          issue_codes: ($('curriculumEvidenceIssueCodes').value || '').split(',').map((value) => value.trim()).filter(Boolean),
          notes,
        });
        closeCurriculumEvidenceReview();
        await loadCurriculumEvidenceReviews();
        setStatus('Expert curriculum evidence review saved with audit history.', 'ok');
      } catch (error) {
        const message = `Evidence review could not be saved: ${error.message || 'validation error'}`;
        setCurriculumEvidenceReviewModalStatus(message, 'error');
        setStatus(message, 'error');
      }
    }

    function evidencePreview(value, maxLength = 650) {
      const text = String(value || '').replace(/\s+/g, ' ').trim();
      if (text.length <= maxLength) return text;
      const cut = text.slice(0, maxLength);
      const boundary = Math.max(cut.lastIndexOf('. '), cut.lastIndexOf('; '), cut.lastIndexOf(', '), cut.lastIndexOf(' '));
      const safeCut = boundary > Math.floor(maxLength * 0.65) ? cut.slice(0, boundary) : cut;
      return `${safeCut.trim()}...`;
    }

    function displaySourceLabel(label) {
      return label === 'ADZUNA_TRIAL_NOT_EMPIRICAL' ? 'Adzuna' : (label || '-');
    }

    function renderSkillMappingWorkbench() {
      const target = $('skillMappingReviewRows');
      const summary = $('skillMappingWorkbenchSummary');
      if (!target) return;
      const workbench = state.skillMappingWorkbench || {};
      const queueTotal = workbench.review_queue_total || 0;
      const queueOffset = workbench.review_queue_offset || 0;
      const queuePage = $('skillMappingQueuePage');
      if (queuePage) queuePage.textContent = `${queueTotal ? queueOffset + 1 : 0}-${Math.min(queueOffset + (workbench.review_queue_count || 0), queueTotal)} of ${queueTotal}`;
      if ($('skillMappingQueuePrev')) $('skillMappingQueuePrev').disabled = queueOffset === 0;
      if ($('skillMappingQueueNext')) $('skillMappingQueueNext').disabled = queueOffset + (workbench.review_queue_count || 0) >= queueTotal;
      const readiness = workbench.readiness || {};
      const counts = readiness.counts || {};
      const coverage = readiness.coverage || {};
      const statusSummary = workbench.mapping_status_summary || {};
      const bands = statusSummary.candidate_confidence_bands || {};
      const latestJob = statusSummary.latest_generation_job || null;
      const jobProgress = latestJob
        ? `${escapeHtml(latestJob.status || 'unknown')} ? ${formatNumber(latestJob.progress_current || 0)}/${formatNumber(latestJob.progress_total || 0)}${latestJob.completed_at ? ` ? completed ${new Date(latestJob.completed_at).toLocaleString()}` : ''}`
        : 'No generation job recorded yet';
      if (summary) {
        summary.className = '';
        summary.innerHTML = `<div class="kv-grid">
          <div><strong>Canonical skills</strong><span>${formatNumber(counts.active_skills || 0)}</span></div>
          <div><strong>Evidence mappings</strong><span>${formatNumber(counts.mappings || 0)}</span></div>
          <div><strong>Approved</strong><span>${formatNumber(statusSummary.approved || counts.approved_mappings || 0)}</span></div>
          <div><strong>Auto-approved</strong><span>${formatNumber(statusSummary.auto_approved || 0)}</span></div>
          <div><strong>Human review queue</strong><span>${formatNumber((statusSummary.candidate || 0) + (statusSummary.needs_review || 0))}</span></div>
          <div><strong>Rejected</strong><span>${formatNumber(statusSummary.rejected || 0)}</span></div>
          <div><strong>ESCO linked</strong><span>${percent(coverage.esco_skill_coverage || 0)} (${formatNumber(counts.esco_linked_canonical_skills || 0)})</span></div>
          <div><strong>OFO linked</strong><span>${percent(coverage.ofo_skill_coverage || 0)} (${formatNumber(counts.ofo_linked_canonical_skills || 0)})</span></div>
          <div><strong>Review history</strong><span>${formatNumber(workbench.review_history_count || 0)}</span></div>
        </div>
        <p class="muted"><strong>Latest mapping job:</strong> ${jobProgress}</p>
        <p class="muted"><strong>Remaining candidates:</strong> ${formatNumber(statusSummary.candidate || 0)} total &middot; ${formatNumber(bands.band_85_90 || 0)} between 85-90% &middot; ${formatNumber(bands.band_70_85 || 0)} between 70-85% &middot; ${formatNumber(bands.below_70 || 0)} below 70%. High-confidence >= ${percent(statusSummary.auto_approval_threshold || 0.9)} is auto-approved.</p>
        <p class="muted">${escapeHtml((readiness.issues || []).join(' ? ') || 'No mapping validity issues reported.')}</p>`;
      }
      target.innerHTML = (workbench.review_queue || []).map((item) => `<tr>
        <td><strong>${escapeHtml(item.matched_text || '-')}</strong><br><small>${escapeHtml(evidencePreview(item.evidence_text, 650))}</small></td>
        <td>${escapeHtml(item.skill_name || '-')}<br><small>${escapeHtml(item.esco_label || 'No ESCO concept linked')}</small></td>
        <td>${escapeHtml(item.source_domain || '-')}<br><small>${escapeHtml(item.job_title || 'No job title recorded')} · ${escapeHtml(displaySourceLabel(item.source_label))}</small><br><small>${escapeHtml(item.extraction_method || '-')}</small></td>
        <td>${percent(item.confidence_score || 0)}</td>
        <td>${statusBadge(item.mapping_status || 'candidate', 'warn')}</td>
        <td><button class="btn skill-mapping-review-btn" data-mapping-id="${escapeHtml(item.mapping_id)}">Review Mapping</button></td>
      </tr>`).join('') || '<tr><td colspan="6">No uncertain mappings are waiting for review. Generate evidence mappings after validated source evidence is loaded; high-confidence matches are auto-approved.</td></tr>';
      // Bind directly after each render as the Data Operations navigation can
      // move/rebuild the workbench DOM. The delegated handler in dashboard-main
      // remains as a fallback, while this guarantees that a visible review
      // button always opens the matching review dialog.
      target.querySelectorAll('.skill-mapping-review-btn').forEach((button) => {
        button.addEventListener('click', () => openSkillMappingReview(button.dataset.mappingId));
      });
    }

    async function loadSkillMappingWorkbench() {
      const status = $('skillMappingQueueStatus')?.value || 'candidate';
      const mappingId = $('skillMappingLookupId')?.value?.trim() || '';
      const offset = Math.max(0, state.skillMappingQueueOffset || 0);
      state.skillMappingWorkbench = await getJson(
        `${API_ENDPOINTS.SKILLS.GOVERNANCE_WORKBENCH}?review_status=${encodeURIComponent(status)}&offset=${offset}&limit=100${mappingId ? `&mapping_id=${encodeURIComponent(mappingId)}` : ''}`,
        { readiness: { counts: {}, coverage: {}, issues: [] }, review_queue: [] },
      );
      if (offset && offset >= (state.skillMappingWorkbench.review_queue_total || 0)) {
        state.skillMappingQueueOffset = Math.max(0, offset - 100);
        return loadSkillMappingWorkbench();
      }
      renderSkillMappingWorkbench();
      setStatus('Skill mapping workbench refreshed.', 'ok');
      loadTaxonomyProvenance();
    }

    async function archiveUnsupportedSkills() {
      const preview = await getJson(`${SKILLS_BASE}/taxonomy/cleanup-candidates`, { items: [], count: 0 });
      if (!preview.count) {
        setStatus('No unsupported inferred canonical entries were found.', 'ok');
        return;
      }
      const names = preview.items.map((item) => item.name).join(', ');
      const confirmed = await showConfirm(
        'Archive unsupported inferred skills',
        `Archive ${preview.count} unsupported inferred entries: ${names}? Only entries with no approved mappings and no ESCO link are eligible.`,
      );
      if (!confirmed) return;
      const note = 'Archived as non-skill job-category labels after all attached mappings were rejected; no ESCO concept linked.';
      const result = await postJson(`${SKILLS_BASE}/taxonomy/archive-unsupported?note=${encodeURIComponent(note)}`, {});
      setStatus(`Archived ${result.count || 0} unsupported inferred canonical entries with audit history.`, 'ok');
      await loadSkillMappingWorkbench();
    }

async function loadTaxonomyProvenance() {
      state.taxonomyProvenance = await getJson(
        `${SKILLS_BASE}/taxonomy/provenance`,
        { sources: { esco: {}, ofo: {} }, counts: {}, coverage: {}, mapping_status_summary: [], traceability: [] },
      );
      const provenancePanel = $('taxonomyProvenancePanel');
      if (provenancePanel) provenancePanel.className = '';
      if (provenancePanel) provenancePanel.innerHTML = renderTaxonomyProvenance(state.taxonomyProvenance);
      loadDhetOfoSource();
      loadDhetOfoMappings();
      loadDhetOfoStats();
      loadDhetOfoBreakdown();
    }

    function renderTaxonomyProvenance(p) {
      const esco = p?.sources?.esco || {};
      const ofo = p?.sources?.ofo || {};
      const dhet = p?.sources?.dhet_ofo || {};
      const latestAcq = dhet.latest_acquisition || {};
      const counts = p?.counts || {};
      const coverage = p?.coverage || {};
      const status = p?.mapping_status_summary || {};
      const tx = (p?.traceability || []).slice(0, 5).map((item) => `<tr>
        <td>${escapeHtml(item.source_record_id || '-')}</td>
        <td>${escapeHtml(item.extracted_text || '-')}</td>
        <td>${escapeHtml(item.method || '-')} @ ${percent(item.confidence || 0)}</td>
        <td>${escapeHtml(item.esco_skill_id || 'Not linked')}</td>
        <td>${escapeHtml(item.review_decision || 'unreviewed')}<br><small>${escapeHtml(item.reviewer || '-')}</small></td>
      </tr>`).join('') || '<tr><td colspan="5">No approved mappings yet.</td></tr>';
      const fileRows = (esco.files || []).map((f) => `<tr>
        <td>${escapeHtml(f.filename)}</td><td>${formatNumber(f.data_rows)}</td>
        <td><code>${escapeHtml(f.sha256.slice(0, 16))}…</code></td></tr>`).join('');
      return `<div class="panel-heading"><h3>Taxonomy Provenance</h3></div>
        <div class="kv-grid">
          <div><strong>ESCO source</strong><span>${escapeHtml(esco.source || 'Not recorded')}</span></div>
          <div><strong>ESCO version</strong><span>${escapeHtml(esco.version || '-')}</span></div>
          <div><strong>Licence</strong><span>${escapeHtml(esco.licence || '-')}</span></div>
          <div><strong>Recorded</strong><span>${escapeHtml(esco.recorded_at || '-')}</span></div>
          <div><strong>ESCO skills</strong><span>${formatNumber(counts.esco_total || 0)} (${formatNumber(counts.esco_linked_canonical_skills || 0)} linked)</span></div>
          <div><strong>ESCO occupations</strong><span>${formatNumber(counts.esco_occupations || 0)}</span></div>
          <div><strong>OFO status</strong><span class="badge warn">${escapeHtml((ofo.status || 'deferred').toUpperCase())}</span></div>
          <div><strong>OFO reason</strong><span>${escapeHtml(String(ofo.reason || '-'))}</span></div>
          <div><strong>Mappings</strong><span>${formatNumber(counts.mappings_total || 0)} (${formatNumber(status.approved || 0)} approved, ${formatNumber(status.candidate || 0)} candidate, ${formatNumber(status.deferred || 0)} deferred)</span></div>
          <div><strong>Decision history</strong><span>${formatNumber(p?.review_event_count || 0)} append-only events</span></div>
        </div>
        <div class="kv-grid" style="margin-top:10px">
          <div><strong>DHET OFO source</strong><span>${escapeHtml((dhet.profile?.name || 'Not registered').slice(0, 64))}</span></div>
          <div><strong>DHET OFO status</strong><span class="badge warn">${escapeHtml(String(latestAcq.status || ofo.status || 'deferred').toUpperCase())}</span></div>
          <div><strong>OFO version</strong><span>${escapeHtml(ofo.version || latestAcq.version || '-')}</span></div>
          <div><strong>Acquisitions recorded</strong><span>${formatNumber(dhet.acquisition_count || 0)}</span></div>
          <div><strong>DHET checksum</strong><span><code>${latestAcq.sha256 ? escapeHtml(latestAcq.sha256.slice(0, 20)) + '…' : 'not acquired'}</code></span></div>
          <div><strong>OFO occupations</strong><span>${formatNumber(counts.ofo_occupations || 0)} (${Object.entries(counts.ofo_occupation_by_version || {}).map(([v, c]) => `${escapeHtml(v)}: ${formatNumber(c)}`).join(' · ') || 'none imported'})</span></div>
        </div>
        <details style="margin-top:10px"><summary>ESCO distribution files (${esco.files?.length || 0} · checksums)</summary>
          <table class="table"><thead><tr><th>File</th><th>Rows</th><th>SHA-256</th></tr></thead><tbody>${fileRows}</tbody></table></details>
        <h4>Traceability sample (source record → extracted skill → ESCO → decision)</h4>
        <table class="table"><thead><tr><th>Source record</th><th>Extracted text</th><th>Method @ conf</th><th>ESCO id</th><th>Decision / reviewer</th></tr></thead><tbody>${tx}</tbody></table>`;
    }

    // ---- DHET OFO 2021 controlled acquisition + evidence mapping ----
    const API_BASE = API_ENDPOINTS.SKILLS.GOVERNANCE_WORKBENCH.replace('/skills/governance/workbench', '');
    const DHET_BASE = `${API_BASE}/dhet-ofo`;

    async function loadDhetOfoSource() {
      state.dhetOfo = await getJson(
        `${DHET_BASE}/source`,
        { source: {}, latest_acquisition: null, acquisitions: [], import_summary: null, occupation_counts_by_version: {} },
      );
      renderDhetOfoSource();
      loadDhetOfoCanonicalSkills();
    }

    async function loadDhetOfoCanonicalSkills() {
      const select = $('dhetOfoCanonicalSkill');
      if (!select) return;
      const skills = await getJson(`${API_ENDPOINTS.SKILLS.LIST}?limit=500`, []);
      select.innerHTML = '<option value="">Select canonical skill</option>' + skills
        .filter((skill) => (skill.status || 'active') === 'active')
        .sort((a, b) => String(a.name).localeCompare(String(b.name)))
        .map((skill) => `<option value="${escapeHtml(skill.skill_id)}">${escapeHtml(skill.name)}</option>`).join('');
    }

    function renderDhetOfoSource() {
      const panel = $('dhetOfoSourcePanel');
      if (!panel) return;
      const src = state.dhetOfo || {};
      const profile = src.source || {};
      const lat = src.latest_acquisition || null;
      const imp = src.import_summary || null;
      panel.className = '';
      panel.innerHTML = `
        <div class="kv-grid">
          <div><strong>Authority / source</strong><span>${escapeHtml(profile.authority || '-')} · ${escapeHtml(String(profile.name || '-').slice(0, 84))}</span></div>
          <div><strong>Version</strong><span>${escapeHtml(profile.version || '-')}</span></div>
          <div><strong>Status</strong><span class="badge ${lat?.status === 'imported' ? '' : 'warn'}">${escapeHtml(String(lat?.status || profile.status || 'pending_validation').toUpperCase())}</span></div>
          <div><strong>Latest SHA-256</strong><span>${lat ? `<code>${escapeHtml(lat.sha256.slice(0, 20))}…</code>` : '<code>not acquired</code>'}</span></div>
          <div><strong>Imported occupations (2021)</strong><span>${formatNumber(imp?.occupations ?? 0)}</span></div>
          <div><strong>Imported version / checksum</strong><span>${imp ? `${escapeHtml(imp.version || '-')} · <code>${escapeHtml(String(imp.sha256 || '').slice(0, 16))}…</code>` : 'not imported'}</span></div>
          <div><strong>Source page</strong><span><code>${escapeHtml(profile.source_page_url || '')}</code></span></div>
          <div><strong>Evidence path</strong><span><code>${escapeHtml(profile.evidence_path || 'data/evidence/dhet_ofo_2021')}</code></span></div>
        </div>
        ${lat ? `<p class="muted" style="margin-top:8px"><strong>Latest acquisition (${escapeHtml(lat.method)}):</strong> ${escapeHtml(lat.status || '')}${lat.content_type ? ` · ${escapeHtml(lat.content_type)}` : ''}${lat.byte_size ? ` · ${formatFileSize(lat.byte_size)}` : ''}${lat.note ? ` · ${escapeHtml(lat.note)}` : ''}</p>` : ''}
        ${imp ? `<p class="muted"><strong>Import:</strong> version ${escapeHtml(imp.version || '-')}, ${formatNumber(imp.occupations || 0)} occupations, checksum <code>${escapeHtml(String(imp.sha256 || '').slice(0, 20))}…</code> at ${escapeHtml(imp.imported_at || '-')}</p>` : ''}`;
      renderDhetOfoAcquisitions(src.acquisitions || []);
    }

    function renderDhetOfoAcquisitions(list) {
      const rowsEl = $('dhetOfoAcquisitionRows');
      if (!rowsEl) return;
      rowsEl.innerHTML = (list || []).map((a) => `<tr>
        <td>${escapeHtml(a.method || '-')}</td>
        <td>${escapeHtml(a.retrieved_at ? new Date(a.retrieved_at).toLocaleString() : '-')}</td>
        <td>${escapeHtml(a.http_status != null ? String(a.http_status) : '-')}</td>
        <td>${formatFileSize(a.byte_size || 0)}</td>
        <td><code>${escapeHtml(String(a.sha256 || '').slice(0, 20))}…</code></td>
        <td>${escapeHtml(a.version || '-')}</td>
        <td>${statusBadge(a.status || 'pending_validation', 'warn')}</td>
        <td>
          ${(a.method === 'upload' || a.method === 'download')
            ? `<button class="btn dhet-validate-btn" data-acq-id="${escapeHtml(a.acquisition_id)}" ${a.status === 'validated' || a.status === 'imported' ? 'disabled' : ''}>Validate</button> <button class="btn primary dhet-import-btn" data-acq-id="${escapeHtml(a.acquisition_id)}" ${a.status === 'imported' ? 'disabled' : ''}>Import</button>`
            : `<span class="muted">${escapeHtml(a.status === 'discovered' ? 'discovery record' : 'no import')}</span>`}
        </td>
      </tr>`).join('') || '<tr><td colspan="8" class="muted">No acquisition provenance recorded yet. Run discovery, confirm &amp; download, or upload manually.</td></tr>';
    }

    async function discoverDhetOfo() {
      setStatus('Discovering the official DHET OFO workbook URL (single allowlist fetch)...', 'ok');
      const result = await getJson(`${DHET_BASE}/discovery`, { status: 'unresolved', candidate_urls: [], message: 'Discovery unavailable.' });
      setStatus(`DHET discovery: ${result.message || result.status}`, result.status === 'discovered' ? 'ok' : 'warn');
      loadDhetOfoSource();
    }

    async function downloadDhetOfo() {
      const confirmed = $('dhetOfoConfirmCheck')?.checked;
      if (!confirmed) return;
      const btn = $('downloadDhetOfoBtn');
      if (btn) btn.disabled = true;
      try {
        const result = await postJson(`${DHET_BASE}/download`, { confirmed: true });
        setStatus(`DHET download: ${result.message || result.status}`, result.status === 'rejected' ? 'error' : 'ok');
      } catch (error) {
        setStatus(`DHET download refused: ${error.message || 'request failed'}`, 'error');
      } finally {
        loadDhetOfoSource();
      }
    }

    async function uploadDhetOfo() {
      const input = $('dhetOfoFileInput');
      const file = input?.files?.[0];
      if (!file) { setStatus('Choose an OFO workbook file to upload.', 'error'); return; }
      const form = new FormData();
      form.append('file', file, file.name);
      try {
        const result = await postForm(`${DHET_BASE}/upload`, form);
        setStatus(`DHET upload recorded (SHA-256 ${String(result.acquisition?.sha256 || '').slice(0, 16)}…): ${result.message || result.status}`, 'ok');
      } catch (error) {
        setStatus(`DHET upload failed: ${error.message || 'request failed'}`, 'error');
      }
      input.value = '';
      loadDhetOfoSource();
    }

    async function validateDhetOfo(acquisitionId) {
      try {
        const result = await postJson(`${DHET_BASE}/acquisitions/${acquisitionId}/validate`, {});
        setStatus(
          result.valid
            ? `Workbook validated: ${formatNumber(result.data_rows)} six-digit rows, version ${result.detected_version || '-'}.`
            : `Validation rejected: ${(result.errors || []).join(' ')}`,
          result.valid ? 'ok' : 'error',
        );
      } catch (error) {
        setStatus(`Validation failed: ${error.message || 'request failed'}`, 'error');
      }
      loadDhetOfoSource();
    }

    async function importDhetOfo(acquisitionId) {
      try {
        const result = await postJson(`${DHET_BASE}/acquisitions/${acquisitionId}/import`, {});
        const counts = result.counts || {};
        setStatus(`OFO import complete: ${formatNumber(counts.created)} new, ${formatNumber(counts.updated)} updated, ${formatNumber(counts.occupations)} occupations, version ${result.version || '-'}.`, 'ok');
      } catch (error) {
        setStatus(`OFO import failed: ${error.message || 'request failed'}`, 'error');
      }
      loadDhetOfoSource();
      loadTaxonomyProvenance();
      loadDhetOfoBreakdown();
    }

    async function loadDhetOfoMappings() {
      state.dhetOfoMappings = asItems(await getJson(`${DHET_BASE}/mappings`, []));
      renderDhetOfoMappings();
    }

    async function loadDhetOfoStats() {
      state.dhetOfoStats = await getJson(`${DHET_BASE}/stats`, { mappings: {}, acquisition: {} });
      renderDhetOfoMappings();
    }

    async function loadDhetOfoBreakdown() {
      state.dhetOfoBreakdown = await getJson(
        `${DHET_BASE}/breakdown`,
        { total_occupations_in_reference_tables: 0, reconciles: false, occupations_by_code_length: {}, occupations_by_acquisition: [], unattributed_rows: 0 },
      );
      renderDhetOfoBreakdown();
    }

    function renderDhetOfoBreakdown() {
      const summaryEl = $('dhetOfoBreakdownSummary');
      const lengthRowsEl = $('dhetOfoBreakdownLengthRows');
      const acqRowsEl = $('dhetOfoBreakdownAcqRows');
      const b = state.dhetOfoBreakdown || {};
      const total = b.total_occupations_in_reference_tables ?? 0;
      const LEVEL_LABELS = {
        major_group: 'Major group',
        sub_major_group: 'Sub-major group',
        minor_group: 'Minor group',
        unit_group: 'Unit group',
        occupation: 'Occupation (6-digit)',
      };
      const LEVEL_LEN = {
        major_group: '1 digit',
        sub_major_group: '2 digits',
        minor_group: '3 digits',
        unit_group: '4 digits',
        occupation: '6 digits',
      };
      if (summaryEl) {
        summaryEl.className = '';
        const lengthSum = Object.values(b.occupations_by_code_length || {}).reduce((a, c) => a + (c || 0), 0);
        const acqSum = (b.occupations_by_acquisition || []).reduce((a, x) => a + (x.rows_present_now || 0), 0) + (b.unattributed_rows || 0);
        summaryEl.innerHTML = `<div class="kv-grid">
          <div><strong>Total reference rows</strong><span>${formatNumber(total)}</span></div>
          <div><strong>Reconciles</strong><span class="badge ${b.reconciles ? '' : 'warn'}">${b.reconciles ? 'YES' : 'NO'}</span></div>
          <div><strong>Code-length sum</strong><span>${formatNumber(lengthSum)} ${lengthSum === total ? '✓' : '✗'}</span></div>
          <div><strong>Acquisition sum</strong><span>${formatNumber(acqSum)} ${acqSum === total ? '✓' : '✗'}</span></div>
          <div><strong>Unattributed rows</strong><span>${formatNumber(b.unattributed_rows || 0)}</span></div>
          <div><strong>Unclassified codes</strong><span>${formatNumber(b.unclassified_codes || 0)}</span></div>
        </div>
        <p class="muted" style="margin-top:6px">${escapeHtml(b.measurement_note || '')}</p>`;
      }
      if (lengthRowsEl) {
        const entries = Object.entries(b.occupations_by_code_length || {});
        lengthRowsEl.innerHTML = entries.map(([key, count]) => `<tr>
          <td>${escapeHtml(LEVEL_LABELS[key] || key)}</td>
          <td>${escapeHtml(LEVEL_LEN[key] || '-')}</td>
          <td>${formatNumber(count)}</td>
        </tr>`).join('') || '<tr><td colspan="3" class="muted">No OFO rows imported yet.</td></tr>';
        if (entries.length) {
          lengthRowsEl.innerHTML += `<tr><td colspan="2"><strong>Total</strong></td><td><strong>${formatNumber(total)}</strong></td></tr>`;
        }
      }
      if (acqRowsEl) {
        acqRowsEl.innerHTML = (b.occupations_by_acquisition || []).map((a) => `<tr>
          <td><code>${escapeHtml(String(a.acquisition_id || '').slice(0, 18))}…</code></td>
          <td>${escapeHtml(a.acquisition_type || '-')}</td>
          <td>${escapeHtml(a.method || '-')}</td>
          <td>${escapeHtml((a.versions || []).join(', ') || '-')}</td>
          <td>${formatNumber(a.rows_present_now || 0)} <small class="muted">(${formatNumber(a.six_digit_rows_present_now || 0)} 6-digit)</small></td>
          <td>${a.rows_imported_at_import != null ? formatNumber(a.rows_imported_at_import) : '-'}</td>
          <td>${a.discrepancy_note ? `<small class="muted">${escapeHtml(a.discrepancy_note)}</small>` : '<span class="muted">matches import</span>'}</td>
        </tr>`).join('') || '<tr><td colspan="7" class="muted">No acquisition lineage recorded yet.</td></tr>';
      }
    }

    function renderDhetOfoMappings() {
      const rowsEl = $('dhetOfoMappingRows');
      const summaryEl = $('dhetOfoMappingSummary');
      const stats = state.dhetOfoStats || {};
      if (rowsEl) rowsEl.innerHTML = (state.dhetOfoMappings || []).map((m) => `<tr>
        <td>${escapeHtml(String(m.matched_text || '').slice(0, 140))}${(m.matched_text || '').length > 140 ? '…' : ''}${m.title_only ? '<br><span class="muted">title-only probe (never approvable)</span>' : ''}${m.defer_reason ? `<br><small class="muted">${escapeHtml(String(m.defer_reason).slice(0, 140))}</small>` : ''}</td>
        <td>${m.ofo_code ? `<strong>${escapeHtml(m.ofo_code)}</strong> ${escapeHtml(m.occupation_title || '')}` : '<span class="muted">unresolved / deferred</span>'}<br><small>version ${escapeHtml(m.version || '2021')}</small></td>
        <td>${escapeHtml(m.method || '-')}${m.confidence_score != null ? ` @ ${percent(m.confidence_score)}` : ''}</td>
        <td>${statusBadge(m.mapping_status || 'candidate', 'warn')}</td>
        <td><button class="btn dhet-mapping-review-btn" data-mapping-id="${escapeHtml(m.mapping_id)}">Review</button></td>
      </tr>`).join('') || '<tr><td colspan="5" class="muted">No OFO evidence mappings yet. Propose mappings only from full advert/evidence content.</td></tr>';
      if (summaryEl) summaryEl.className = '';
      if (summaryEl) summaryEl.innerHTML = `<div class="kv-grid" style="margin-bottom:8px">
        <div><strong>OFO evidence mappings</strong><span>${formatNumber(stats.mappings?.total ?? 0)}</span></div>
        <div><strong>Approved</strong><span>${formatNumber(stats.mappings?.status_counts?.approved ?? 0)}</span></div>
        <div><strong>Rejected</strong><span>${formatNumber(stats.mappings?.status_counts?.rejected ?? 0)}</span></div>
        <div><strong>Deferred / unresolved</strong><span>${formatNumber((stats.mappings?.status_counts?.deferred ?? 0) + (stats.mappings?.status_counts?.candidate ?? 0) + (stats.mappings?.status_counts?.needs_review ?? 0))}</span></div>
        <div><strong>Title-only probes (excluded)</strong><span>${formatNumber(stats.mappings?.title_only_probes ?? 0)}</span></div>
        <div><strong>OFO occupations by version</strong><span>${Object.entries(stats.acquisition?.occupation_counts_by_version || {}).map(([v, c]) => `${escapeHtml(v)}: ${formatNumber(c)}`).join(' · ') || 'none imported'}</span></div>
      </div>`;
    }

    async function proposeDhetOfoMapping() {
      const payload = {
        canonical_skill_id: $('dhetOfoCanonicalSkill')?.value || null,
        source_domain: 'labour_market',
        source_entity_type: 'job_posting',
        matched_text: $('dhetOfoEvidenceTitle')?.value || '',
        duties_text: $('dhetOfoEvidenceDuties')?.value || '',
        education_text: $('dhetOfoEvidenceEducation')?.value || '',
        experience_text: $('dhetOfoEvidenceExperience')?.value || '',
        skills_text: $('dhetOfoEvidenceSkills')?.value || '',
        version: '2021',
      };
      if (!payload.canonical_skill_id) {
        setStatus('Select the canonical skill being linked to OFO evidence.', 'error');
        return;
      }
      if (!(payload.matched_text || payload.duties_text || payload.education_text || payload.experience_text || payload.skills_text).trim()) {
        setStatus('Provide evidence text before proposing a mapping.', 'error');
        return;
      }
      try {
        const mapping = await postJson(`${DHET_BASE}/mappings`, payload);
        setStatus(
          `OFO mapping proposed: ${mapping.mapping_status}${mapping.ofo_code ? ` · ${mapping.ofo_code} ${mapping.occupation_title || ''}` : mapping.defer_reason ? ' · deferred (unresolved)' : ''}.`,
          mapping.mapping_status === 'deferred' ? 'warn' : 'ok',
        );
        $('dhetOfoEvidenceTitle').value = '';
        $('dhetOfoEvidenceDuties').value = '';
        $('dhetOfoEvidenceEducation').value = '';
        $('dhetOfoEvidenceExperience').value = '';
        $('dhetOfoEvidenceSkills').value = '';
        $('dhetOfoCanonicalSkill').value = '';
      } catch (error) {
        setStatus(`Mapping proposal failed: ${error.message || 'request failed'}`, 'error');
      }
      loadDhetOfoMappings();
      loadDhetOfoStats();
    }

    function openDhetOfoReview(mappingId) {
      const item = (state.dhetOfoMappings || []).find((m) => m.mapping_id === mappingId);
      if (!item) return;
      $('dhetOfoReviewId').value = mappingId;
      $('dhetOfoReviewEvidence').textContent = `"${String(item.matched_text || '').slice(0, 220)}" → ${item.ofo_code ? `${item.ofo_code} ${item.occupation_title || ''}` : 'unresolved / deferred'}`;
      $('dhetOfoReviewDecision').value = 'approved';
      $('dhetOfoReviewCode').value = item.ofo_code || '';
      $('dhetOfoReviewNote').value = '';
      const historyEl = $('dhetOfoReviewHistory');
      if (historyEl) historyEl.innerHTML = 'Loading...';
      getJson(`${DHET_BASE}/mappings/${mappingId}/history`, null).then((detail) => {
        if (!historyEl) return;
        const rows = (detail?.history || []).map((event) => `<div class="line" style="border-bottom:1px dashed var(--border,#ddd);padding:6px 0">
          <strong>${escapeHtml(event.decision)}</strong> ${event.previous_status} → ${detail.mapping_status}<br>
          <small>${escapeHtml(event.note)}<br>reviewer ${escapeHtml(event.reviewer_id || 'system')} · ${event.timestamp ? new Date(event.timestamp).toLocaleString() : 'unknown'}${event.ofo_code_after ? ` · OFO code ${event.ofo_code_before || '-'} → ${event.ofo_code_after}` : ''}</small>
        </div>`).join('') || '<div class="line muted">No prior decisions for this OFO mapping.</div>';
        historyEl.innerHTML = rows + `<div class="line" style="padding-top:6px"><button class="btn" data-history-export data-event-ids='${JSON.stringify(detail?.audit_ids || [])}'>Export Decision History</button></div>`;
        historyEl.querySelector('[data-history-export]')?.addEventListener('click', () => {
          download(`ofo-mapping-${mappingId}-decision-history.json`, JSON.stringify(detail, null, 2), 'application/json');
        });
      }).catch((error) => {
        if (historyEl) historyEl.innerHTML = `<div class="line muted">Decision history unavailable: ${error.message || 'request failed'}</div>`;
      });
      $('dhetOfoReviewModal').classList.remove('hidden');
    }

    async function submitDhetOfoReview() {
      const mappingId = $('dhetOfoReviewId')?.value;
      if (!mappingId) return;
      const decision = $('dhetOfoReviewDecision')?.value || 'approved';
      const payload = {
        decision,
        note: $('dhetOfoReviewNote')?.value?.trim() || '',
        selected_ofo_code: $('dhetOfoReviewCode')?.value?.trim() || null,
      };
      if (payload.note.length < 10) { setStatus('Provide a review note of at least 10 characters.', 'error'); return; }
      try {
        const mapping = await postJson(`${DHET_BASE}/mappings/${mappingId}/review`, payload);
        setStatus(`OFO review saved: ${decision} → ${mapping.mapping_status}.`, 'ok');
        closeDhetOfoReview();
      } catch (error) {
        setStatus(`OFO review failed: ${error.message || 'request failed'}`, 'error');
      }
      loadDhetOfoMappings();
      loadDhetOfoStats();
    }

    function closeDhetOfoReview() {
      $('dhetOfoReviewModal')?.classList.add('hidden');
    }

    function openSkillMappingReview(mappingId) {
      const item = (state.skillMappingWorkbench?.review_queue || []).find((entry) => entry.mapping_id === mappingId)
        || { matched_text: 'Mapping evidence', skill_name: 'Selected canonical skill', esco_label: '', job_title: '' };
      $('skillMappingReviewId').value = mappingId;
      $('skillMappingReviewEvidence').textContent = `"${item.matched_text}" → ${item.skill_name}${item.esco_label ? ` / ESCO: ${item.esco_label}` : ''}${item.job_title ? ` · ${item.job_title}` : ''}`;
      $('skillMappingReviewDecision').value = 'approved';
      $('skillMappingReviewNote').value = '';
      const historyEl = $('skillMappingReviewHistory');
      if (historyEl) historyEl.innerHTML = 'Loading...';
      getJson(`${SKILLS_BASE}/mappings/${mappingId}/history`, null).then((detail) => {
        if (historyEl) {
          const rows = (detail?.history || []).map((event) => `<div class="line" style="border-bottom:1px dashed var(--border,#ddd);padding:6px 0">
            <strong>${escapeHtml(event.decision)}</strong> ${event.previous_status} → ${detail.mapping_status}<br>
            <small>${escapeHtml(event.note)}<br>reviewer ${escapeHtml(event.reviewer_id || 'system')} · ${event.timestamp ? new Date(event.timestamp).toLocaleString() : 'unknown'}</small>
          </div>`).join('') || '<div class="line muted">No prior review decisions for this mapping.</div>';
          historyEl.innerHTML = rows + `<div class="line" style="padding-top:6px"><button class="btn" data-history-export data-event-ids='${JSON.stringify(detail?.audit_ids || [])}' title="Download the append-only audit trail">Export Decision History</button></div>`;
          historyEl.querySelector('[data-history-export]')?.addEventListener('click', () => {
            download(`mapping-${mappingId}-decision-history.json`, JSON.stringify(detail, null, 2), 'application/json');
          });
        }
      }).catch((error) => {
        if (historyEl) historyEl.innerHTML = `<div class="line muted">Decision history unavailable: ${error.message || 'request failed'}</div>`;
      });
      $('skillMappingReviewModal').classList.remove('hidden');
    }

    function closeSkillMappingReview() {
      $('skillMappingReviewModal')?.classList.add('hidden');
    }

    async function submitSkillMappingReview() {
      const mappingId = $('skillMappingReviewId')?.value;
      const note = $('skillMappingReviewNote')?.value?.trim() || '';
      if (!mappingId || note.length < 10) {
        setStatus('Please provide a mapping review note of at least 10 characters.', 'error');
        return;
      }
      try {
        await postJson(API_ENDPOINTS.SKILLS.MAPPING_REVIEW(mappingId), {
          decision: $('skillMappingReviewDecision').value,
          note,
        });
        closeSkillMappingReview();
        await loadSkillMappingWorkbench();
        setStatus('Skill mapping review saved with immutable history.', 'ok');
      } catch (error) {
        setStatus(`Mapping review could not be saved: ${error.message || 'validation error'}`, 'error');
      }
    }

    async function generateSkillMappings() {
      const confirmed = await showConfirm(
        'Generate Evidence Mappings',
        'Extract skill mappings from the current curriculum and labour-market evidence? High-confidence matches will be auto-approved with audit metadata; uncertain matches remain in the human review queue.',
      );
      if (!confirmed) return;
      setStatus('Generating evidence mappings and auto-approving high-confidence matches...');
      try {
        const result = await postJson(API_ENDPOINTS.SKILLS.EXTRACT_EVIDENCE_JOB, {});
        await refreshOperationalJobs();
        startIngestionMonitor();
        const job = result.operational_job || {};
        setStatus(`Skill mapping extraction queued as job ${String(job.job_id || '').slice(0, 8)}. It will continue on the server.`, 'ok');
      } catch (error) {
        setStatus(`Skill mapping generation failed: ${error.message || 'processing error'}`, 'error');
      }
    }

    function renderAlignmentLabelQueue() {
      const target = $('alignmentLabelTaskRows');
      const summary = $('alignmentLabelQualitySummary');
      if (!target) return;
      const queue = state.alignmentLabelQueue || {};
      const statuses = queue.status_counts || {};
      const snapshotTarget = $('alignmentLabelSnapshotSummary');
      if (summary) {
        summary.className = '';
        const modeIsUat = (queue.filters?.dataset_mode || state.alignmentLabelSnapshot?.dataset_mode) === 'technical_uat_researcher_operated';
        summary.innerHTML = `<div class="kv-grid">
          <div><strong>Review tasks</strong><span>${formatNumber(queue.total_tasks || 0)}</span></div>
          <div><strong>Independent labels</strong><span>${formatNumber(queue.total_labels || 0)}</span></div>
          <div><strong>Paired reviews</strong><span>${formatNumber(queue.paired_reviews || 0)}</span></div>
          <div><strong>Agreement</strong><span>${queue.agreement_rate == null ? 'Not available' : percent(queue.agreement_rate)}</span></div>
          <div><strong>Adjudication queue</strong><span>${formatNumber(statuses.adjudication_required || 0)}</span></div>
          <div><strong>Completed</strong><span>${formatNumber(statuses.completed || 0)}</span></div>
        </div><p class="muted">Generated model scores are never shown to reviewers or used as labels.</p>${modeIsUat
          ? '<p class="muted" style="color:#b26a00">Current operation mode: <code>technical_uat_researcher_operated</code> — researcher-operated UAT personas, NOT independent experts. An <code>independent_expert_validation</code> dataset mode is reserved for future real expert review.</p>'
          : ''}`;
      }
      if (snapshotTarget) {
        const snapshot = state.alignmentLabelSnapshot;
        snapshotTarget.className = snapshot ? '' : 'empty';
        snapshotTarget.innerHTML = snapshot
          ? `<strong>Locked dataset:</strong> ${escapeHtml(snapshot.snapshot_version)} · ${formatNumber(snapshot.row_count)} rows · fingerprint <code>${escapeHtml(String(snapshot.dataset_fingerprint || '').slice(0, 16))}</code> · ${escapeHtml(snapshot.lifecycle_state)}${snapshot.dataset_mode === 'technical_uat_researcher_operated'
              ? ' · <span style="color:#b26a00">mode technical_uat_researcher_operated (UAT personas, NOT independent expert labels)</span>'
              : ''}`
          : 'No locked reviewed-label dataset exists. Complete paired UAT reviews before locking.';
      target.innerHTML = (queue.items || []).map((task) => {
        const metadata = task.evidence_metadata || {};
        const stage = task.status === 'awaiting_first_review' ? 'First independent review'
          : task.status === 'awaiting_second_review' ? 'Second independent review'
          : 'Third-person adjudication';
        return `<tr>
          <td><strong>${escapeHtml(metadata.document_title || 'Curriculum evidence')}</strong><br><small>${escapeHtml(metadata.alignment_task_granularity === 'subject_module_skill_profile' ? 'Subject/module skill profile' : [metadata.programme, metadata.module_code, metadata.section, metadata.page_start ? `page ${metadata.page_start}` : ''].filter(Boolean).join(' | '))}</small><br><small>${escapeHtml(evidencePreview(task.curriculum_evidence, 450))}</small></td>
          <td>${statusBadge(stage, task.status === 'adjudication_required' ? 'warn' : 'info')}</td>
          <td>${(task.labels || []).map((label) => label.decision_hidden ? `${escapeHtml(label.review_stage)}: submitted (decision hidden)` : `${escapeHtml(label.review_stage)}: ${formatNumber(label.alignment_label)}/5`).join('<br>') || 'None yet'}</td>
          <td>${formatNumber((task.labour_market_evidence || []).length)} signals<br><small>${escapeHtml(String(task.evidence_metadata?.label_definition || ''))}</small></td>
          <td><button class="btn alignment-label-task-btn" data-task-id="${escapeHtml(task.task_id)}">Open Review</button></td>
        </tr>`;
      }).join('') || (queue.total_tasks === 0
        ? '<tr><td colspan="5">No eligible tasks. A curriculum version must first be independently validated by a curriculum expert before alignment review tasks can be generated.</td></tr>'
        : (statuses.completed || 0) === queue.total_tasks
          ? '<tr><td colspan="5">All ' + formatNumber(queue.total_tasks) + ' alignment review tasks are complete: two independent labels per task were recorded and disagreements were adjudicated before locking.</td></tr>'
          : '<tr><td colspan="5">No review tasks remain for this reviewer. Pending tasks are already labelled by the current reviewer or wait on another independent reviewer.</td></tr>');
    }
    }

    async function loadAlignmentLabelQueue() {
      state.alignmentLabelQueue = await getJson(
        API_ENDPOINTS.ALIGNMENT_LABELS.TASKS,
        { items: [], total_tasks: 0, total_labels: 0, status_counts: {} },
      );
      const snapshotPayload = await getJson(
        API_ENDPOINTS.ALIGNMENT_LABELS.LATEST_SNAPSHOT,
        { latest: null },
      );
      state.alignmentLabelSnapshot = snapshotPayload.latest || null;
      renderAlignmentLabelQueue();
      if ($('xgboostDatasetReadiness')) {
        await loadXgboostTrainReadiness();
      }
      setStatus('Independent alignment label queue refreshed.', 'ok');
    }

    async function lockAlignmentLabelSnapshot() {
      const confirmed = await showConfirm(
        'Lock Reviewed Dataset',
        'Create an immutable content-addressed dataset from all completed alignment reviews (current operation mode: technical UAT research)? Locked rows cannot be edited or deleted.',
      );
      if (!confirmed) return;
      try {
        const snapshot = await postJson(
          `${API_ENDPOINTS.ALIGNMENT_LABELS.LOCK_SNAPSHOT}?dataset_mode=technical_uat_researcher_operated`,
          {},
        );
        state.alignmentLabelSnapshot = snapshot;
        if ($('xgboostDatasetReadiness')) {
          await loadXgboostTrainReadiness();
        } else {
          renderAlignmentLabelQueue();
        }
        setStatus(`Reviewed-label dataset locked: ${String(snapshot.dataset_fingerprint || '').slice(0, 16)}.`, 'ok');
      } catch (error) {
        setStatus(`Dataset could not be locked: ${error.message || 'no eligible completed labels'}`, 'error');
      }
    }

    async function generateAlignmentTasks() {
      const granularity = String($('alignmentTaskGranularity')?.value || 'subject_module_skill');
      try {
        const result = await postJson(
          `${API_ENDPOINTS.ALIGNMENT_LABELS.GENERATE_TASKS}?limit=${granularity === 'evidence_chunk_skill' ? 2000 : 500}&dataset_mode=technical_uat_researcher_operated&granularity=${encodeURIComponent(granularity)}`,
          {},
        );
        await loadAlignmentLabelQueue();
        setStatus(
          result.created
            ? `${formatNumber(result.created)} alignment review task(s) created at ${granularity.replaceAll('_', ' ')} granularity.`
            : `No tasks created: ${result.reason || 'no eligible evidence'}`,
          result.created ? 'ok' : 'error',
        );
      } catch (error) {
        setStatus(`Alignment tasks could not be generated: ${error.message || 'API error'}`, 'error');
      }
    }

    async function buildAlignmentSample() {
      const targetSize = Number($('alignmentSampleSize')?.value) || 12;
      const seed = String($('alignmentSampleSeed')?.value || '').trim() || 'uat-researcher-sample-2026-09-12';
      try {
        const result = await postJson(
          `${API_ENDPOINTS.ALIGNMENT_LABELS.SAMPLE}?target_size=${targetSize}&dataset_mode=technical_uat_researcher_operated&sample_seed=${encodeURIComponent(seed)}`,
          {},
        );
        await loadAlignmentLabelQueue();
        setStatus(
          `UAT sample built: ${formatNumber(result.selected_count)} tasks assigned to ${(result.assigned_reviewers || []).join(' + ')} across ${formatNumber((result.strata || []).length)} strata (seed ${escapeHtml(String(result.sample_seed || ''))}).`,
          'ok',
        );
      } catch (error) {
        setStatus(`Sample could not be built: ${error.message || 'API error'}`, 'error');
      }
    }

    async function exportAlignmentLabelSnapshot() {
      const snapshot = state.alignmentLabelSnapshot;
      if (!snapshot) {
        setStatus('No locked reviewed-label dataset to export. Lock the dataset first.', 'error');
        return;
      }
      try {
        const response = await auth.fetch(`${API_ENDPOINTS.ALIGNMENT_LABELS.SNAPSHOT_EXPORT(snapshot.snapshot_id)}?format=csv`);
        if (!response.ok) {
          const detail = await response.text().catch(() => '');
          throw new Error(`export failed (${response.status}): ${detail.slice(0, 200)}`);
        }
        const text = await response.text();
        download(
          `alignment-labels-${String(snapshot.snapshot_version || 'snapshot').replace(/[^A-Za-z0-9._-]+/g, '_')}.csv`,
          text,
          'text/csv',
        );
        setStatus(`Exported reviewed-label snapshot ${escapeHtml(snapshot.snapshot_version)} as CSV.`, 'ok');
      } catch (error) {
        setStatus(`Snapshot export failed: ${error.message || 'API error'}`, 'error');
      }
    }

    let assistedLabelPreview = null;

    function renderAssistedLabelPreview() {
      const summary = $('assistedLabelSummary');
      const rows = $('assistedLabelRows');
      const confirmButton = $('confirmAssistedLabelsBtn');
      if (!summary || !rows || !assistedLabelPreview) return;
      const preview = assistedLabelPreview;
      const distribution = Object.entries(preview.class_distribution || {})
        .map(([label, count]) => `${label}: ${formatNumber(count)}`).join(' | ');
      summary.className = '';
      summary.innerHTML = `<strong>${formatNumber(preview.selected_count || 0)} proposals</strong> from ${formatNumber(preview.candidate_count || 0)} eligible tasks. Class distribution ${escapeHtml(distribution || 'none')}. Rule <code>${escapeHtml(preview.rule_version || '')}</code>. Preview fingerprint <code>${escapeHtml(String(preview.proposal_fingerprint || '').slice(0, 16))}</code>.`;
      rows.innerHTML = (preview.items || []).slice(0, 500).map((item) => `<tr>
        <td><input type="checkbox" class="assisted-label-checkbox" value="${escapeHtml(item.task_id)}"></td>
        <td><strong>${escapeHtml(item.subject_code || 'Curriculum evidence')}</strong><br><small>${escapeHtml(item.module_key || '')}</small><br><small>${escapeHtml(item.evidence_preview || '')}</small></td>
        <td>${escapeHtml(item.target_skill || 'Not recorded')}</td>
        <td><strong>${formatNumber(item.proposed_label)}/5</strong><br><small>confidence ${formatNumber(item.confidence)}/5</small></td>
        <td><code>${escapeHtml(item.rule || '')}</code><br><small>Matched: ${escapeHtml((item.matched_terms || []).join(', ') || 'none')}</small></td>
      </tr>`).join('') || '<tr><td colspan="5">No eligible proposals remain.</td></tr>';
      if (confirmButton) confirmButton.disabled = true;
    }

    async function previewAssistedLabels() {
      const target = Math.max(1, Math.min(2500, Number($('assistedLabelTarget')?.value) || 500));
      const cap = Math.max(1, Math.min(1000, Number($('assistedLabelClassCap')?.value) || 500));
      try {
        assistedLabelPreview = await getJson(`${API_ENDPOINTS.ALIGNMENT_LABELS.RULE_ASSISTED_PROPOSALS}?target_size=${target}&per_class_cap=${cap}`);
        renderAssistedLabelPreview();
        setStatus('Rule-assisted proposals loaded for review. No labels have been written.', 'ok');
      } catch (error) {
        setStatus(`Assisted proposal preview failed: ${error.message || 'API error'}`, 'error');
      }
    }

    function selectAllAssistedLabels() {
      document.querySelectorAll('.assisted-label-checkbox').forEach((box) => { box.checked = true; });
      if ($('confirmAssistedLabelsBtn')) $('confirmAssistedLabelsBtn').disabled = !document.querySelector('.assisted-label-checkbox:checked');
    }

    async function confirmAssistedLabels() {
      const taskIds = Array.from(document.querySelectorAll('.assisted-label-checkbox:checked')).map((box) => box.value);
      if (!assistedLabelPreview || !taskIds.length) {
        setStatus('Select at least one reviewed proposal.', 'error');
        return;
      }
      const payload = { task_ids: taskIds, proposal_fingerprint: assistedLabelPreview.proposal_fingerprint, dry_run: true };
      try {
        const dryRun = await postJson(API_ENDPOINTS.ALIGNMENT_LABELS.RULE_ASSISTED_CONFIRM, payload);
        const approved = await showConfirm('Confirm Rule-assisted Labels', `Confirm ${dryRun.selected_count} selected proposals as a separate rule_assisted_confirmed dataset? Distribution: ${JSON.stringify(dryRun.class_distribution)}. Each row records this user and the rule provenance.`);
        if (!approved) return;
        const result = await postJson(API_ENDPOINTS.ALIGNMENT_LABELS.RULE_ASSISTED_CONFIRM, { ...payload, dry_run: false });
        setStatus(`${formatNumber(result.selected_count)} rule-assisted labels confirmed with row-level provenance.`, 'ok');
        await previewAssistedLabels();
      } catch (error) {
        setStatus(`Assisted confirmation failed: ${error.message || 'API error'}`, 'error');
      }
    }

    async function lockAssistedSnapshot() {
      const approved = await showConfirm('Lock Assisted Dataset', 'Create a content-addressed snapshot containing only portal-confirmed rule-assisted rows? It remains separate from paired-review evidence.');
      if (!approved) return;
      try {
        const result = await postJson(`${API_ENDPOINTS.ALIGNMENT_LABELS.LOCK_SNAPSHOT}?dataset_mode=rule_assisted_confirmed`, {});
        setStatus(`Assisted snapshot locked: ${formatNumber(result.row_count)} rows; SHA-256 ${String(result.dataset_fingerprint || '').slice(0, 16)}.`, 'ok');
      } catch (error) {
        setStatus(`Assisted snapshot could not be locked: ${error.message || 'API error'}`, 'error');
      }
    }

    function openAlignmentLabelTask(taskId) {
      const task = (state.alignmentLabelQueue?.items || []).find((item) => item.task_id === taskId);
      if (!task) return;
      const currentReviewer = String(state.user?.identity_id || state.user?.username || '');
      if ((task.labels || []).some((label) => String(label.reviewer_id || '') === currentReviewer)) {
        loadAlignmentLabelQueue();
        setStatus('This task has already been reviewed by the signed-in user. The queue has been refreshed.', 'info');
        return;
      }
      $('alignmentLabelTaskId').value = taskId;
      $('alignmentLabelStage').textContent = task.status === 'awaiting_first_review'
        ? 'First independent review'
        : task.status === 'awaiting_second_review'
          ? 'Second independent review — you must not be the first reviewer'
          : 'Adjudication — you must be independent of both earlier reviewers';
      const metadata = task.evidence_metadata || {};
      $('alignmentCurriculumEvidence').innerHTML = `<div style="font-size:12px;color:#526985;margin-bottom:8px">${escapeHtml([metadata.document_title, metadata.module_code, metadata.section, metadata.page_start ? `page ${metadata.page_start}` : ''].filter(Boolean).join(' | '))}</div><div style="white-space:pre-wrap">${escapeHtml(task.curriculum_evidence || 'No curriculum evidence')}</div>`;
      $('alignmentLabourEvidence').innerHTML = (task.labour_market_evidence || []).map((signal) =>
        `<p><strong>${escapeHtml(signal.name || '-')}</strong> · ${escapeHtml(signal.year || '')} ${escapeHtml(signal.quarter || '')}<br><small>Demand ${formatNumber(signal.demand_score || 0)} · confidence ${percent(signal.confidence_score || 0)}</small></p>`
      ).join('');
      $('alignmentLabelValue').value = '3';
      $('alignmentLabelConfidence').value = '3';
      $('alignmentPresentSkills').value = '';
      $('alignmentMissingSkills').value = '';
      $('alignmentLabelJustification').value = '';
      $('alignmentLabelModal').classList.remove('hidden');
    }

    function closeAlignmentLabelTask() {
      $('alignmentLabelModal')?.classList.add('hidden');
    }

    async function submitAlignmentLabel() {
      const taskId = $('alignmentLabelTaskId')?.value;
      const justification = $('alignmentLabelJustification')?.value?.trim() || '';
      if (!taskId || justification.length < 20) {
        setStatus('Provide an independent evidence-based justification of at least 20 characters.', 'error');
        return;
      }
      const splitSkills = (id) => ($(id)?.value || '').split(',').map((value) => value.trim()).filter(Boolean);
      const submitButton = $('submitAlignmentLabelBtn');
      if (submitButton?.disabled) return;
      if (submitButton) {
        submitButton.disabled = true;
        submitButton.textContent = 'Saving...';
      }
      try {
        await postJson(API_ENDPOINTS.ALIGNMENT_LABELS.SUBMIT_LABEL(taskId), {
          alignment_label: Number($('alignmentLabelValue').value),
          confidence: Number($('alignmentLabelConfidence').value),
          justification,
          present_skills: splitSkills('alignmentPresentSkills'),
          missing_skills: splitSkills('alignmentMissingSkills'),
        });
        closeAlignmentLabelTask();
        await loadAlignmentLabelQueue();
        setStatus('Independent alignment label saved. Original labels remain immutable.', 'ok');
      } catch (error) {
        if (String(error.message || '').includes('same reviewer cannot label the same task twice')) {
          closeAlignmentLabelTask();
          await loadAlignmentLabelQueue();
          setStatus('This review was already recorded for the signed-in user. The queue has been refreshed; no duplicate label was created.', 'info');
        } else {
          setStatus(`Alignment label could not be saved: ${error.message || 'review policy error'}`, 'error');
        }
      } finally {
        if (submitButton) {
          submitButton.disabled = false;
          submitButton.textContent = 'Save Independent Label';
        }
      }
    }

    async function retryOperationalJob(jobId) {
      try {
        await postJson(API_ENDPOINTS.OPERATIONS.JOB_RETRY(jobId), {});
        await refreshOperationalJobs();
        setStatus(`Retry queued for job ${String(jobId).slice(0, 8)}.`, 'ok');
      } catch (error) {
        setStatus(`Job retry failed: ${error.message || 'API error'}`, 'error');
      }
    }

    async function cancelOperationalJob(jobId) {
      const confirmed = await showConfirm(
        'Cancel Job',
        'Request cancellation of this operational job?',
      );
      if (!confirmed) return;
      try {
        await postJson(API_ENDPOINTS.OPERATIONS.JOB_CANCEL(jobId), {});
        await refreshOperationalJobs();
        setStatus(`Cancellation requested for job ${String(jobId).slice(0, 8)}.`, 'ok');
      } catch (error) {
        setStatus(`Job cancellation failed: ${error.message || 'API error'}`, 'error');
      }
    }

    async function runProcessingCheck() {
      await runProcessingEndpoint(
        API_ENDPOINTS.PROCESSING.RUN,
        'Checking processing readiness',
        '?limit=100&horizon_periods=4&run_analytics=false',
      );
    }

    async function runFullProcessingPipeline() {
      const confirmed = await showConfirm('Regenerate Validated Outputs', 'Generate a coherent alignment, forecast, skill-gap, and recommendation bundle only from expert-validated curriculum and approved labour evidence?');
      if (!confirmed) return;
      await runProcessingEndpoint(
        API_ENDPOINTS.PROCESSING.VALIDATED_REGENERATION_RUN,
        'Regenerating validated decision outputs',
        '?horizon_periods=4',
      );
    }

    async function rerunAlignmentOnly() {
      await runProcessingEndpoint(API_ENDPOINTS.PROCESSING.VALIDATED_REGENERATION_RUN, 'Regenerating coherent validated outputs', '?horizon_periods=4');
    }

    async function rerunForecastsOnly() {
      await runProcessingEndpoint(API_ENDPOINTS.PROCESSING.VALIDATED_REGENERATION_RUN, 'Regenerating validated outputs with 4-period forecasts', '?horizon_periods=4');
    }

    async function rerunRecommendationsOnly() {
      await runProcessingEndpoint(API_ENDPOINTS.PROCESSING.VALIDATED_REGENERATION_RUN, 'Regenerating coherent validated outputs', '?horizon_periods=4');
    }

    async function runQuality(jobId) {
      setStatus('Checking source readiness...');
      try {
        await postJson(API_ENDPOINTS.INGESTION.QUALITY_RUN(jobId), { limit: 1000 });
        state.ingestionContracts = asItems(await getJson(API_ENDPOINTS.INGESTION.CONTRACTS, []));
        state.normaliserDefinitions = asItems(await getJson(API_ENDPOINTS.INGESTION.NORMALISERS, []));
        await loadQualitySummaries();
        renderIngestionQuality();
        setStatus('Source readiness checks completed.', 'ok');
      } catch (error) {
        console.error(error);
        setStatus('Source readiness checks could not be completed. Check the API logs and try again.', 'error');
      }
    }

    async function runTrendNormalisation(jobId) {
      setStatus('Normalising cleaned records into labour-market trend facts...');
      try {
        const result = await postJson(API_ENDPOINTS.LABOUR_MARKET.TRENDS_NORMALISE, { job_id: jobId, limit: 1000 });
        state.labourTrendSummary = await getJson(API_ENDPOINTS.LABOUR_MARKET.TRENDS_SUMMARY, {});
        renderExecutive();
        renderIngestionQuality();
        setStatus(`Trend normalisation completed. ${formatNumber(result.trend_facts_inserted)} new facts inserted.`, 'ok');
      } catch (error) {
        console.error(error);
        setStatus('Trend normalisation could not be completed. Run quality checks first, then try again.', 'error');
      }
    }

    async function runSignalGeneration() {
      setStatus('Generating canonical labour-market demand signals...');
      try {
        const result = await postJson(API_ENDPOINTS.LABOUR_MARKET.SIGNALS_GENERATE, { limit: 50000 });
        state.labourTrendSummary = await getJson(API_ENDPOINTS.LABOUR_MARKET.TRENDS_SUMMARY, {});
        state.analyticsSummary = await getJson(API_ENDPOINTS.ANALYTICS.SUMMARY, {});
        renderExecutive();
        renderIngestionQuality();
        setStatus(`Signal generation completed. ${formatNumber(result.signals_inserted)} new signals inserted.`, 'ok');
      } catch (error) {
        console.error(error);
        setStatus('Signal generation could not be completed. Normalise trends first, then try again.', 'error');
      }
    }

    async function runDemandEvidenceGeneration() {
      setStatus('Linking canonical demand signals to skills...');
      try {
        const result = await postJson(API_ENDPOINTS.SKILLS.GENERATE_DEMAND_EVIDENCE, { limit: 10000 });
        state.skillsSummary = await getJson(API_ENDPOINTS.SKILLS.SUMMARY, {});
        renderSkills();
        renderIngestionQuality();
        setStatus(`Demand evidence completed. ${formatNumber(result.evidence_created)} new links inserted.`, 'ok');
      } catch (error) {
        console.error(error);
        setStatus('Demand evidence could not be generated. Generate canonical signals first, then try again.', 'error');
      }
    }

    function importNumber(id, fallback) {
      const value = Number($(id)?.value);
      return Number.isFinite(value) ? value : fallback;
    }

    function importProgressValue(job) {
      const total = Number(job?.progress_total || 0);
      const current = Number(job?.progress_current || 0);
      if (total > 0) return Math.max(0, Math.min(100, Math.round((current / total) * 100)));
      if (job?.status === 'completed') return 100;
      if (job?.status === 'failed') return 100;
      if (job?.status === 'running') return 35;
      if (job?.status === 'queued') return 8;
      return 0;
    }

    function importProgressText(job) {
      const total = Number(job?.progress_total || 0);
      const current = Number(job?.progress_current || 0);
      const loaded = Number(job?.records_loaded || 0);
      const failed = Number(job?.records_failed || 0);
      const parts = [];
      if (total > 0) parts.push(`${formatNumber(current)} / ${formatNumber(total)} current phase`);
      if (loaded || failed) parts.push(`${formatNumber(loaded)} loaded, ${formatNumber(failed)} failed`);
      return parts.join(' - ');
    }

    function setImportStatus(kind, message, type = '', job = null) {
      const target = $(`${kind}ImportStatus`);
      if (!target) return;
      const percent = importProgressValue(job);
      const detail = job ? importProgressText(job) : '';
      target.innerHTML = `
        <div>${escapeHtml(message)}</div>
        <div class="mini-progress" aria-label="Import progress"><span style="width:${percent}%"></span></div>
        <small>${formatNumber(percent)}%${detail ? ` - ${escapeHtml(detail)}` : ''}${job?.job_id ? ` - ${escapeHtml(String(job.job_id).slice(0, 8))}` : ''}</small>
      `;
      target.className = `inline-status show ${type}`.trim();
    }

    function clearImportStatus(kind) {
      const target = $(`${kind}ImportStatus`);
      if (!target) return;
      target.textContent = '';
      target.className = 'inline-status';
    }

    function wireImportMode(prefix) {
      const dryRun = $(`${prefix}DryRun`);
      const parse = $(`${prefix}Parse`);
      if (!dryRun || !parse) return;

      const sync = () => {
        if (dryRun.checked) {
          parse.checked = false;
          parse.disabled = true;
        } else {
          parse.disabled = false;
        }
      };

      dryRun.addEventListener('change', sync);
      parse.addEventListener('change', () => {
        if (parse.checked) {
          dryRun.checked = false;
          parse.disabled = false;
        }
      });
      sync();
    }

    function curriculumBaseFields() {
      return {
        institution: $('curriculumInstitution')?.value?.trim() || '',
        faculty: $('curriculumFaculty')?.value?.trim() || '',
        department: $('curriculumDepartment')?.value?.trim() || '',
        programme: $('curriculumProgramme')?.value?.trim() || '',
        title: $('curriculumTitle')?.value?.trim() || '',
        document_key: $('curriculumDocumentKey')?.value?.trim() || '',
        evidence_type: $('curriculumEvidenceType')?.value?.trim() || '',
      };
    }

    async function refreshCurriculumState() {
      state.documents = await getJson(API_ENDPOINTS.CURRICULUM.DOCUMENTS, []);
      state.curriculumHierarchy = await getJson(API_ENDPOINTS.CURRICULUM.HIERARCHY, { faculties: [], departments: [], programmes: [], modules: [] });
      state.curriculumQuality = await getJson(API_ENDPOINTS.CURRICULUM.QUALITY_SUMMARY, null);
      state.documentDetails = await Promise.all(
        state.documents.slice(0, 25).map((doc) => getJson(API_ENDPOINTS.CURRICULUM.DOCUMENT_DETAIL(doc.document_id), null))
      );
      state.ingestionJobs = asItems(await getJson(API_ENDPOINTS.INGESTION.JOBS, []));
      closeCurriculumDetail();
      state.curriculumPage = 1;
      await loadQualitySummaries();
      renderCurriculum();
      renderIngestionQuality();
    }

    function wireCurriculumCredentials() {
      const checkbox = $('curriculumApiRequiresCredentials');
      const username = $('curriculumApiUsername');
      const password = $('curriculumApiPassword');
      if (!checkbox || !username || !password) return;
      const sync = () => {
        username.disabled = !checkbox.checked;
        password.disabled = !checkbox.checked;
        if (!checkbox.checked) {
          username.value = '';
          password.value = '';
        }
      };
      checkbox.addEventListener('change', sync);
      sync();
    }

    async function uploadCurriculumFile() {
      clearImportStatus('curriculum');
      const button = $('uploadCurriculumBtn');
      const fileInput = $('curriculumFile');
      const file = fileInput?.files?.[0];
      if (!file) {
        setImportStatus('curriculum', 'Choose an official PDF, TXT, CSV, or Excel curriculum file first. JSONL/ML training datasets are not valid curriculum evidence.', 'error');
        return;
      }
      const fields = curriculumBaseFields();
      const form = new FormData();
      form.append('file', file);
      if (fields.title) form.append('title', fields.title);
      if (fields.faculty) form.append('faculty', fields.faculty);
      if (fields.department) form.append('department', fields.department);
      if (fields.programme) form.append('programme', fields.programme);
      if (fields.document_key) form.append('document_key', fields.document_key);
      if (fields.evidence_type) form.append('evidence_type', fields.evidence_type);
      const evidenceYear = $('curriculumEvidenceYear')?.value?.trim();
      if (evidenceYear) form.append('evidence_year', evidenceYear);
      form.append('currency_status', $('curriculumCurrencyStatus')?.value || 'unknown');
      form.append('description', `Institution: ${fields.institution || 'unspecified'}`);

      if (button) {
        button.disabled = true;
        button.textContent = 'Uploading...';
      }
      setImportStatus('curriculum', `Uploading ${file.name}. Please wait and do not click again.`, '');
      try {
        const result = await postForm(API_ENDPOINTS.CURRICULUM.UPLOAD, form);
        await refreshOperationalJobs();
        startIngestionMonitor();
        const operationalJob = result.operational_job || null;
        setImportStatus(
          'curriculum',
          `Curriculum file accepted as job ${String(operationalJob?.job_id || 'queued').slice(0, 8)}. Extraction and chunking will continue if this page is closed.`,
          'ok',
          operationalJob,
        );
      } catch (error) {
        console.error(error);
        setImportStatus('curriculum', `Curriculum upload failed. ${error.message || 'Check API logs.'}`, 'error');
      } finally {
        if (button) {
          button.disabled = false;
          button.textContent = 'Upload Curriculum File';
        }
      }
    }

    async function importCurriculumApi() {
      clearImportStatus('curriculum');
      const fields = curriculumBaseFields();
      const endpoint = $('curriculumApiEndpoint')?.value?.trim();
      if (!endpoint) {
        setImportStatus('curriculum', 'Paste a curriculum API endpoint first.', 'error');
        return;
      }
      const requiresCredentials = Boolean($('curriculumApiRequiresCredentials')?.checked);
      const payload = {
        endpoint_url: endpoint,
        title: fields.title || `API import - ${fields.institution || 'institution'}`,
        faculty: fields.faculty || null,
        department: fields.department || null,
        programme: fields.programme || null,
        document_key: fields.document_key || null,
        description: `Institution: ${fields.institution || 'unspecified'}`,
        response_format: $('curriculumApiFormat')?.value?.trim() || 'auto',
        requires_credentials: requiresCredentials,
        username: requiresCredentials ? $('curriculumApiUsername')?.value || null : null,
        password: requiresCredentials ? $('curriculumApiPassword')?.value || null : null,
      };

      setImportStatus('curriculum', 'Importing curriculum API endpoint...', '');
      try {
        const result = await postJson(API_ENDPOINTS.CURRICULUM.IMPORT_API, payload);
        await refreshOperationalJobs();
        startIngestionMonitor();
        const operationalJob = result.operational_job || null;
        setImportStatus(
          'curriculum',
          `Curriculum API response accepted as job ${String(operationalJob?.job_id || 'queued').slice(0, 8)}. Extraction will continue if this page is closed.`,
          'ok',
          operationalJob,
        );
      } catch (error) {
        console.error(error);
        setImportStatus('curriculum', `Curriculum API import failed. ${error.message || 'Check API logs.'}`, 'error');
      }
    }

    async function discoverCputCourses() {
      clearImportStatus('curriculum');
      const facultyCode = $('cputProspectusFacultyCode')?.value?.trim() || '220';
      setImportStatus('curriculum', `Discovering CPUT courses for faculty ${facultyCode}...`, '');
      try {
        const result = await getJson(API_ENDPOINTS.CURRICULUM.CPUT_PROSPECTUS_COURSES(facultyCode), null);
        const courses = result?.courses || [];
        const codes = courses.map((item) => item.course_code).filter(Boolean);
        if (codes.length) {
          $('cputProspectusCourseCodes').value = codes.slice(0, Math.min(4, codes.length)).join(',');
        }
        const preview = courses.slice(0, 10).map((item) => `${item.course_code}: ${item.title}`).join('; ');
        setImportStatus(
          'curriculum',
          codes.length
            ? `Found ${formatNumber(codes.length)} CPUT courses for faculty ${facultyCode}. Course code field has been filled with the first few valid codes. ${preview}`
            : `No CPUT courses found for faculty ${facultyCode}. Check the faculty code on the CPUT prospectus site.`,
          codes.length ? 'ok' : 'error',
        );
      } catch (error) {
        console.error(error);
        setImportStatus('curriculum', `CPUT course discovery failed. ${error.message || 'Check API logs.'}`, 'error');
      }
    }
    async function importCputProspectus() {
      clearImportStatus('curriculum');
      const button = $('importCputProspectusBtn');
      const payload = {
        faculty_code: $('cputProspectusFacultyCode')?.value?.trim() || '220',
        max_courses: importNumber('cputProspectusMaxCourses', 5),
        course_codes: ($('cputProspectusCourseCodes')?.value || '')
          .split(',')
          .map((value) => value.trim().toUpperCase())
          .filter(Boolean),
      };

      setImportStatus('curriculum', 'Importing CPUT online prospectus...', '');
      if (button) button.disabled = true;
      try {
        const result = await postJson(API_ENDPOINTS.CURRICULUM.IMPORT_CPUT_PROSPECTUS, payload);
        await refreshOperationalJobs();
        startIngestionMonitor();
        const operationalJob = result.operational_job || null;
        setImportStatus(
          'curriculum',
          `CPUT prospectus import accepted as job ${String(operationalJob?.job_id || 'queued').slice(0, 8)}. Course and module processing will continue if this page is closed.`,
          'ok',
          operationalJob,
        );
      } catch (error) {
        console.error(error);
        setImportStatus('curriculum', `CPUT prospectus import failed. ${error.message || 'Check API logs.'}`, 'error');
      } finally {
        if (button) button.disabled = false;
      }
    }

    async function discoverCurriculumSources() {
      clearImportStatus('curriculum');
      const url = $('curriculumDiscoveryUrl')?.value?.trim();
      if (!url) {
        setImportStatus('curriculum', 'Enter a curriculum discovery URL first.', 'error');
        return;
      }
      setImportStatus('curriculum', 'Discovering curriculum source links...', '');
      try {
        const result = await postJson(API_ENDPOINTS.CURRICULUM.DISCOVER_SOURCES, {
          start_url: url,
          institution: $('curriculumDiscoveryInstitution')?.value?.trim() || null,
          max_links: importNumber('curriculumDiscoveryMaxLinks', 50),
          same_domain_only: true,
        });
        state.curriculumDiscovery = result;
        const candidates = result.candidates || [];
        const top = candidates.slice(0, 5).map((item) => `${item.document_type}: ${item.title}`).join('; ');
        setImportStatus(
          'curriculum',
          `Discovery completed. ${formatNumber(result.total_candidates || 0)} candidates found. ${top}`,
          'ok',
        );
      } catch (error) {
        console.error(error);
        setImportStatus('curriculum', `Curriculum discovery failed. ${error.message || 'Check API logs.'}`, 'error');
      }
    }

    async function uploadJobAdverts() {
      clearImportStatus('jobAdvert');
      const fileInput = $('jobAdvertFile');
      const file = fileInput?.files?.[0];
      if (!file) {
        setImportStatus('jobAdvert', 'Choose a CSV, Excel, JSON, TXT, or PDF job advert file first.', 'error');
        return;
      }
      const form = new FormData();
      form.append('file', file);
      form.append('source_label', $('jobAdvertSourceLabel')?.value?.trim() || 'manual_dataset');
      form.append('default_region', $('jobAdvertDefaultRegion')?.value?.trim() || 'South Africa');
      form.append('default_country', $('jobAdvertDefaultCountry')?.value?.trim() || 'ZA');

      const button = $('uploadJobAdvertBtn');
      setImportStatus('jobAdvert', 'Uploading job advert dataset...', '');
      if (button) button.disabled = true;
      try {
        const result = await postForm(API_ENDPOINTS.LABOUR_MARKET.JOBS_UPLOAD, form);
        await refreshIngestionState();
        state.labourTrendSummary = await getJson(API_ENDPOINTS.LABOUR_MARKET.TRENDS_SUMMARY, {});
        setImportStatus(
          'jobAdvert',
          `Job adverts uploaded. ${formatNumber(result.inserted || 0)} inserted, ${formatNumber(result.updated || 0)} updated, ${formatNumber(result.failed || 0)} failed.`,
          result.failed ? 'error' : 'ok',
          result.job,
        );
      } catch (error) {
        console.error(error);
        setImportStatus('jobAdvert', `Job advert upload failed. ${error.message || 'Check API logs.'}`, 'error');
      } finally {
        if (button) button.disabled = false;
      }
    }

    async function loadKnownSources() {
      const select = $('genericSourceName');
      if (!select) return;
      try {
        const sources = await getJson(API_ENDPOINTS.INGESTION.KNOWN_SOURCES, []);
        select.innerHTML = '';
        if (sources.length === 0) {
          select.innerHTML = '<option value="Other">Other</option>';
          return;
        }
        const genericSources = sources.filter((s) => !/curriculum|prospectus|study guide|syllabus|module descriptor/i.test(`${s.name || ''} ${s.source_category || ''} ${s.connector_type || ''}`));
        if (genericSources.length === 0) {
          select.innerHTML = '<option value="Other">Other</option>';
          return;
        }
        for (const s of genericSources) {
          const opt = document.createElement('option');
          opt.value = s.name;
          opt.textContent = s.name + (s.job_count > 0 ? ` (${s.job_count})` : '');
          select.appendChild(opt);
        }
      } catch (err) {
        console.error('Failed to load known sources:', err);
        select.innerHTML = '<option value="Other">Other</option>';
      }
    }

    function wireCurriculumFilePreview() {
      const input = $('curriculumFile');
      const preview = $('curriculumFilePreview');
      if (!input || !preview || input.dataset.previewWired === 'true') return;
      input.dataset.previewWired = 'true';
      const sync = () => {
        const file = input.files?.[0];
        if (!file) {
          preview.style.display = 'none';
          preview.textContent = '';
          return;
        }
        preview.style.display = '';
        const sizeMb = (file.size / 1048576).toFixed(1);
        preview.textContent = `${file.name} ? ready for official curriculum upload (${sizeMb} MB)`;
      };
      input.addEventListener('change', sync);
      sync();
    }

    function wireGenericIntakeControls() {
      const requiresAuth = $('genericRequiresAuth');
      const mode = $('genericIntakeMode');
      const apiPayload = $('genericApiPayload');
      const apiMethod = $('genericApiMethod');
      const fileInput = $('genericFile');
      const folderBtn = $('genericFolderBtn');
      const fileList = $('genericFileList');
      const endpointUrl = $('genericEndpointUrl');

      const syncMode = () => {
        const value = mode?.value || 'file';
        const isFile = value === 'file';
        const isApi = value === 'api';
        if (fileInput) {
          fileInput.disabled = !isFile;
          fileInput.style.display = isFile ? '' : 'none';
        }
        if (folderBtn) folderBtn.style.display = isFile ? '' : 'none';
        if (endpointUrl) {
          endpointUrl.style.display = isFile ? 'none' : '';
          endpointUrl.disabled = isFile;
        }
        if (apiPayload) apiPayload.disabled = !isApi || apiMethod?.value !== 'POST';
        if (apiMethod) apiMethod.disabled = !isApi;
        if (requiresAuth) requiresAuth.style.display = isFile ? 'none' : '';
        syncFileList();
      };

      const syncFileList = () => {
        if (!fileList || !fileInput) return;
        const files = fileInput.files;
        if (!files || files.length === 0) {
          fileList.style.display = 'none';
          fileList.innerHTML = '';
          return;
        }
        fileList.style.display = '';
        if (files.length === 1) {
          fileList.textContent = files[0].name;
        } else {
          fileList.textContent = `${files.length} files selected - will be uploaded as a batch`;
        }
      };

      if (folderBtn) {
        folderBtn.addEventListener('click', (e) => {
          e.preventDefault();
          const hidden = document.createElement('input');
          hidden.type = 'file';
          hidden.multiple = true;
          hidden.setAttribute('webkitdirectory', '');
          hidden.setAttribute('directory', '');
          hidden.accept = '.pdf,.xlsx,.xls,.csv,.txt,.json,.zip';
          hidden.addEventListener('change', () => {
            if (fileInput) {
              const dt = new DataTransfer();
              for (const f of hidden.files) dt.items.add(f);
              fileInput.files = dt.files;
              syncFileList();
            }
          });
          hidden.click();
        });
      }

      if (fileInput) fileInput.addEventListener('change', syncFileList);

      mode?.addEventListener('change', syncMode);
      apiMethod?.addEventListener('change', syncMode);
      syncMode();

      loadKnownSources();
      wireCurriculumFilePreview();
    }

    async function runGenericIntake() {
      clearImportStatus('generic');
      const mode = $('genericIntakeMode')?.value || 'file';
      const fileInput = $('genericFile');
      const files = fileInput?.files ? Array.from(fileInput.files) : [];
      const endpoint = $('genericEndpointUrl')?.value?.trim() || '';
      if (mode === 'file' && files.length === 0) {
        setImportStatus('generic', 'Choose at least one file, or select a folder.', 'error');
        return;
      }
      if ((mode === 'website' || mode === 'api') && !endpoint) {
        setImportStatus('generic', 'Enter a website or API endpoint first.', 'error');
        return;
      }

      const sourceCategory = $('genericSourceCategory')?.value || 'other';
      const sourceName = $('genericSourceName')?.value || 'Other';
      const looksLikeCurriculumFile = files.some((file) => /subject|curriculum|syllabus|prospectus|module|study guide/i.test(file.name || ''));
      const selectedCurriculumSource = /curriculum/i.test(sourceName);
      if (sourceCategory === 'curriculum' || selectedCurriculumSource || looksLikeCurriculumFile) {
        setImportStatus('generic', 'Official curriculum files must be uploaded in the Curriculum Documents card below. That route preserves the original file, extracts chunks, and creates the structured subject profile.', 'error');
        return;
      }
      const unsupported = files.filter((file) => ['.jsonl', '.ndjson'].includes((file.name.match(/\.[^.]+$/)?.[0] || '').toLowerCase()));
      if (unsupported.length) {
        setImportStatus('generic', 'JSONL/NDJSON training datasets are not supported as portal evidence. Use official PDFs, syllabi, prospectuses, CSV/XLSX source extracts, ESCO files, or LinkedIn/job CSVs.', 'error');
        return;
      }

      const isOther = sourceName === 'Other';

      const totalSize = files.reduce((sum, f) => sum + f.size, 0);
      const sizeMB = (totalSize / 1048576).toFixed(1);

      if (mode === 'file' && files.length > 1) {
        const form = new FormData();
        form.append('intake_mode', 'file');
        form.append('source_category', sourceCategory);
        form.append('source_type', isOther ? 'other' : sourceName);
        form.append('source_name', sourceName);
        form.append('other_source_name', $('genericOtherSourceName')?.value?.trim() || '');
        form.append('description', $('genericDescription')?.value?.trim() || '');
        for (const f of files) form.append('files', f);

        const button = $('runGenericIntakeBtn');
        setImportStatus('generic', `Uploading ${files.length} files (${sizeMB} MB)...`, '');
        if (button) { button.disabled = true; button.textContent = 'Uploading...'; }
        try {
          const result = await postForm(API_ENDPOINTS.INGESTION.GENERIC_INTAKE_BATCH, form, 600000);
          await refreshIngestionState();
          const job = result.job || null;
          const tone = job?.status === 'failed' ? 'error' : 'ok';
          setImportStatus('generic', `${result.message || 'Batch intake completed.'} Use the Generic Import Queue below to import and normalise it.`, tone, job);
        } catch (error) {
          console.error(error);
          setImportStatus('generic', `Batch intake failed. ${error.message || 'Check API logs.'}`, 'error');
        } finally {
          if (button) { button.disabled = false; button.textContent = 'Upload Source'; }
        }
        return;
      }

      const form = new FormData();
      form.append('intake_mode', mode);
      form.append('source_category', sourceCategory);
      form.append('source_type', isOther ? 'other' : sourceName);
      form.append('source_name', sourceName);
      form.append('other_source_name', $('genericOtherSourceName')?.value?.trim() || '');
      form.append('description', $('genericDescription')?.value?.trim() || '');
      form.append('endpoint_url', endpoint);
      form.append('api_method', $('genericApiMethod')?.value || 'GET');
      form.append('api_payload', $('genericApiPayload')?.value?.trim() || '');
      form.append('requires_auth', Boolean($('genericRequiresAuth')?.checked));
      if (files.length === 1) form.append('file', files[0]);

      const button = $('runGenericIntakeBtn');
      const singleSizeMB = files.length === 1 ? (files[0].size / 1048576).toFixed(1) : sizeMB;
      setImportStatus('generic', `Uploading ${singleSizeMB} MB...`, '');
      if (button) { button.disabled = true; button.textContent = 'Uploading...'; }
      try {
        const result = await postForm(API_ENDPOINTS.INGESTION.GENERIC_INTAKE, form, 600000);
        await refreshIngestionState();
        const job = result.job || null;
        const tone = job?.status === 'failed' ? 'error' : 'ok';
        setImportStatus('generic', `${result.message || 'Generic source intake completed.'} ${result.record_id ? `Record ${String(result.record_id).slice(0, 8)} archived.` : ''} Use the Generic Import Queue below to import and normalise it.`, tone, job);
      } catch (error) {
        console.error(error);
        setImportStatus('generic', `Generic intake failed. ${error.message || 'Check API logs.'}`, 'error');
      } finally {
        if (button) { button.disabled = false; button.textContent = 'Upload Source'; }
      }
    }

    async function refreshIngestionState() {
      state.connectorDefinitions = asItems(await getJson(API_ENDPOINTS.INGESTION.CONNECTORS, []));
      state.normaliserDefinitions = asItems(await getJson(API_ENDPOINTS.INGESTION.NORMALISERS, []));
      state.ingestionSources = asItems(await getJson(API_ENDPOINTS.INGESTION.SOURCES, []));
      state.ingestionJobs = asItems(await getJson(API_ENDPOINTS.INGESTION.JOBS, []));
      state.ingestionContracts = asItems(await getJson(API_ENDPOINTS.INGESTION.CONTRACTS, []));
      state.ingestionFailures = asItems(await getJson(API_ENDPOINTS.INGESTION.FAILURES, []));
      await loadQualitySummaries();
      renderIngestionQuality();
    }

    function activeIngestionJobs() {
      return (state.ingestionJobs || []).filter((job) => ['queued', 'running'].includes(job.status));
    }

    function activePipelineRuns() {
      return (state.pipelineRuns || []).filter((run) => ['queued', 'running'].includes(run.status));
    }

    function activeOperationalJobs() {
      return (state.operationalJobs || []).filter((job) =>
        ['queued', 'running', 'retry_scheduled'].includes(job.status)
      );
    }

    function activePipelineJobIds() {
      return new Set(activePipelineRuns().map((run) => run.parameters?.existing_job_id).filter(Boolean));
    }

    function shouldPollIngestionMonitor() {
      return Boolean(state._pipelineSubmissionInFlight)
        || activeIngestionJobs().length > 0
        || activePipelineRuns().length > 0
        || activeOperationalJobs().length > 0;
    }

    async function refreshIngestionMonitorTick() {
      const hadActive = activeIngestionJobs().length > 0;
      const hadPipeline = activePipelineRuns().length > 0;
      const hadOperational = activeOperationalJobs().length > 0;
      const previous = new Map((state.ingestionJobs || []).map((job) => [job.job_id, job.status]));
      const previousOperational = new Map((state.operationalJobs || []).map((job) => [job.job_id, job.status]));
      state.ingestionJobs = await getJson(API_ENDPOINTS.INGESTION.JOBS, state.ingestionJobs || []);
      state.pipelineRuns = await getJson(`${API_ENDPOINTS.PIPELINE.RUNS}?limit=10`, state.pipelineRuns || []);
      if ($('operationalJobRows')) {
        const operational = await getJson(
          `${API_ENDPOINTS.OPERATIONS.JOBS}?limit=50`,
          { jobs: state.operationalJobs || [] },
        );
        state.operationalJobs = operational.jobs || [];
        renderOperationalJobRows();
      }
      await loadQualitySummaries();
      renderIngestionQuality();

      const active = activeIngestionJobs();
      if (active.length) {
        const lead = active[0];
        const total = Number(lead.progress_total || 0);
        const current = Number(lead.progress_current || 0);
        const pct = total > 0 ? Math.max(0, Math.min(100, Math.round((current / total) * 100))) : 0;
        setStatus(`Ingestion running: ${lead.job_type} ${String(lead.job_id || '').slice(0, 8)} | ${formatNumber(pct)}% current phase | ${formatNumber(lead.records_loaded || 0)} loaded, ${formatNumber(lead.records_failed || 0)} failed`);
        return;
      }

      const pipelines = activePipelineRuns();
      if (pipelines.length) {
        const lead = pipelines[0];
        const stages = lead.summary?.stages || {};
        const completedStages = Number(lead.summary?.stage_count ?? Object.keys(stages).length);
        setStatus(`Pipeline running: ${String(lead.pipeline_run_id || '').slice(0, 8)} - ${formatNumber(completedStages)} stages completed. Refreshes automatically.`);
        return;
      }

      const operational = activeOperationalJobs();
      if (operational.length) {
        const lead = operational[0];
        setStatus(
          `Operational job ${String(lead.job_id || '').slice(0, 8)}: ${lead.progress_message || lead.status} (${formatNumber(lead.progress_current || 0)}%).`
        );
        return;
      }

      if (hadActive || hadPipeline) {
        const finished = (state.ingestionJobs || []).find((job) => ['completed', 'completed_with_errors', 'failed', 'retry_scheduled'].includes(job.status) && previous.has(job.job_id));
        if (finished?.status === 'completed') {
          setStatus(`Ingestion completed: ${String(finished.job_id || '').slice(0, 8)}. You can now run the full pipeline.`, 'ok');
          showToast('Ingestion completed. The pipeline can now be run.', 'ok');
        } else if (finished?.status === 'completed_with_errors') {
          setStatus(`Ingestion completed with errors: ${String(finished.job_id || '').slice(0, 8)}. Review failures before pipeline processing.`, 'error');
          showToast('Ingestion completed with errors. Review the job before processing.', 'error');
        } else if (finished?.status === 'failed') {
          setStatus(`Ingestion failed: ${String(finished.job_id || '').slice(0, 8)}. Check failure events and retry.`, 'error');
          showToast('Ingestion failed. Check the job failure details.', 'error');
        }
      }
      if (hadOperational) {
        const finishedOperational = (state.operationalJobs || []).find(
          (job) => ['completed', 'failed', 'cancelled'].includes(job.status)
            && previousOperational.has(job.job_id)
            && String(job.job_type || '').startsWith('model.train.')
        );
        if (finishedOperational?.status === 'completed') {
          await refreshModelRegistry('Candidate training completed and registry refreshed.');
          state.modelMetrics = await getJson(API_ENDPOINTS.PREDICTIVE.MODEL_METRICS, null, 60000);
          renderModelMetrics();
          showToast('Candidate training completed. Review its registry evidence before promotion.', 'ok');
        } else if (finishedOperational?.status === 'failed') {
          setStatus(`Candidate training failed: ${finishedOperational.error_summary || 'Review the model job evidence.'}`, 'error');
          showToast('Candidate training failed. Review the durable job error before retrying.', 'error');
        }
      }
    }

    function startIngestionMonitor() {
      if (state._ingestionMonitorTimer) return;
      state._ingestionMonitorTimer = window.setInterval(() => {
        if (shouldPollIngestionMonitor()) {
          refreshIngestionMonitorTick().catch((error) => console.error('Ingestion monitor failed', error));
        }
      }, 10000);
      if (shouldPollIngestionMonitor()) {
        refreshIngestionMonitorTick().catch((error) => console.error('Ingestion monitor failed', error));
      }
    }

    async function pollImportJob(kind, label, jobId, initialJob = null) {
      if (!jobId) return;
      let latest = initialJob;

      // Multi-year PDF extraction routinely exceeds one minute. Keep polling
      // until a terminal state so the import button cannot invite a duplicate
      // submission while the durable job is still running.
      for (let attempt = 0; attempt < 600; attempt += 1) {
        if (attempt > 0) {
          await new Promise((resolve) => setTimeout(resolve, 1500));
        }

        const detail = await getJson(API_ENDPOINTS.INGESTION.JOB_DETAIL(jobId), latest);
        latest = detail?.job || detail || latest;
        const status = latest?.status || 'queued';
        const tone = status === 'completed' ? 'ok' : status === 'failed' ? 'error' : '';
        const verb = status === 'completed'
          ? 'completed'
          : status === 'failed'
            ? 'failed'
            : status === 'running'
              ? 'running'
              : 'queued';
        setImportStatus(kind, `${label} import ${verb}.`, tone, latest);

        if (['completed', 'failed', 'cancelled'].includes(status)) break;
      }

      await refreshIngestionState();
    }

    async function runSourceImport(kind) {
      const isChe = kind === 'che';
      const endpoint = isChe ? API_ENDPOINTS.INGESTION.START_CHE_VITALSTATS : API_ENDPOINTS.INGESTION.START_STATSSA;
      const label = isChe ? 'CHE VitalStats' : 'StatsSA QLFS';
      const prefix = isChe ? 'che' : 'stats';
      const button = $(isChe ? 'runCheImportBtn' : 'runStatsImportBtn');
      const payload = {
        start_year: importNumber(`${prefix}StartYear`, 2020),
        end_year: importNumber(`${prefix}EndYear`, isChe ? 2022 : 2025),
        max_files: importNumber(`${prefix}MaxFiles`, isChe ? 2 : 24),
        dry_run: Boolean($(`${prefix}DryRun`)?.checked),
        parse: Boolean($(`${prefix}Parse`)?.checked),
      };

      setStatus(`Starting ${label} ingestion...`);
      setImportStatus(prefix, `Starting ${label} ingestion...`);
      if (button) button.disabled = true;
      try {
        const result = await postJson(endpoint, payload);
        await refreshIngestionState();
        const job = result.job || null;
        const jobId = result.job_id || result.ingestion_job_id || job?.job_id || null;
        const mode = payload.dry_run ? 'Discovery job' : payload.parse ? 'Download and table extraction job' : 'Download job';
        const message = `${mode} accepted. Job ${String(jobId || 'queued').slice(0, 8)} is visible in Ingestion Jobs.`;
        setStatus(`${label} import started. ${message}`, 'ok');
        setImportStatus(prefix, message, '', job);
        await pollImportJob(prefix, label, jobId, job);
      } catch (error) {
        console.error(error);
        setStatus(`${label} import could not be started. Check the API logs and endpoint permissions.`, 'error');
        setImportStatus(prefix, `${label} import could not be started. ${error.message || 'Check the API logs.'}`, 'error');
      } finally {
        if (button) button.disabled = false;
      }
    }

    async function runFullPipeline() {
      await refreshIngestionState();
      const activeJobIds = activePipelineJobIds();
      const unprocessed = (state.ingestionJobs || []).filter(
        j => j.status === 'completed' && j.job_type === 'statssa_qlfs' && !j.processed && !activeJobIds.has(j.job_id) && (j.records_loaded || 0) > 0
      );
      const modal = $('pipelineJobModal');
      const list = $('pipelineJobList');
      const empty = $('pipelineJobEmpty');
      const runBtn = $('pipelineJobRunBtn');
      if (!modal || !list) return;

      if (unprocessed.length === 0) {
        const runningStatsJobs = (state.ingestionJobs || []).filter(
          j => ['queued', 'running'].includes(j.status) && j.job_type === 'statssa_qlfs'
        );
        const runningPipelines = activePipelineRuns();
        list.style.display = 'none';
        empty.style.display = 'block';
        empty.textContent = runningStatsJobs.length
          ? 'A StatsSA ingestion job is still running. Wait for it to complete before running the pipeline.'
          : runningPipelines.length
            ? 'A StatsSA pipeline is already running. Wait for it to complete before starting another one.'
            : 'All completed StatsSA jobs have been processed.';
        runBtn.disabled = true;
      } else {
        list.style.display = 'block';
        empty.style.display = 'none';
        list.innerHTML = unprocessed.map(j => {
          const shortId = (j.job_id || '').slice(0, 8);
          const params = j.parameters || {};
          const range = params.start_year && params.end_year ? `${params.start_year}-${params.end_year}` : 'unknown range';
          const records = formatNumber(j.records_loaded || 0);
          const date = j.created_at ? new Date(j.created_at).toLocaleDateString() : '';
          return `<label style="display:flex;align-items:center;gap:8px;padding:8px 12px;border:1px solid var(--border);border-radius:6px;margin-bottom:6px;cursor:pointer">
            <input type="radio" name="pipelineJobSelect" value="${j.job_id}" style="margin:0">
            <div>
              <strong>${shortId}</strong> &middot; ${range} &middot; ${records} records loaded &middot; ${date}
            </div>
          </label>`;
        }).join('');
        runBtn.disabled = true;
        list.querySelectorAll('input[type=radio]').forEach(r => {
          r.addEventListener('change', () => { runBtn.disabled = false; });
        });
      }
      modal.classList.remove('hidden');
    }

    function closePipelineJobModal() {
      const modal = $('pipelineJobModal');
      if (modal) modal.classList.add('hidden');
    }

    async function executePipelineJob() {
      const selected = document.querySelector('input[name="pipelineJobSelect"]:checked');
      if (!selected) return;
      const jobId = selected.value;
      closePipelineJobModal();
      setStatus('Running the full StatsSA pipeline on the selected job. This can take a little while...');
      try {
        const payload = {
          quality_limit: 1000,
          trend_limit: 50000,
          signal_limit: 100000,
          evidence_limit: 50000,
          horizon_periods: 4,
          report_limit: 3,
          skip_ingestion: true,
          existing_job_id: jobId,
        };
        const run = await postJson(API_ENDPOINTS.PIPELINE.RUN_STATSSA_FULL, payload, 'POST', 900000);
        state.pipelineRuns = await getJson(`${API_ENDPOINTS.PIPELINE.RUNS}?limit=10`, []);
        state.connectorDefinitions = asItems(await getJson(API_ENDPOINTS.INGESTION.CONNECTORS, []));
        state.normaliserDefinitions = asItems(await getJson(API_ENDPOINTS.INGESTION.NORMALISERS, []));
        state.ingestionJobs = asItems(await getJson(API_ENDPOINTS.INGESTION.JOBS, []));
        state.ingestionFailures = asItems(await getJson(API_ENDPOINTS.INGESTION.FAILURES, []));
        state.generatedReports = await getJson(`${API_ENDPOINTS.ANALYTICS.REPORTS}?limit=50`, []);
        state.labourTrendSummary = await getJson(API_ENDPOINTS.LABOUR_MARKET.TRENDS_SUMMARY, {});
        state.analyticsSummary = await getJson(API_ENDPOINTS.ANALYTICS.SUMMARY, {});
        state.recommendations = await getJson(`${API_ENDPOINTS.ANALYTICS.RECOMMENDATIONS}?limit=100`, []);
        state.recommendationGroups = (await getJson(`${API_ENDPOINTS.ANALYTICS.RECOMMENDATIONS_GROUPED}?status=pending_review&limit=50`, { groups: [] })).groups || [];
        await loadQualitySummaries();
        renderAll();
        setStatus(`Pipeline ${run.status}. ${formatNumber(run.summary?.stage_count || 0)} stages recorded.`, run.status === 'completed' ? 'ok' : 'error');
      } catch (error) {
        console.error(error);
        setStatus('Full pipeline could not be completed. Check the API logs and pipeline stage history.', 'error');
      }
    }

    async function retryJob(jobId) {
      setStatus('Queuing ingestion retry...');
      try {
        await postJson(API_ENDPOINTS.INGESTION.JOB_RETRY(jobId), {});
        state.ingestionJobs = asItems(await getJson(API_ENDPOINTS.INGESTION.JOBS, []));
        state.ingestionFailures = asItems(await getJson(API_ENDPOINTS.INGESTION.FAILURES, []));
        await loadQualitySummaries();
        renderIngestionQuality();
        setStatus('Retry job queued.', 'ok');
      } catch (error) {
        console.error(error);
        setStatus('Retry could not be queued. The job may already have a scheduled retry.', 'error');
      }
    }

    async function importJobData(jobId) {
      showToast('Importing records from job...', 'info');
      setStatus('Starting background import for this job...');
      try {
        const result = await postJson(`${API_ENDPOINTS.INGESTION.IMPORT_JOB_ASYNC(jobId)}?auto_enrich=true`, {});
        state.ingestionJobs = asItems(await getJson(API_ENDPOINTS.INGESTION.JOBS, []));
        await loadQualitySummaries();
        renderIngestionQuality();
        startIngestionMonitor();
        if (result.already_imported) {
          showToast('This job has already been imported.', 'info');
          setStatus('This job has already been imported.', 'info');
          return;
        }
        showToast('Import accepted by the durable worker.', 'ok');
        setStatus('Import accepted. It will continue if this page is closed, and progress will refresh automatically.', 'ok');
      } catch (error) {
        console.error(error);
        showToast(`Import failed to start. ${error.message || 'Check API logs.'}`, 'error');
        setStatus(`Import failed to start. ${error.message || 'Check API logs.'}`, 'error');
      }
    }

    async function reviewRecommendation(recommendationId, action) {
      const isDestructive = action === 'reject';
      if (isDestructive) {
        const confirmed = await showConfirm('Reject Recommendation', 'Rejecting this recommendation will mark it as rejected and remove it from the review queue. Continue?');
        if (!confirmed) return;
      }
      const reason = window.prompt(`${action === 'approve' ? 'Approve' : 'Reject'} recommendation reason`, '');
      if (reason === null) return;
      setStatus(`${action === 'approve' ? 'Approving' : 'Rejecting'} recommendation...`);
      try {
        const endpoint = action === 'approve'
          ? API_ENDPOINTS.ANALYTICS.RECOMMENDATION_APPROVE(recommendationId)
          : API_ENDPOINTS.ANALYTICS.RECOMMENDATION_REJECT(recommendationId);
        await postJson(endpoint, {
          reason: reason || `${action} from recommendation dossier`,
          feedback_comment: reason || null,
        });
        state.recommendations = await getJson(`${API_ENDPOINTS.ANALYTICS.RECOMMENDATIONS}?limit=100`, []);
        state.recommendationGroups = (await getJson(`${API_ENDPOINTS.ANALYTICS.RECOMMENDATIONS_GROUPED}?status=pending_review&limit=50`, { groups: [] })).groups || [];
        await loadGovernanceDetails();
        state.selectedRecommendationDossier = await getJson(API_ENDPOINTS.ANALYTICS.RECOMMENDATION_DOSSIER(recommendationId), null);
        renderExecutive();
        renderGovernance();
        renderRecommendationDossier();
        setStatus(`Recommendation ${action === 'approve' ? 'approved' : 'rejected'}.`, 'ok');
      } catch (error) {
        console.error(error);
        setStatus('Recommendation review could not be saved.', 'error');
      }
    }

    const ATTRIBUTION_NOTE = 'Adzuna South Africa data used under written academic research permission. Source: https://www.adzuna.co.za';

    async function exportDossierReport(recommendationId, format) {
      setStatus('Preparing recommendation evidence report...');
      try {
        const report = await getJson(API_ENDPOINTS.ANALYTICS.RECOMMENDATION_DOSSIER_REPORT(recommendationId), null);
        const name = `recommendation-dossier-${recommendationId}`;
        if (format === 'csv') {
          download(`${name}.csv`, toCsv(flattenDossierReport(report)), 'text/csv');
        } else {
          report.attribution = report.attribution || {
            note: ATTRIBUTION_NOTE,
            url: 'https://www.adzuna.co.za',
            applies_to: 'demand_evidence',
          };
          download(`${name}.json`, JSON.stringify(report, null, 2), 'application/json');
        }
        state.generatedReports = await getJson(`${API_ENDPOINTS.ANALYTICS.REPORTS}?limit=50`, []);
        renderReports();
        setStatus('Recommendation evidence report exported.', 'ok');
      } catch (error) {
        console.error(error);
        setStatus('Recommendation evidence report could not be exported.', 'error');
      }
    }

    async function loadRecommendationLineage(recommendationId) {
      setStatus('Loading recommendation lineage...');
      try {
        const lineage = await getJson(API_ENDPOINTS.ANALYTICS.RECOMMENDATION_LINEAGE(recommendationId), null);
        renderLineageSummary(lineage);
        setStatus('Recommendation lineage loaded.', 'ok');
      } catch (error) {
        console.error(error);
        setStatus('Recommendation lineage could not be loaded.', 'error');
      }
    }

    function flattenDossierReport(report) {
      const summary = report.executive_summary || {};
      const attributionNote = report.attribution?.note || ATTRIBUTION_NOTE;
      const rows = [
        { section: 'attribution', text: attributionNote },
        { section: 'summary', ...summary },
      ];
      (report.explanations || []).forEach((item) => rows.push({
        section: 'explanation',
        type: item.explanation_type,
        text: item.explanation_text,
        confidence_score: item.confidence_score,
      }));
      (report.demand_evidence || []).forEach((item) => rows.push({
        section: 'demand_evidence',
        context: item.matched_context,
        demand_score: item.demand_score,
        confidence_score: item.confidence_score,
        rationale: item.rationale,
        canonical_key: item.evidence_metadata?.canonical_key,
        dimension_type: item.evidence_metadata?.dimension_type,
        dimension_value: item.evidence_metadata?.dimension_value,
      }));
      (report.governance?.reviews || []).forEach((item) => {
        const meta = item.review_metadata || {};
        const ctx = meta.evidence_context || {};
        rows.push({
          section: 'review',
          decision: item.decision,
          previous_status: item.previous_status,
          new_status: item.new_status,
          reason: item.decision_reason,
          reviewer_id: item.reviewer_id,
          reviewer_persona: item.reviewer_persona || ctx.reviewer_role,
          reviewed_at: item.created_at,
          evidence_reviewed: meta.evidence_reviewed,
          evidence_context_fingerprint: ctx.evidence_context_fingerprint || meta.evidence_context_fingerprint,
          skill: ctx.skill_name,
          forecast_method: ctx.forecast_method,
          modified_title: item.modified_title,
          modified_description: item.modified_description,
          modified_priority: item.modified_priority,
        });
      });
      (report.governance?.status_history || []).forEach((item) => rows.push({
        section: 'status_history',
        transition_type: item.transition_type,
        previous_status: item.previous_status,
        new_status: item.new_status,
        changed_by: item.changed_by,
        changed_at: item.created_at,
        change_reason: item.change_reason,
      }));
      (report.governance?.feedback || []).forEach((item) => rows.push({
        section: 'feedback',
        reviewer_id: item.reviewer_id,
        feedback_type: item.feedback_type,
        rating: item.rating,
        comment: item.comment,
        created_at: item.created_at,
      }));
      return rows;
    }

    function switchView(view) {
      document.querySelectorAll('.view').forEach((item) => item.classList.toggle('active', item.id === view));
      document.querySelectorAll('[data-view-button]').forEach((item) => item.classList.toggle('active', item.dataset.viewButton === view));
      const title = titles[view] || titles.executive;
      const pageTitle = $('pageTitle');
      const pageSubtitle = $('pageSubtitle');
      if (pageTitle) pageTitle.textContent = title[0];
      if (pageSubtitle) pageSubtitle.textContent = title[1];
    }

    function exportReport(kind, format) {
      const payloads = {
        executive: {
          generated_at: new Date().toISOString(),
          metrics: {
            documents: state.documents.length,
            skills: state.skillsSummary.skills || 0,
            recommendations: state.recommendations.length,
            pending_reviews: state.recommendations.filter((item) => item.status === 'pending_review').length,
            labour_trend_facts: state.labourTrendSummary.total_trends || 0,
            canonical_labour_signals: state.labourTrendSummary.total_signals || 0,
          },
          recommendations: state.recommendations,
          forecasts: state.forecasts,
        },
        curriculum: {
          generated_at: new Date().toISOString(),
          documents: state.documents,
          document_details: state.documentDetails,
          alignment_scores: state.alignmentScores,
        },
        skills: {
          generated_at: new Date().toISOString(),
          summary: state.skillsSummary,
          skills: state.skills,
          mappings: state.skillMappings,
          mapping_workbench: state.skillMappingWorkbench,
          taxonomy_provenance: state.taxonomyProvenance,
          demand_evidence_count: state.skillsSummary.skill_demand_evidence || 0,
          alignment_scores: state.alignmentScores,
        },
        governance: {
          generated_at: new Date().toISOString(),
          recommendations: state.recommendations,
          reviews: state.recommendationReviews,
          feedback: state.recommendationFeedback,
          status_history: state.recommendationHistory,
        },
        ingestion: {
          generated_at: new Date().toISOString(),
          connector_definitions: state.connectorDefinitions,
          normaliser_definitions: state.normaliserDefinitions,
          jobs: state.ingestionJobs,
          sources: state.ingestionSources,
          contracts: state.ingestionContracts,
          failures: state.ingestionFailures,
          quality_summaries: state.qualitySummaries,
          labour_trend_summary: state.labourTrendSummary,
          recent_checks: state.qualityChecks,
        },
      };
      const data = payloads[kind];
      if (format === 'json') {
        data.attribution = { note: ATTRIBUTION_NOTE, url: 'https://www.adzuna.co.za' };
        download(`${kind}-report.json`, JSON.stringify(data, null, 2), 'application/json');
      } else if (format === 'csv') {
        download(`${kind}-report.csv`, toCsv(flattenReport(data)), 'text/csv');
      } else if (format === 'pdf') {
        exportReportPdf(kind, data);
      }
    }

    function exportReportPdf(kind, data) {
      const { jsPDF } = window.jspdf;
      const doc = new jsPDF();
      const pageW = doc.internal.pageSize.getWidth();
      let y = 20;

      const title = kind.charAt(0).toUpperCase() + kind.slice(1) + ' Report';
      doc.setFontSize(18);
      doc.text(title, pageW / 2, y, { align: 'center' });
      y += 10;
      doc.setFontSize(10);
      doc.text(`Generated: ${new Date().toLocaleString()}`, pageW / 2, y, { align: 'center' });
      y += 8;
      doc.setFontSize(8);
      doc.setTextColor(90, 90, 90);
      doc.text(ATTRIBUTION_NOTE, pageW / 2, y, { align: 'center', maxWidth: pageW - 40 });
      doc.setTextColor(0, 0, 0);
      doc.setFontSize(11);
      y += 12;

      const addSection = (label, value) => {
        if (y > 270) { doc.addPage(); y = 20; }
        doc.setFont('helvetica', 'bold');
        doc.text(label + ':', 14, y);
        doc.setFont('helvetica', 'normal');
        doc.text(String(value ?? '-'), 60, y);
        y += 8;
      };
      const addTable = (headers, rows) => {
        if (!rows.length) return;
        if (y > 250) { doc.addPage(); y = 20; }
        doc.autoTable({
          startY: y,
          head: [headers],
          body: rows,
          styles: { fontSize: 8, cellPadding: 2 },
          headStyles: { fillColor: [41, 128, 185] },
          margin: { left: 14, right: 14 },
        });
        y = doc.lastAutoTable.finalY + 10;
      };

      if (kind === 'executive') {
        const m = data.metrics || {};
        addSection('Documents', m.documents);
        addSection('Skills', m.skills);
        addSection('Recommendations', m.recommendations);
        addSection('Pending Reviews', m.pending_reviews);
        addSection('Labour Trend Facts', m.labour_trend_facts);
        addSection('Canonical Signals', m.canonical_labour_signals);
        if (data.recommendations?.length) {
          addTable(['Title', 'Status', 'Priority', 'Confidence'], data.recommendations.slice(0, 25).map((r) => {
            const rep = r.representative || r;
            return [rep.title || '', rep.status || '', rep.priority || '', rep.confidence_score != null ? `${(rep.confidence_score * 100).toFixed(0)}%` : '-'];
          }));
        }
        if (data.forecasts?.length) {
          addTable(['Skill', 'Baseline', 'Forecast', 'Trend'], data.forecasts.slice(0, 25).map((f) => [
            f.skill_id || '-', f.baseline_value ?? '-', f.forecast_value ?? '-', f.trend_direction || '-',
          ]));
        }
      } else if (kind === 'curriculum') {
        addSection('Documents', data.documents?.length || 0);
        if (data.alignment_scores?.length) {
          addTable(['Programme', 'Score'], data.alignment_scores.slice(0, 25).map((a) => [
            a.programme || a.document_id || '-', a.alignment_score != null ? `${(a.alignment_score * 100).toFixed(0)}%` : '-',
          ]));
        }
      } else if (kind === 'skills') {
        const s = data.summary || {};
        addSection('Total Skills', s.skills);
        addSection('Curriculum Mappings', s.curriculum_mappings);
        addSection('Labour Market Mappings', s.labour_market_mappings);
        addSection('Demand Evidence', s.skill_demand_evidence);
        if (data.mappings?.length) {
          addTable(['Skill', 'Source', 'Confidence'], data.mappings.slice(0, 25).map((m) => [
            m.skill_name || m.skill_id || '-', m.source_type || '-', m.confidence_score != null ? `${(m.confidence_score * 100).toFixed(0)}%` : '-',
          ]));
        }
      } else if (kind === 'governance') {
        addSection('Reviews', data.reviews?.length || 0);
        addSection('Feedback Items', data.feedback?.length || 0);
        addSection('Status Transitions', data.status_history?.length || 0);
        if (data.reviews?.length) {
          addTable(
            ['Decision', 'Status', 'Reviewer', 'Role', 'Evid. reviewed', 'Fingerprint'],
            data.reviews.slice(0, 30).map((r) => {
              const meta = r.review_metadata || {};
              const ctx = meta.evidence_context || {};
              return [
                r.decision || '-',
                `${r.previous_status || '-'} -> ${r.new_status || '-'}`,
                r.reviewer_id || '-',
                r.reviewer_persona || ctx.reviewer_role || '-',
                meta.evidence_reviewed === true ? 'yes' : 'no',
                String(ctx.evidence_context_fingerprint || meta.evidence_context_fingerprint || '-').slice(0, 16),
              ];
            }),
          );
        }
        if (data.status_history?.length) {
          addTable(['Type', 'New Status', 'Reason'], data.status_history.slice(0, 30).map((h) => [
            h.transition_type || '-', h.new_status || '-', h.change_reason || '-',
          ]));
        }
      } else if (kind === 'ingestion') {
        addSection('Connectors', data.connector_definitions?.length || 0);
        addSection('Normalisers', data.normaliser_definitions?.length || 0);
        addSection('Jobs', data.jobs?.length || 0);
        addSection('Sources', data.sources?.length || 0);
        addSection('Contracts', data.contracts?.length || 0);
        addSection('Failures', data.failures?.length || 0);
        if (data.jobs?.length) {
          addTable(['Job', 'Status', 'Records'], data.jobs.slice(0, 20).map((j) => [
            j.job_id || '-', j.status || '-', j.records_loaded ?? '-',
          ]));
        }
      }

      doc.save(`${kind}-report.pdf`);
    }

    function flattenReport(data) {
      if (Array.isArray(data.recommendations)) return data.recommendations;
      if (Array.isArray(data.documents)) return data.documents;
      if (Array.isArray(data.mappings)) return data.mappings;
      if (Array.isArray(data.reviews)) return data.reviews;
      if (Array.isArray(data.jobs)) return data.jobs.map((job) => ({
        ...job,
        quality_summary: JSON.stringify(data.quality_summaries[job.job_id] || {}),
      }));
      return Object.entries(data.metrics || data.summary || data).map(([key, value]) => ({ key, value }));
    }


    async function loadIngestionReadiness() {
      const readiness = await getJson(API_ENDPOINTS.INGESTION.READINESS, null);
      const target = $('connectorOpsPanel');
      target.className = '';
      const implemented = readiness?.implemented || [];
      const deferred = readiness?.deferred || [];
      target.innerHTML = `
        <h4>Ingestion Readiness</h4>
        <p>${statusBadge(readiness?.phase || 'unknown', 'good')} ${escapeHtml(readiness?.summary || '')}</p>
        <p><strong>Source categories:</strong> ${escapeHtml(JSON.stringify(readiness?.category_counts || {}))}</p>
        <p><strong>Source types:</strong> ${escapeHtml(JSON.stringify(readiness?.source_counts || {}))}</p>
        <p><strong>Current implemented surface:</strong><br><small>${escapeHtml(implemented.join(', '))}</small></p>
        <p><strong>Deferred until provider access or future hardening:</strong><br><small>${escapeHtml(deferred.join(', '))}</small></p>
      `;
      setStatus('Ingestion readiness loaded.', 'ok');
    }

    async function loadSourceFreshness() {
      const rows = await getJson(API_ENDPOINTS.INGESTION.SOURCE_FRESHNESS, []);
      const target = $('connectorOpsPanel');
      target.className = '';
      target.innerHTML = `
        <h4>Source Freshness</h4>
        ${rows.slice(0, 20).map((item) => `
          <p>${statusBadge(item.freshness_status, item.freshness_status === 'fresh' ? 'good' : item.freshness_status === 'failing' ? 'bad' : 'warn')} ${escapeHtml(item.name)}
          <br><small>${escapeHtml(item.source_category)} / ${escapeHtml(item.source_type)} - loaded ${formatNumber(item.records_loaded)} of ${formatNumber(item.records_seen)}, failed ${formatNumber(item.records_failed)}</small></p>
        `).join('') || '<p>No source freshness records found.</p>'}
      `;
      setStatus(`Loaded freshness for ${formatNumber(rows.length)} sources.`, 'ok');
    }

    async function loadDueSchedules() {
      const rows = await getJson(API_ENDPOINTS.INGESTION.SCHEDULES_DUE, []);
      const target = $('connectorOpsPanel');
      target.className = '';
      target.innerHTML = `
        <h4>Due Schedules</h4>
        ${rows.slice(0, 20).map((item) => `
          <p>${statusBadge(item.due ? 'due' : 'not_due', item.due ? 'warn' : 'good')} ${escapeHtml(item.name)}
          <br><small>${escapeHtml(item.reason)}${item.next_run_hint ? ` - next ${escapeHtml(new Date(item.next_run_hint).toLocaleString())}` : ''}</small></p>
        `).join('') || '<p>No schedules found.</p>'}
      `;
      setStatus(`Loaded schedule status for ${formatNumber(rows.length)} sources.`, 'ok');
    }

    async function simulateJobBoardIngestion() {
      const provider = (window.prompt('Provider: linkedin, indeed, pnet, or careerjunction', 'indeed') || '').trim().toLowerCase();
      if (!provider) return;
      try {
        const result = await postJson(API_ENDPOINTS.INGESTION.JOB_BOARD_SIMULATE, {
          provider,
          payloads: [],
          use_sample_when_empty: true,
        });
        setStatus(`Simulated ${provider} API ingestion completed. Job ${result.job_id}: ${formatNumber(result.inserted)} inserted, ${formatNumber(result.updated)} updated, ${formatNumber(result.failed)} failed.`, 'ok');
        state.ingestionJobs = asItems(await getJson(API_ENDPOINTS.INGESTION.JOBS, []));
        renderQualityJobRows('qualityJobRows', state.ingestionJobs);
      } catch (error) {
        console.error(error);
        setStatus('Job-board simulation failed. Check provider name and API logs.', 'error');
      }
    }

    async function loadSecurityReadiness() {
      const target = $('securityReadinessPanel');
      if (target) {
        target.className = 'empty';
        target.textContent = 'Loading security and operations readiness...';
      }
      showSpinner('spinnerSecurityReadiness');
      setStatus('Loading security and operations readiness...');
      state.securityReadiness = await getJson(API_ENDPOINTS.OPERATIONS.SECURITY_READINESS, null, 60000);
      hideSpinner('spinnerSecurityReadiness');
      renderSecurityReadiness();
      setStatus(state.securityReadiness ? 'Security & operations readiness loaded.' : 'Security & operations readiness could not be loaded.', state.securityReadiness ? 'ok' : 'error');
    }

    function renderSystemAlerts() {
      const summary = state.monitoringEvaluation;
      const panel = $('monitoringSummaryPanel');
      const rows = $('systemAlertRows');
      const humanStatus = (value) => String(value || 'unknown').replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
      if (panel) {
        const checks = summary?.checks || {};
        panel.className = summary ? '' : 'empty';
        panel.innerHTML = summary ? `
          <div class="metrics">
            <div class="metric"><span>Overall</span><strong>${escapeHtml(humanStatus(summary.status))}</strong><small>${escapeHtml(summary.evaluated_at || '-')}</small></div>
            <div class="metric"><span>Database</span><strong>${escapeHtml(humanStatus(checks.database || '-'))}</strong><small>Connectivity</small></div>
            <div class="metric"><span>Worker</span><strong>${escapeHtml(humanStatus(checks.worker || '-'))}</strong><small>Durable jobs</small></div>
            <div class="metric"><span>Ingestion Failures</span><strong>${formatNumber(checks.ingestion_failures_24h || 0)}</strong><small>Last 24 hours</small></div>
            <div class="metric"><span>Degraded Sources</span><strong>${formatNumber(checks.degraded_sources || 0)}</strong><small>Accessible sources</small></div>
            <div class="metric"><span>External Delivery</span><strong>${summary.webhook_configured ? 'Configured' : 'Not configured'}</strong><small>Prometheus ${escapeHtml(summary.prometheus_endpoint || '/metrics')}</small></div>
          </div>
          <p class="operation-purpose"><strong>Interpretation:</strong> ${state.systemAlerts.length
            ? `${formatNumber(state.systemAlerts.length)} active alert(s) require investigation. Healthy database and worker checks do not cancel a separate degraded-source warning.`
            : 'No active operational alerts were found at the time of this evaluation.'}</p>` : 'Run a health evaluation to create or resolve operational alerts.';
      }
      if (!rows) return;
      if (!state.systemAlerts.length) {
        rows.innerHTML = '<tr><td colspan="7" class="empty">No active alerts. Run Health Evaluation to confirm current status.</td></tr>';
        return;
      }
      rows.innerHTML = state.systemAlerts.map((alert) => `
        <tr>
          <td>${statusBadge(alert.severity || 'unknown', alert.severity === 'critical' ? 'bad' : 'warn')}</td>
          <td>${escapeHtml(alert.component || '-')}</td>
          <td><strong>${escapeHtml(alert.title || '-')}</strong><br><small>${escapeHtml(alert.message || '')}</small></td>
          <td>${statusBadge(alert.status || 'open', alert.status === 'acknowledged' ? 'warn' : 'bad')}<br><small>${formatNumber(alert.occurrence_count || 1)} occurrence(s)</small></td>
          <td>${escapeHtml(alert.last_detected_at || '-')}</td>
          <td>${escapeHtml(humanStatus(alert.notification_status || 'not_configured'))}</td>
          <td>${alert.status === 'open' ? `<button class="btn small" data-ack-alert="${escapeHtml(alert.alert_id)}">Acknowledge</button>` : escapeHtml(alert.acknowledged_by || '-')}</td>
        </tr>`).join('');
    }

    async function refreshSystemAlerts() {
      const result = await getJson(`${API_ENDPOINTS.OPERATIONS.ALERTS}?state=active`, { alerts: [] }, 60000);
      state.systemAlerts = result?.alerts || [];
      renderSystemAlerts();
    }

    async function evaluateMonitoring() {
      setStatus('Evaluating service health and alert rules...');
      state.monitoringEvaluation = await postJson(API_ENDPOINTS.OPERATIONS.MONITORING_EVALUATE, {}, 'POST', 60000);
      state.systemAlerts = state.monitoringEvaluation?.active_alerts || [];
      renderSystemAlerts();
      setStatus('Monitoring evaluation completed.', state.systemAlerts.length ? 'error' : 'ok');
    }

    function formatPerformanceDuration(seconds) {
      const value = Number(seconds || 0);
      if (value < 60) return `${Math.round(value)} sec`;
      if (value < 3600) return `${Math.floor(value / 60)} min ${Math.round(value % 60)} sec`;
      if (value < 86400) return `${Math.floor(value / 3600)} hr ${Math.floor((value % 3600) / 60)} min`;
      return `${Math.floor(value / 86400)} day ${Math.floor((value % 86400) / 3600)} hr`;
    }

    function performanceTone(value) {
      return value === 'healthy' ? 'good' : value === 'warning' ? 'warn' : 'bad';
    }

    function performanceThresholdStatus(value, warning, critical) {
      if (value == null) return 'unavailable';
      if (Number(value) >= critical) return 'critical';
      if (Number(value) >= warning) return 'warning';
      return 'healthy';
    }

    function renderSystemPerformance() {
      const target = $('systemPerformancePanel');
      const data = state.systemPerformance;
      if (!target) return;
      if (!data) {
        target.className = 'empty';
        target.textContent = 'No performance measurement is available.';
        return;
      }
      const resources = data.resources || {};
      const latency = data.api_latency || {};
      const database = data.database || {};
      const jobs = data.jobs || {};
      const requests = data.request_totals || {};
      const resourceRows = [['CPU', resources.cpu_percent], ['Memory', resources.memory_percent], ['Disk', resources.disk_percent]];
      target.className = '';
      target.innerHTML = `
        <div class="performance-summary">
          <div><span class="performance-label">Current status</span>${statusBadge(data.status || 'unknown', performanceTone(data.status))}</div>
          <div><span class="performance-label">Measured</span><strong>${escapeHtml(data.measured_at ? new Date(data.measured_at).toLocaleString() : '-')}</strong></div>
          <div><span class="performance-label">Service uptime</span><strong>${escapeHtml(formatPerformanceDuration(data.uptime_seconds))}</strong></div>
        </div>
        <div class="metrics performance-metrics">
          <div class="metric"><span>CPU</span><strong>${resources.cpu_percent == null ? 'Unavailable' : `${formatNumber(resources.cpu_percent)}%`}</strong><small>${statusBadge(performanceThresholdStatus(resources.cpu_percent, 75, 90), performanceTone(performanceThresholdStatus(resources.cpu_percent, 75, 90)))}</small></div>
          <div class="metric"><span>Memory</span><strong>${resources.memory_percent == null ? 'Unavailable' : `${formatNumber(resources.memory_percent)}%`}</strong><small>${statusBadge(performanceThresholdStatus(resources.memory_percent, 75, 90), performanceTone(performanceThresholdStatus(resources.memory_percent, 75, 90)))}</small></div>
          <div class="metric"><span>Disk</span><strong>${resources.disk_percent == null ? 'Unavailable' : `${formatNumber(resources.disk_percent)}%`}</strong><small>${statusBadge(performanceThresholdStatus(resources.disk_percent, 75, 90), performanceTone(performanceThresholdStatus(resources.disk_percent, 75, 90)))}</small></div>
          <div class="metric"><span>API P95 Latency</span><strong>${formatNumber(latency.p95_ms || 0)} ms</strong><small>${statusBadge(latency.status || 'healthy', performanceTone(latency.status))} · ${formatNumber(latency.samples || 0)} samples</small></div>
          <div class="metric"><span>DB Connections</span><strong>${database.active_connections == null ? formatNumber(database.checked_out || 0) : `${formatNumber(database.active_connections)} / ${formatNumber(database.total_connections || 0)}`}</strong><small>${statusBadge(database.status || 'healthy', performanceTone(database.status))} · ${formatNumber(database.pressure_percent || 0)}% pressure</small></div>
          <div class="metric"><span>Job Queue</span><strong>${formatNumber(jobs.queue_depth || 0)}</strong><small>${statusBadge(jobs.queue_status || 'healthy', performanceTone(jobs.queue_status))}</small></div>
          <div class="metric"><span>Job Failure Rate</span><strong>${formatNumber(jobs.failure_rate_percent || 0)}%</strong><small>${statusBadge(jobs.failure_status || 'healthy', performanceTone(jobs.failure_status))} · ${formatNumber(jobs.failed_jobs_24h || 0)} of ${formatNumber(jobs.jobs_24h || 0)} jobs</small></div>
          <div class="metric"><span>Backup Duration</span><strong>${jobs.average_backup_duration_seconds == null ? 'No recent sample' : escapeHtml(formatPerformanceDuration(jobs.average_backup_duration_seconds))}</strong><small>${formatNumber(jobs.backup_samples_24h || 0)} completed backup(s) in 24 hours</small></div>
          <div class="metric"><span>API Error Rate</span><strong>${formatNumber(requests.error_rate_percent || 0)}%</strong><small>${statusBadge(requests.status || 'healthy', performanceTone(requests.status))} · ${formatNumber(requests.errors || 0)} of ${formatNumber(requests.requests || 0)} requests</small></div>
        </div>
        <div class="grid">
          <div class="span-5">
            <h4>Resource utilisation</h4>
            <div class="performance-bars">
              ${resourceRows.map(([label, value]) => `<div class="performance-bar-row"><span>${label}</span><div class="performance-track"><i style="width:${Math.max(0, Math.min(100, Number(value || 0)))}%"></i></div><strong>${value == null ? '-' : `${formatNumber(value)}%`}</strong></div>`).join('')}
            </div>
            <p class="performance-threshold"><strong>Resource thresholds:</strong> warning at 75%; critical at 90%.</p>
          </div>
          <div class="span-7">
            <h4>Slowest API endpoints</h4>
            <div class="table-wrap"><table>
              <thead><tr><th>Endpoint</th><th>Average</th><th>P95</th><th>Maximum</th><th>Samples</th></tr></thead>
              <tbody>${(latency.slowest_endpoints || []).length
                ? latency.slowest_endpoints.map((item) => `<tr><td><code>${escapeHtml(item.path || '-')}</code></td><td>${formatNumber(item.avg_ms || 0)} ms</td><td>${formatNumber(item.p95_ms || 0)} ms</td><td>${formatNumber(item.max_ms || 0)} ms</td><td>${formatNumber(item.count || 0)}</td></tr>`).join('')
                : '<tr><td colspan="5" class="empty">No request timing samples are available yet.</td></tr>'}</tbody>
            </table></div>
          </div>
        </div>
        <p class="operation-purpose"><strong>Interpretation:</strong> ${escapeHtml(data.interpretation || '')} API latency warns at 750 ms P95 and is critical at 2,000 ms. Queue depth warns at 10 jobs; the 24-hour job failure rate warns at 10%.</p>
      `;
    }

    async function loadSystemPerformance() {
      showSpinner('spinnerSystemPerformance');
      setStatus('Measuring current system performance...');
      try {
        state.systemPerformance = await getJson(API_ENDPOINTS.OPERATIONS.PERFORMANCE, null, 60000);
        renderSystemPerformance();
        const status = state.systemPerformance?.status || 'unknown';
        setStatus(`System performance measured: ${String(status).replaceAll('_', ' ')}.`, status === 'healthy' ? 'ok' : 'error');
      } finally {
        hideSpinner('spinnerSystemPerformance');
      }
    }

    async function loadCurriculumGovernanceChain() {
      const summary = $('curriculumGovernanceSummary');
      const rows = $('curriculumGovernanceRows');
      if (!summary || !rows) return;
      summary.textContent = 'Loading curriculum governance evidence...';
      try {
        const programmeSelect = $('governanceProgramme');
        if (programmeSelect && programmeSelect.options.length <= 1) {
          const hierarchy = await getJson(API_ENDPOINTS.CURRICULUM.HIERARCHY, { programmes: [] });
          const programmes = (hierarchy.programmes || []).filter((item) => item.status === 'active');
          programmeSelect.innerHTML = '<option value="">Select programme</option>' + programmes.map((item) =>
            `<option value="${escapeHtml(item.programme_id)}">${escapeHtml(item.name)} (${escapeHtml(item.programme_key || 'no code')})</option>`
          ).join('');
          const preferred = programmes.find((item) => item.programme_key === 'ADICTA')
            || programmes.find((item) => /applications development/i.test(item.name || ''))
            || programmes[0];
          if (preferred) programmeSelect.value = preferred.programme_id;
          if (!programmeSelect.dataset.bound) {
            programmeSelect.addEventListener('change', loadCurriculumGovernanceChain);
            programmeSelect.dataset.bound = 'true';
          }
        }
        const selectedProgrammeId = programmeSelect?.value || '';
        const endpoint = selectedProgrammeId
          ? `${API_ENDPOINTS.CURRICULUM.GOVERNANCE_CHAIN}?programme_id=${encodeURIComponent(selectedProgrammeId)}`
          : API_ENDPOINTS.CURRICULUM.GOVERNANCE_CHAIN;
        const result = await getJson(endpoint, { items: [], summary: {} });
        const chainSummary = result.summary || {};
        summary.innerHTML = `
          <strong>${formatNumber(chainSummary.verified || 0)} of ${formatNumber(chainSummary.total || 0)} evidence records verified.</strong>
          ${chainSummary.selected_programme_name
            ? `<strong>${escapeHtml(chainSummary.selected_programme_name)}</strong> evidence is <strong>${chainSummary.programme_evidence_ready ? 'ready for interpretation' : 'not yet complete'}</strong>.`
            : 'Select a programme to evaluate its regulatory provenance.'}
          ${chainSummary.technical_demo_ready && !chainSummary.programme_evidence_ready
            ? '<div style="margin-top:6px"><strong>Technical UAT complete with synthetic placeholders; empirical regulatory verification remains incomplete.</strong></div>'
            : ''}
          <div style="margin-top:6px">${escapeHtml(result.interpretation || '')}</div>
          ${chainSummary.missing_or_unverified_layers?.length ? `<div style="margin-top:6px"><strong>Missing or unverified:</strong> ${chainSummary.missing_or_unverified_layers.map(escapeHtml).join(', ')}</div>` : ''}
          ${chainSummary.synthetic_uat_layers?.length ? `<div style="margin-top:6px"><strong>Synthetic UAT layers:</strong> ${chainSummary.synthetic_uat_layers.map(escapeHtml).join(', ')}</div>` : ''}
        `;
        rows.innerHTML = (result.items || []).map((item) => `
          <tr>
            <td><strong>${escapeHtml(String(item.layer || '').replaceAll('_', ' '))}</strong>${item.evidence_metadata?.evidence_class === 'synthetic_uat' ? '<br><small>SYNTHETIC UAT — NOT EMPIRICAL</small>' : ''}</td>
            <td>${escapeHtml(item.authority || '-')}<br><small>${escapeHtml(item.title || '-')}</small></td>
            <td>${escapeHtml(item.identifier || item.version_label || '-')}</td>
            <td>${statusBadge(item.currency_status || 'unknown', statusTone(item.currency_status || 'unknown'))}</td>
            <td>${statusBadge(item.verification_status || 'unverified', statusTone(item.verification_status || 'unverified'))}</td>
            <td>${item.programme_id ? 'Programme' : item.tenant_id ? 'Institution' : 'National / shared'}</td>
            <td>${item.official_url ? `<a href="${escapeHtml(item.official_url)}" target="_blank" rel="noopener noreferrer">Open official source</a>` : 'Uploaded evidence'}</td>
          </tr>
        `).join('') || '<tr><td colspan="7">No governance evidence has been registered.</td></tr>';
      } catch (error) {
        summary.textContent = `Curriculum governance evidence could not be loaded: ${error.message || 'API error'}`;
        rows.innerHTML = '<tr><td colspan="7">Governance chain unavailable.</td></tr>';
      }
    }

    async function addCurriculumGovernanceEvidence() {
      const statusTarget = $('curriculumGovernanceStatus');
      const payload = {
        programme_id: $('governanceProgramme')?.value || null,
        layer: $('governanceLayer')?.value,
        authority: $('governanceAuthority')?.value?.trim(),
        evidence_key: $('governanceEvidenceKey')?.value?.trim(),
        title: $('governanceTitle')?.value?.trim(),
        identifier: $('governanceIdentifier')?.value?.trim() || null,
        version_label: $('governanceVersion')?.value?.trim() || null,
        official_url: $('governanceUrl')?.value?.trim() || null,
        nqf_level: $('governanceNqfLevel')?.value ? Number($('governanceNqfLevel').value) : null,
        credits: $('governanceCredits')?.value ? Number($('governanceCredits').value) : null,
        currency_status: $('governanceCurrency')?.value || 'unverified',
        verification_status: $('governanceVerification')?.value || 'unverified',
        notes: $('governanceNotes')?.value?.trim() || null,
        evidence_metadata: { entry_channel: 'data_operations_portal' },
      };
      const programmeLayers = ['che_accreditation', 'dhet_pqm', 'saqa_registration', 'institutional_programme', 'module_curriculum'];
      if (programmeLayers.includes(payload.layer) && !payload.programme_id) {
        if (statusTarget) statusTarget.textContent = 'Select the programme this evidence belongs to.';
        return;
      }
      if (!payload.authority || !payload.evidence_key || !payload.title) {
        if (statusTarget) statusTarget.textContent = 'Authority, evidence key, and title are required.';
        return;
      }
      if (statusTarget) statusTarget.textContent = 'Saving curriculum governance evidence...';
      try {
        await postJson(API_ENDPOINTS.CURRICULUM.GOVERNANCE_EVIDENCE, payload);
        if (statusTarget) statusTarget.textContent = 'Evidence saved with tenant scope and audit history.';
        await loadCurriculumGovernanceChain();
      } catch (error) {
        if (statusTarget) statusTarget.textContent = `Evidence could not be saved: ${error.message || 'API error'}`;
      }
    }

    async function acknowledgeSystemAlert(alertId) {
      const note = window.prompt('Enter a short acknowledgement note describing who will investigate:');
      if (!note || note.trim().length < 3) return;
      await postJson(API_ENDPOINTS.OPERATIONS.ALERT_ACKNOWLEDGE(alertId), { note: note.trim() });
      await refreshSystemAlerts();
      setStatus('Alert acknowledged. It remains active until the next healthy evaluation resolves it.', 'ok');
    }

    async function loadRollbackReadiness() {
      const panel = $('rollbackReadinessPanel');
      const applicationButton = $('runApplicationRollbackBtn');
      const databaseButton = $('runDatabaseRollbackBtn');
      if (panel) panel.textContent = 'Loading rollback rehearsal status...';
      const readiness = await getJson(API_ENDPOINTS.OPERATIONS.ROLLBACK_READINESS, null, 60000);
      if (!panel || !readiness) return;
      const latest = readiness.latest_evidence || {};
      const authority = readiness.database_authority || {};
      panel.className = '';
      panel.innerHTML = `
        <div class="metrics">
          <div class="metric"><span>Application Rehearsal</span><strong>${readiness.application_rehearsal_ready ? 'Ready' : 'Blocked'}</strong><small>Verified release archive</small></div>
          <div class="metric"><span>Database Rehearsal</span><strong>${readiness.database_rehearsal_ready ? 'Ready' : 'Blocked'}</strong><small>Isolated Alembic cycle</small></div>
          <div class="metric"><span>Latest Result</span><strong>${escapeHtml(latest.status || 'not run')}</strong><small>${escapeHtml(latest.type || '-')}</small></div>
          <div class="metric"><span>Live Application</span><strong>Untouched</strong><small>No release switch during rehearsal</small></div>
          <div class="metric"><span>Live Database</span><strong>Untouched</strong><small>Generated temporary database only</small></div>
        </div>
        <p><strong>Database authority:</strong> ${escapeHtml(authority.reason || 'Not checked')}</p>
        <p><strong>Latest evidence:</strong> ${escapeHtml(latest.completed_at || 'No rehearsal recorded.')} ${latest.release_id ? `— ${escapeHtml(latest.release_id)}` : ''}</p>`;
      if (applicationButton) {
        applicationButton.disabled = !readiness.application_rehearsal_ready;
        applicationButton.title = readiness.application_rehearsal_ready
          ? 'Runs an isolated release-bundle verification without switching the live application.'
          : 'Application rehearsal is blocked until a verified release bundle is available.';
      }
      if (databaseButton) {
        databaseButton.disabled = !readiness.database_rehearsal_ready;
        databaseButton.title = readiness.database_rehearsal_ready
          ? 'Runs a downgrade and upgrade cycle against a generated temporary database.'
          : (authority.reason || 'Migration rehearsal authority is unavailable.');
      }
    }

    async function runApplicationRollbackRehearsal() {
      const confirmed = await showConfirm(
        'Test application rollback bundle?',
        'The deployable application will be packaged, extracted into an isolated directory and checksum-verified. The running application will not be switched.'
      );
      if (!confirmed) return;
      const result = await postJson(API_ENDPOINTS.OPERATIONS.ROLLBACK_APPLICATION_REHEARSAL, {});
      await refreshOperationalJobs();
      startIngestionMonitor();
      setStatus(`Application rollback rehearsal queued. Job ${String(result.operational_job?.job_id || '').slice(0, 8)}.`, 'ok');
    }

    async function runDatabaseRollbackRehearsal() {
      const readiness = await getJson(API_ENDPOINTS.OPERATIONS.ROLLBACK_READINESS, null, 60000);
      if (!readiness?.database_rehearsal_ready) {
        setStatus(readiness?.database_authority?.reason || 'Database rollback authority is unavailable.', 'error');
        return;
      }
      const confirmed = await showConfirm(
        'Test database migration rollback?',
        'A generated temporary database will migrate to head, downgrade one release, and upgrade to head again. The live database will not be changed.'
      );
      if (!confirmed) return;
      const result = await postJson(API_ENDPOINTS.OPERATIONS.ROLLBACK_DATABASE_REHEARSAL, {});
      await refreshOperationalJobs();
      startIngestionMonitor();
      setStatus(`Database rollback rehearsal queued. Job ${String(result.operational_job?.job_id || '').slice(0, 8)}.`, 'ok');
    }

    function renderResearchClaims() {
      const data = state.researchClaims;
      const summary = $('researchClaimsSummary');
      const rows = $('researchClaimRows');
      if (!data) return;
      const counts = data.generated_from?.current_counts || {};
      if (summary) {
        summary.className = '';
        summary.innerHTML = `
          <div class="metrics">
            <div class="metric"><span>Camera-ready Gate</span><strong>${escapeHtml(data.camera_ready_gate || 'unknown')}</strong><small>Due ${escapeHtml(data.paper?.camera_ready_due || '-')}</small></div>
            <div class="metric"><span>Claims Checked</span><strong>${formatNumber(data.claims?.length || 0)}</strong><small>${formatNumber(data.blocking_claim_ids?.length || 0)} require revision/evidence</small></div>
            <div class="metric"><span>Expert Labels</span><strong>${formatNumber(counts.expert_labels || 0)}</strong><small>${formatNumber(counts.locked_label_snapshots || 0)} locked snapshots</small></div>
            <div class="metric"><span>Active ML Models</span><strong>${formatNumber(counts.active_models || 0)}</strong><small>${formatNumber(counts.registered_models || 0)} registered artifacts</small></div>
            <div class="metric"><span>Current Evidence</span><strong>${formatNumber(counts.job_postings || 0)}</strong><small>${formatNumber(counts.labour_market_signals || 0)} canonical signals</small></div>
          </div>
          <p><strong>Required positioning:</strong> ${escapeHtml((data.required_camera_ready_positioning || []).join(' | '))}</p>`;
      }
      if (rows) {
        rows.innerHTML = (data.claims || []).map((item) => {
          const supported = ['supported', 'evidence_available'].includes(item.status);
          return `<tr>
            <td><strong>${escapeHtml(item.claim_id)}</strong><br><small>${escapeHtml(item.paper_location || '')}</small></td>
            <td>${escapeHtml(item.claim || '')}</td>
            <td>${statusBadge(item.status || 'unknown', supported ? 'good' : item.status === 'simulation_only' ? 'warn' : 'bad')}</td>
            <td>${escapeHtml(item.evidence || '')}</td>
            <td>${escapeHtml(item.camera_ready_action || '')}</td>
          </tr>`;
        }).join('');
      }
    }

    async function loadResearchClaims() {
      setStatus('Reconciling accepted-paper claims with current evidence...');
      state.researchClaims = await getJson(API_ENDPOINTS.OPERATIONS.RESEARCH_CLAIMS, null, 60000);
      renderResearchClaims();
      setStatus(
        state.researchClaims ? `Claim reconciliation loaded: ${state.researchClaims.blocking_claim_ids?.length || 0} item(s) require revision or evidence.` : 'Claim reconciliation could not be loaded.',
        state.researchClaims ? 'ok' : 'error'
      );
    }

    async function archiveResearchClaims() {
      const result = await postJson(API_ENDPOINTS.OPERATIONS.RESEARCH_CLAIMS_ARCHIVE, {}, 'POST', 60000);
      state.researchClaims = result;
      renderResearchClaims();
      setStatus(`Claim evidence archived as report ${String(result.report_id || '').slice(0, 8)}.`, 'ok');
    }

    async function loadDeploymentReadiness() {
      const target = $('deploymentReadinessPanel');
      if (target) {
        target.className = 'empty';
        target.textContent = 'Loading deployment and UAT readiness...';
      }
      try {
        showSpinner('spinnerDeploymentReadiness');
        setStatus('Loading deployment and UAT readiness...');
        state.deploymentReadiness = await getJson(API_ENDPOINTS.OPERATIONS.DEPLOYMENT_READINESS, null, 60000);
        renderDeploymentReadiness();
        setStatus(state.deploymentReadiness ? 'Deployment & UAT readiness loaded.' : 'Deployment & UAT readiness could not be loaded.', state.deploymentReadiness ? 'ok' : 'error');
      } catch (error) {
        console.error(error);
        if (target) target.textContent = `Deployment readiness could not be rendered: ${error.message || 'unknown error'}`;
        setStatus('Deployment & UAT readiness could not be loaded.', 'error');
      } finally {
        hideSpinner('spinnerDeploymentReadiness');
      }
    }

    async function generateBackupManifest() {
      setStatus('Queuing encrypted backup...');
      try {
        const result = await postJson(API_ENDPOINTS.OPERATIONS.BACKUP_CREATE, {});
        const job = result.operational_job || {};
        await refreshOperationalJobs();
        await loadBackupLifecycle();
        startIngestionMonitor();
        setStatus(`Encrypted backup queued. Job ${String(job.job_id || '').slice(0, 8)} will continue on the server.`, 'ok');
      } catch (error) {
        console.error(error);
        setStatus('Encrypted backup could not be queued. Check API logs.', 'error');
      }
    }

    async function loadBackupLifecycle() {
      const panel = $('backupLifecyclePanel');
      const restoreButton = $('runRestoreDrillBtn');
      if (panel) panel.textContent = 'Loading backup lifecycle status...';
      const [summary, retention, restoreReadiness] = await Promise.all([
        getJson(API_ENDPOINTS.OPERATIONS.BACKUPS, null, 60000),
        getJson(API_ENDPOINTS.OPERATIONS.BACKUP_RETENTION, null, 60000),
        getJson(API_ENDPOINTS.OPERATIONS.BACKUP_RESTORE_READINESS, null, 60000),
      ]);
      if (!panel || !summary || !retention) return;
      const drill = summary.latest_restore_drill || {};
      panel.className = '';
      panel.innerHTML = `
        <div class="metrics">
          <div class="metric"><span>Encrypted Backups</span><strong>${formatNumber(summary.backup_count || 0)}</strong><small>${escapeHtml(summary.latest?.backup_id || 'none')}</small></div>
          <div class="metric"><span>Retention</span><strong>${formatNumber(retention.keep?.length || 0)} kept</strong><small>${formatNumber(retention.quarantine?.length || 0)} eligible for quarantine</small></div>
          <div class="metric"><span>Restore Drills</span><strong>${formatNumber(summary.restore_drill_count || 0)}</strong><small>${escapeHtml(drill.status || 'not run')}</small></div>
          <div class="metric"><span>Live Database</span><strong>${drill.live_database_modified === false ? 'Untouched' : 'No evidence'}</strong><small>Temporary database removed: ${drill.temporary_database_removed ? 'yes' : 'not recorded'}</small></div>
        </div>
        <p><strong>Policy:</strong> ${formatNumber(retention.policy?.daily || 0)} daily, ${formatNumber(retention.policy?.weekly || 0)} weekly, ${formatNumber(retention.policy?.monthly || 0)} monthly; quarantined backups remain recoverable for ${formatNumber(retention.policy?.quarantine_days || 0)} days.</p>
        <p><strong>Latest drill:</strong> ${escapeHtml(drill.completed_at || 'No isolated restore drill recorded.')} ${drill.backup_id ? `from backup ${escapeHtml(drill.backup_id)}` : ''}</p>
        <p><strong>Restore authority:</strong> ${restoreReadiness?.ready ? 'Ready' : 'Blocked'} — ${escapeHtml(restoreReadiness?.reason || 'Not checked')}</p>`;
      if (restoreButton) {
        restoreButton.disabled = !restoreReadiness?.ready;
        restoreButton.title = restoreReadiness?.ready
          ? 'Restores the latest encrypted backup into a generated temporary database and removes it after validation.'
          : (restoreReadiness?.reason || 'Restore authority is unavailable.');
      }
    }

    async function applyBackupRetention() {
      const retention = await getJson(API_ENDPOINTS.OPERATIONS.BACKUP_RETENTION, null, 60000);
      if (!retention) return;
      const count = retention.quarantine?.length || 0;
      if (!count) {
        setStatus('Retention policy is already satisfied; no backups need quarantine.', 'ok');
        await loadBackupLifecycle();
        return;
      }
      const confirmed = await showConfirm(
        'Apply backup retention?',
        `${count} backup(s) will move to recoverable quarantine. No backup will be permanently deleted.`
      );
      if (!confirmed) return;
      await postJson(API_ENDPOINTS.OPERATIONS.BACKUP_RETENTION_APPLY, {});
      await refreshOperationalJobs();
      startIngestionMonitor();
      setStatus('Recoverable retention job queued.', 'ok');
    }

    async function runRestoreDrill() {
      const readiness = await getJson(API_ENDPOINTS.OPERATIONS.BACKUP_RESTORE_READINESS, null, 60000);
      if (!readiness?.ready) {
        setStatus(readiness?.reason || 'Restore drill authority is unavailable.', 'error');
        return;
      }
      const confirmed = await showConfirm(
        'Run isolated restore drill?',
        'The latest encrypted backup will be restored into a generated temporary database, validated, and the temporary database will then be removed. The live database is not changed.'
      );
      if (!confirmed) return;
      const result = await postJson(API_ENDPOINTS.OPERATIONS.BACKUP_RESTORE_DRILL, {});
      await refreshOperationalJobs();
      startIngestionMonitor();
      setStatus(`Restore drill queued. Job ${String(result.operational_job?.job_id || '').slice(0, 8)} continues on the server.`, 'ok');
    }

    async function runPortalUat() {
      const target = $('portalUatPanel');
      if (target) {
        target.className = 'empty';
        target.textContent = 'Running portal golden-path and failure-path acceptance checks...';
      }
      showSpinner('spinnerPortalUat');
      setStatus('Running portal acceptance UAT...');
      try {
        state.portalUat = await postJson(API_ENDPOINTS.OPERATIONS.PORTAL_UAT_RUN, {}, 'POST', 120000);
        renderPortalUat();
        const failed = Number(state.portalUat?.summary?.failed || 0);
        setStatus(
          failed ? `Portal UAT completed with ${failed} failure(s).` : 'Portal UAT passed; expected safety blocks are recorded separately.',
          failed ? 'error' : 'ok'
        );
      } catch (error) {
        console.error(error);
        if (target) target.textContent = 'Portal UAT could not run. Check API availability and administrator access.';
        setStatus('Portal UAT could not run.', 'error');
      } finally {
        hideSpinner('spinnerPortalUat');
      }
    }

    async function runModelEvaluation() {
      showSpinner('spinnerModelReadiness');
      setStatus('Archiving model readiness evaluation...');
      try {
        const result = await postJson(API_ENDPOINTS.PREDICTIVE.RUN_MODEL_EVALUATION, {});
        state.modelReadiness = result.readiness || await getJson(API_ENDPOINTS.PREDICTIVE.MODEL_READINESS, null, 60000);
        state.generatedReports = await getJson(`${API_ENDPOINTS.ANALYTICS.REPORTS}?limit=50`, []);
        hideSpinner('spinnerModelReadiness');
        renderForecasts();
        renderReports();
        setStatus(`Model evaluation archived. Report ${String(result.report_id || '').slice(0, 8)}.`, 'ok');
      } catch (error) {
        hideSpinner('spinnerModelReadiness');
        console.error(error);
        setStatus('Model evaluation could not be archived.', 'error');
      }
    }

    async function refreshPredictionRanking() {
      setStatus('Running recommendation ranking dry-run...');
      try {
        const result = await postJson(`${API_ENDPOINTS.PREDICTIVE.RANKING_REFRESH}?limit=200&dry_run=true`, {});
        await loadForecastQuality();
        setStatus(`Ranking dry-run checked ${formatNumber(result.recommendations_checked || 0)} recommendations.`, 'ok');
      } catch (error) {
        console.error(error);
        setStatus('Ranking dry-run failed. Check API logs.', 'error');
      }
    }

    async function archivePredictionReport() {
      setStatus('Archiving explainability report...');
      try {
        const result = await postJson(API_ENDPOINTS.PREDICTIVE.EXPLAINABILITY_REPORT, {});
        state.forecastQuality = result.payload || await getJson(API_ENDPOINTS.PREDICTIVE.FORECAST_QUALITY, null, 60000);
        state.generatedReports = await getJson(`${API_ENDPOINTS.ANALYTICS.REPORTS}?limit=50`, []);
        renderForecastQuality();
        renderReports();
        setStatus(`Quality report archived: ${String(result.report_id || '').slice(0, 8)}`, 'ok');
      } catch (error) {
        console.error(error);
        setStatus('Quality report could not be archived. Check API logs.', 'error');
      }
    }

export { loadCurriculumGovernanceChain, addCurriculumGovernanceEvidence };
export { archiveUnsupportedSkills };

export { previewAssistedLabels, selectAllAssistedLabels, confirmAssistedLabels, lockAssistedSnapshot };

Object.assign(actions, {
  loadRecommendationDossier, createDatasetSnapshot, refreshModelRegistry, checkSelectedModelGates, recordSelectedModelTestEvidence, evaluateSelectedModel, approveSelectedModel, promoteSelectedModel, rejectSelectedModel, rollbackSelectedModel, showCurriculumDetail, closeCurriculumDetail,
  loadSkillGapEvidence, editConnector, loadContractDrift, editContract, cloneContract,
  toggleSource, remapTableRows, reviewRecord, correctRecord, reviewRecommendation,
  retryJob, exportDossierReport, loadRecommendationLineage,
  runQuality, runTrendNormalisation, runSignalGeneration, runDemandEvidenceGeneration,
  importJobData,
  retryOperationalJob,
  cancelOperationalJob,
  evaluateMonitoring,
  loadSystemPerformance,
  refreshSystemAlerts,
  acknowledgeSystemAlert,
  loadBackupLifecycle,
  applyBackupRetention,
  runRestoreDrill,
  loadRollbackReadiness,
  runApplicationRollbackRehearsal,
  runDatabaseRollbackRehearsal,
  loadResearchClaims,
  archiveResearchClaims,
});

export { trainModel, loadDashboard, loadSubjectProfiles, openSubjectProfileValidation, closeSubjectProfileValidation, submitSubjectProfileValidation, loadCurriculumEvidenceReviews, openCurriculumEvidenceReview, closeCurriculumEvidenceReview, submitCurriculumEvidenceReview, loadSkillMappingWorkbench, loadTaxonomyProvenance, openSkillMappingReview, closeSkillMappingReview, submitSkillMappingReview, generateSkillMappings, loadAlignmentLabelQueue, generateAlignmentTasks, openAlignmentLabelTask, closeAlignmentLabelTask, submitAlignmentLabel, lockAlignmentLabelSnapshot, buildAlignmentSample, exportAlignmentLabelSnapshot, loadDhetOfoSource, discoverDhetOfo, downloadDhetOfo, uploadDhetOfo, validateDhetOfo, importDhetOfo, loadDhetOfoMappings, loadDhetOfoStats, loadDhetOfoBreakdown, proposeDhetOfoMapping, openDhetOfoReview, closeDhetOfoReview, submitDhetOfoReview, refreshModelRegistry, checkSelectedModelGates, recordSelectedModelTestEvidence, evaluateSelectedModel, approveSelectedModel, promoteSelectedModel, rejectSelectedModel, rollbackSelectedModel, loadGovernanceDetails, loadQualitySummaries, loadRecommendationDossier, createDatasetSnapshot, showCurriculumDetail, closeCurriculumDetail, loadSkillGapEvidence, addConnector, editConnector, addSource, toggleSource, loadContractDrift, editContract, cloneContract, loadSkillsValidity, loadIngestionDataQuality, remapTableRows, loadReviewRows, reviewRecord, correctRecord, refreshProcessingSummary, refreshProcessingOutputs, refreshSkillsData, refreshForecastData, runForecasts, runSkillExtraction, runGapAnalysis, loadForecastQuality, runProcessingCheck, runFullProcessingPipeline, rerunAlignmentOnly, rerunForecastsOnly, rerunRecommendationsOnly, runQuality, runTrendNormalisation, runSignalGeneration, runDemandEvidenceGeneration, wireImportMode, refreshCurriculumState, wireCurriculumCredentials, wireCurriculumFilePreview, uploadCurriculumFile, importCurriculumApi, importCputProspectus, discoverCputCourses, discoverCurriculumSources, uploadJobAdverts, wireGenericIntakeControls, runGenericIntake, loadKnownSources, refreshIngestionState, runSourceImport, runFullPipeline, closePipelineJobModal, executePipelineJob, retryJob, importJobData, retryOperationalJob, cancelOperationalJob, reviewRecommendation, exportDossierReport, loadRecommendationLineage, switchView, exportReport, loadIngestionReadiness, loadSourceFreshness, loadDueSchedules, simulateJobBoardIngestion, startIngestionMonitor, loadSecurityReadiness, loadSystemPerformance, evaluateMonitoring, refreshSystemAlerts, acknowledgeSystemAlert, loadBackupLifecycle, applyBackupRetention, runRestoreDrill, loadRollbackReadiness, runApplicationRollbackRehearsal, runDatabaseRollbackRehearsal, loadResearchClaims, archiveResearchClaims, loadDeploymentReadiness, runPortalUat, generateBackupManifest, runModelEvaluation, refreshPredictionRanking, archivePredictionReport };





























