// dashboard-main.js - Entry point, event wiring, and initialization
import { requireAuth } from './auth.js';
import { $, setupSearch, showToast } from './dashboard-utils.js?v=20260825b';
import { state } from './dashboard-state.js?v=20260921-registry1';
import { API_ENDPOINTS } from './config.js?v=20260912d';
import {
  renderRecommendationRows, renderSkillGapRows, renderSkillMappingRows,
  renderForecastRows, openForecastExplanation, closeForecastExplanation, renderGovernanceRows, renderCurriculumRows, renderCurriculum
} from './dashboard-views.js?v=20260921-registry1';
import {
  loadDashboard, switchView, exportReport,
  runFullPipeline, closePipelineJobModal, executePipelineJob, addConnector, addSource,
  runFullProcessingPipeline, runProcessingCheck,
  rerunAlignmentOnly, rerunForecastsOnly, rerunRecommendationsOnly,
  runForecasts, refreshForecastData, refreshProcessingSummary,
  wireImportMode, wireCurriculumCredentials, wireCurriculumFilePreview, wireGenericIntakeControls,
  runGenericIntake, loadKnownSources, runSourceImport,
  uploadJobAdverts, uploadCurriculumFile, loadCurriculumGovernanceChain, addCurriculumGovernanceEvidence,
  importCurriculumApi, discoverCurriculumSources, importCputProspectus, discoverCputCourses,
  loadReviewRows, loadIngestionDataQuality, loadSkillsValidity,
  createDatasetSnapshot, refreshModelRegistry, checkSelectedModelGates, recordSelectedModelTestEvidence, evaluateSelectedModel, approveSelectedModel, promoteSelectedModel, rejectSelectedModel, rollbackSelectedModel,
  trainModel, refreshCurriculumState, closeCurriculumDetail,
  loadIngestionReadiness, loadSourceFreshness, loadDueSchedules, simulateJobBoardIngestion,
  startIngestionMonitor, loadSecurityReadiness, loadSystemPerformance, evaluateMonitoring, refreshSystemAlerts, acknowledgeSystemAlert, loadBackupLifecycle, applyBackupRetention, runRestoreDrill, loadRollbackReadiness, runApplicationRollbackRehearsal, runDatabaseRollbackRehearsal, loadResearchClaims, archiveResearchClaims, loadDeploymentReadiness, runPortalUat, generateBackupManifest,
  runModelEvaluation, refreshPredictionRanking, archivePredictionReport,
  runSkillExtraction, runGapAnalysis, refreshSkillsData, loadForecastQuality,
  loadSubjectProfiles, openSubjectProfileValidation, closeSubjectProfileValidation, submitSubjectProfileValidation, loadCurriculumEvidenceReviews, openCurriculumEvidenceReview, closeCurriculumEvidenceReview, submitCurriculumEvidenceReview,
  loadSkillMappingWorkbench, loadTaxonomyProvenance, openSkillMappingReview, closeSkillMappingReview, submitSkillMappingReview, generateSkillMappings, archiveUnsupportedSkills,
  loadAlignmentLabelQueue, generateAlignmentTasks, openAlignmentLabelTask, closeAlignmentLabelTask, submitAlignmentLabel, lockAlignmentLabelSnapshot, buildAlignmentSample, exportAlignmentLabelSnapshot, previewAssistedLabels, selectAllAssistedLabels, confirmAssistedLabels, lockAssistedSnapshot,
  loadDhetOfoSource, discoverDhetOfo, downloadDhetOfo, uploadDhetOfo, validateDhetOfo, importDhetOfo, loadDhetOfoMappings, loadDhetOfoStats, loadDhetOfoBreakdown, proposeDhetOfoMapping, openDhetOfoReview, closeDhetOfoReview, submitDhetOfoReview
} from './dashboard-actions.js?v=20260921-registry4';
import { auth } from './auth.js';

requireAuth();

function wireEventListeners() {
  const onOptional = (id, event, handler) => {
    const el = $(id);
    if (el) el.addEventListener(event, handler);
  };

  document.querySelectorAll('[data-export]').forEach((button) => {
    button.addEventListener('click', () => {
      const [kind, format] = button.dataset.export.split('-');
      exportReport(kind, format);
    });
  });

  onOptional('refreshBtn', 'click', loadDashboard);
  onOptional('runPipelineBtn', 'click', runFullPipeline);
  onOptional('pipelineJobCancelBtn', 'click', closePipelineJobModal);
  onOptional('pipelineJobRunBtn', 'click', executePipelineJob);
  onOptional('pipelineJobModal', 'click', (e) => {
    if (e.target === $('pipelineJobModal')) closePipelineJobModal();
  });
  onOptional('addConnectorBtn', 'click', addConnector);
  onOptional('addSourceBtn', 'click', addSource);
  onOptional('runFullProcessingBtn', 'click', runFullProcessingPipeline);
  onOptional('runProcessingBtn', 'click', runProcessingCheck);
  onOptional('rerunAlignmentBtn', 'click', rerunAlignmentOnly);
  onOptional('rerunForecastsBtn', 'click', rerunForecastsOnly);
  onOptional('rerunRecommendationsBtn', 'click', rerunRecommendationsOnly);
  const runForecastsBtn = $('runForecastsBtn');
  if (runForecastsBtn) runForecastsBtn.addEventListener('click', runForecasts);
  const refreshForecastBtn = $('refreshForecastBtn');
  if (refreshForecastBtn) refreshForecastBtn.addEventListener('click', refreshForecastData);
  onOptional('refreshProcessingBtn', 'click', refreshProcessingSummary);
  onOptional('forecastExplanationCloseBtn', 'click', closeForecastExplanation);
  onOptional('forecastExplanationDoneBtn', 'click', closeForecastExplanation);
  onOptional('forecastExplanationModal', 'click', (event) => {
    if (event.target === $('forecastExplanationModal')) closeForecastExplanation();
  });
  document.addEventListener('click', (event) => {
    const button = event.target.closest('[data-forecast-explanation]');
    if (button) openForecastExplanation(button.dataset.forecastExplanation);
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !$('forecastExplanationModal')?.classList.contains('hidden')) {
      closeForecastExplanation();
    }
  });
  wireImportMode('che');
  wireImportMode('stats');
  wireCurriculumCredentials();
  wireCurriculumFilePreview();
  wireGenericIntakeControls();
  onOptional('runGenericIntakeBtn', 'click', runGenericIntake);
  onOptional('runCheImportBtn', 'click', () => runSourceImport('che'));
  onOptional('runStatsImportBtn', 'click', () => runSourceImport('stats'));
  onOptional('uploadJobAdvertBtn', 'click', uploadJobAdverts);
  onOptional('uploadCurriculumBtn', 'click', uploadCurriculumFile);
  onOptional('refreshCurriculumGovernanceBtn', 'click', loadCurriculumGovernanceChain);
  onOptional('addCurriculumGovernanceBtn', 'click', addCurriculumGovernanceEvidence);
  onOptional('importCurriculumApiBtn', 'click', importCurriculumApi);
  onOptional('discoverCurriculumSourcesBtn', 'click', discoverCurriculumSources);
  const discoverCputCoursesBtn = $('discoverCputCoursesBtn');
  if (discoverCputCoursesBtn) discoverCputCoursesBtn.addEventListener('click', discoverCputCourses);
  onOptional('importCputProspectusBtn', 'click', importCputProspectus);
  onOptional('loadReviewRowsBtn', 'click', loadReviewRows);
  onOptional('loadIngestionDataQualityBtn', 'click', loadIngestionDataQuality);
  onOptional('reloadSkillsValidityBtn', 'click', loadSkillsValidity);
  onOptional('trainXgboostBtn', 'click', () => trainModel('xgboost'));
  onOptional('trainLstmBtn', 'click', () => trainModel('lstm'));
  onOptional('createDatasetSnapshotBtn', 'click', createDatasetSnapshot);
  onOptional('refreshModelRegistryBtn', 'click', () => refreshModelRegistry());
  onOptional('checkModelGatesBtn', 'click', checkSelectedModelGates);
  onOptional('recordModelTestsBtn', 'click', recordSelectedModelTestEvidence);
  onOptional('evaluateModelBtn', 'click', evaluateSelectedModel);
  onOptional('approveModelBtn', 'click', approveSelectedModel);
  onOptional('promoteModelBtn', 'click', promoteSelectedModel);
  onOptional('rejectModelBtn', 'click', rejectSelectedModel);
  onOptional('rollbackModelBtn', 'click', rollbackSelectedModel);
  const recommendationRows = () => state.recommendationStatusFilter === 'all'
    ? state.recommendations
    : (state.recommendationGroups.length ? state.recommendationGroups : state.recommendations.filter((item) => item.status === 'pending_review'));
  setupSearch('recommendationSearch', () => {
    state.recPage = 1;
    renderRecommendationRows('latestRecommendations', recommendationRows());
  }, (val) => { state.recommendationSearchFilter = val.trim(); });
  const recommendationStatusFilter = $('recommendationStatusFilter');
  if (recommendationStatusFilter) {
    recommendationStatusFilter.value = state.recommendationStatusFilter;
    recommendationStatusFilter.addEventListener('change', () => {
      state.recommendationStatusFilter = recommendationStatusFilter.value || 'pending_review';
      state.recPage = 1;
      renderRecommendationRows('latestRecommendations', recommendationRows());
    });
  }
  const skillGapTypeFilter = $('skillGapTypeFilter');
  if (skillGapTypeFilter) {
    skillGapTypeFilter.addEventListener('change', () => {
      state.skillGapTypeFilter = skillGapTypeFilter.value;
      state.skillGapPage = 1;
      renderSkillGapRows('skillGapRows', state.skillGapSummary?.gaps || []);
    });
  }
  setupSearch('skillMappingSearch', () => {
    state.skillMappingPage = 1;
    renderSkillMappingRows('skillMappingRows', state.skillMappings);
  }, (val) => { state.skillMappingSearchFilter = val; });
  setupSearch('skillGapSearch', () => {
    state.skillGapPage = 1;
    renderSkillGapRows('skillGapRows', state.skillGapSummary?.gaps || []);
  }, (val) => { state.skillGapSearchFilter = val; });
  setupSearch('forecastSearch', () => {
    state.forecastPage = 1;
    renderForecastRows('forecastRows', state.forecasts);
  }, (val) => { state.forecastSearchFilter = val; });
  setupSearch('governanceSearch', () => {
    state.governancePage = 1;
    renderGovernanceRows('governanceRows', state.recommendationHistory);
  }, (val) => { state.governanceSearchFilter = val; });
  setupSearch('curriculumSearch', () => {
    state.curriculumPage = 1;
    renderCurriculum();
  }, (val) => { state.curriculumSearchFilter = val; });
  const curriculumStatusFilter = $('curriculumStatusFilter');
  if (curriculumStatusFilter) {
    curriculumStatusFilter.addEventListener('change', () => {
      state.curriculumStatusFilter = curriculumStatusFilter.value;
      state.curriculumPage = 1;
      renderCurriculum();
    });
  }
  const refreshCurriculumBtn = $('refreshCurriculumBtn');
  if (refreshCurriculumBtn) refreshCurriculumBtn.addEventListener('click', refreshCurriculumState);
  const curriculumDetailClose = $('curriculumDetailClose');
  if (curriculumDetailClose) curriculumDetailClose.addEventListener('click', closeCurriculumDetail);

  const runSkillExtractionBtn = $('runSkillExtractionBtn');
  if (runSkillExtractionBtn) runSkillExtractionBtn.addEventListener('click', runSkillExtraction);
  const runGapAnalysisBtn = $('runGapAnalysisBtn');
  if (runGapAnalysisBtn) runGapAnalysisBtn.addEventListener('click', runGapAnalysis);
  const refreshSkillsBtn = $('refreshSkillsBtn');
  if (refreshSkillsBtn) refreshSkillsBtn.addEventListener('click', refreshSkillsData);

  const loadReadinessBtn = $('loadReadinessBtn');
  if (loadReadinessBtn) loadReadinessBtn.addEventListener('click', loadIngestionReadiness);
  const loadFreshnessBtn = $('loadFreshnessBtn');
  if (loadFreshnessBtn) loadFreshnessBtn.addEventListener('click', loadSourceFreshness);
  const loadDueSchedulesBtn = $('loadDueSchedulesBtn');
  if (loadDueSchedulesBtn) loadDueSchedulesBtn.addEventListener('click', loadDueSchedules);
  const simulateJobBoardBtn = $('simulateJobBoardBtn');
  if (simulateJobBoardBtn) simulateJobBoardBtn.addEventListener('click', simulateJobBoardIngestion);

  const loadForecastQualityBtn = $('loadForecastQualityBtn');
  if (loadForecastQualityBtn) loadForecastQualityBtn.addEventListener('click', loadForecastQuality);
  const refreshRankingBtn = $('refreshRankingBtn');
  if (refreshRankingBtn) refreshRankingBtn.addEventListener('click', refreshPredictionRanking);
  const archivePredictionReportBtn = $('archivePredictionReportBtn');
  if (archivePredictionReportBtn) archivePredictionReportBtn.addEventListener('click', archivePredictionReport);

  const runModelEvaluationBtn = $('runModelEvaluationBtn');
  if (runModelEvaluationBtn) runModelEvaluationBtn.addEventListener('click', runModelEvaluation);
  const loadSecurityReadinessBtn = $('loadSecurityReadinessBtn');
  if (loadSecurityReadinessBtn) loadSecurityReadinessBtn.addEventListener('click', loadSecurityReadiness);
  onOptional('loadSystemPerformanceBtn', 'click', loadSystemPerformance);
  onOptional('evaluateMonitoringBtn', 'click', evaluateMonitoring);
  onOptional('refreshAlertsBtn', 'click', refreshSystemAlerts);
  const systemAlertRows = $('systemAlertRows');
  if (systemAlertRows) systemAlertRows.addEventListener('click', (event) => {
    const button = event.target.closest('[data-ack-alert]');
    if (button) acknowledgeSystemAlert(button.dataset.ackAlert);
  });
  const loadDeploymentReadinessBtn = $('loadDeploymentReadinessBtn');
  if (loadDeploymentReadinessBtn) loadDeploymentReadinessBtn.addEventListener('click', loadDeploymentReadiness);
  const runPortalUatBtn = $('runPortalUatBtn');
  if (runPortalUatBtn) runPortalUatBtn.addEventListener('click', runPortalUat);
  const generateBackupManifestBtn = $('generateBackupManifestBtn');
  if (generateBackupManifestBtn) generateBackupManifestBtn.addEventListener('click', generateBackupManifest);
  onOptional('loadBackupLifecycleBtn', 'click', loadBackupLifecycle);
  onOptional('applyBackupRetentionBtn', 'click', applyBackupRetention);
  onOptional('runRestoreDrillBtn', 'click', runRestoreDrill);
  onOptional('loadRollbackReadinessBtn', 'click', loadRollbackReadiness);
  onOptional('runApplicationRollbackBtn', 'click', runApplicationRollbackRehearsal);
  onOptional('runDatabaseRollbackBtn', 'click', runDatabaseRollbackRehearsal);
  onOptional('loadResearchClaimsBtn', 'click', loadResearchClaims);
  onOptional('archiveResearchClaimsBtn', 'click', archiveResearchClaims);
  const subjectProfileStatusFilter = $('subjectProfileStatusFilter');
  if (subjectProfileStatusFilter) subjectProfileStatusFilter.addEventListener('change', () => {
    state.subjectProfileStatusFilter = subjectProfileStatusFilter.value || 'active_review';
    loadSubjectProfiles(false);
  });
  const refreshSubjectProfilesBtn = $('refreshSubjectProfilesBtn');
  if (refreshSubjectProfilesBtn) refreshSubjectProfilesBtn.addEventListener('click', () => loadSubjectProfiles(true));
  const subjectProfileValidationRows = $('subjectProfileValidationRows');
  if (subjectProfileValidationRows) subjectProfileValidationRows.addEventListener('click', (event) => {
    const button = event.target.closest('.subject-profile-edit-btn');
    if (button) openSubjectProfileValidation(button.dataset.profileId);
  });
  const closeSubjectProfileValidationBtn = $('closeSubjectProfileValidationBtn');
  if (closeSubjectProfileValidationBtn) closeSubjectProfileValidationBtn.addEventListener('click', closeSubjectProfileValidation);
  const submitSubjectProfileValidationBtn = $('submitSubjectProfileValidationBtn');
  if (submitSubjectProfileValidationBtn) submitSubjectProfileValidationBtn.addEventListener('click', submitSubjectProfileValidation);

  const refreshCurriculumEvidenceReviewsBtn = $('refreshCurriculumEvidenceReviewsBtn');
  if (refreshCurriculumEvidenceReviewsBtn) refreshCurriculumEvidenceReviewsBtn.addEventListener('click', loadCurriculumEvidenceReviews);
  const curriculumEvidenceReviewRows = $('curriculumEvidenceReviewRows');
  if (curriculumEvidenceReviewRows) curriculumEvidenceReviewRows.addEventListener('click', (event) => {
    const button = event.target.closest('.curriculum-evidence-review-btn');
    if (button) openCurriculumEvidenceReview(button.dataset.versionId);
  });
  const closeCurriculumEvidenceReviewBtn = $('closeCurriculumEvidenceReviewBtn');
  if (closeCurriculumEvidenceReviewBtn) closeCurriculumEvidenceReviewBtn.addEventListener('click', closeCurriculumEvidenceReview);
  const submitCurriculumEvidenceReviewBtn = $('submitCurriculumEvidenceReviewBtn');
  if (submitCurriculumEvidenceReviewBtn) submitCurriculumEvidenceReviewBtn.addEventListener('click', submitCurriculumEvidenceReview);
  const refreshSkillMappingWorkbenchBtn = $('refreshSkillMappingWorkbenchBtn');
  if (refreshSkillMappingWorkbenchBtn) refreshSkillMappingWorkbenchBtn.addEventListener('click', loadSkillMappingWorkbench);
  onOptional('skillMappingQueueStatus', 'change', () => { state.skillMappingQueueOffset = 0; loadSkillMappingWorkbench(); });
  onOptional('skillMappingLookupBtn', 'click', () => { state.skillMappingQueueOffset = 0; loadSkillMappingWorkbench(); });
  onOptional('archiveUnsupportedSkillsBtn', 'click', archiveUnsupportedSkills);
  onOptional('skillMappingQueuePrev', 'click', () => { state.skillMappingQueueOffset = Math.max(0, (state.skillMappingQueueOffset || 0) - 100); loadSkillMappingWorkbench(); });
  onOptional('skillMappingQueueNext', 'click', () => { state.skillMappingQueueOffset = (state.skillMappingQueueOffset || 0) + 100; loadSkillMappingWorkbench(); });
  const refreshTaxonomyProvenanceBtn = $('refreshTaxonomyProvenanceBtn');
  if (refreshTaxonomyProvenanceBtn) refreshTaxonomyProvenanceBtn.addEventListener('click', loadTaxonomyProvenance);
  const generateSkillMappingsBtn = $('generateSkillMappingsBtn');
  if (generateSkillMappingsBtn) generateSkillMappingsBtn.addEventListener('click', generateSkillMappings);
  const skillMappingReviewRows = $('skillMappingReviewRows');
  if (skillMappingReviewRows) skillMappingReviewRows.addEventListener('click', (event) => {
    const button = event.target.closest('.skill-mapping-review-btn');
    if (button) openSkillMappingReview(button.dataset.mappingId);
  });
  const closeSkillMappingReviewBtn = $('closeSkillMappingReviewBtn');
  if (closeSkillMappingReviewBtn) closeSkillMappingReviewBtn.addEventListener('click', closeSkillMappingReview);
  const submitSkillMappingReviewBtn = $('submitSkillMappingReviewBtn');
  if (submitSkillMappingReviewBtn) submitSkillMappingReviewBtn.addEventListener('click', submitSkillMappingReview);
  const refreshAlignmentLabelQueueBtn = $('refreshAlignmentLabelQueueBtn');
  if (refreshAlignmentLabelQueueBtn) refreshAlignmentLabelQueueBtn.addEventListener('click', loadAlignmentLabelQueue);
  const generateAlignmentTasksBtn = $('generateAlignmentTasksBtn');
  if (generateAlignmentTasksBtn) generateAlignmentTasksBtn.addEventListener('click', generateAlignmentTasks);
  const alignmentLabelTaskRows = $('alignmentLabelTaskRows');
  if (alignmentLabelTaskRows) alignmentLabelTaskRows.addEventListener('click', (event) => {
    const button = event.target.closest('.alignment-label-task-btn');
    if (button) openAlignmentLabelTask(button.dataset.taskId);
  });
  const closeAlignmentLabelBtn = $('closeAlignmentLabelBtn');
  if (closeAlignmentLabelBtn) closeAlignmentLabelBtn.addEventListener('click', closeAlignmentLabelTask);
  const submitAlignmentLabelBtn = $('submitAlignmentLabelBtn');
  if (submitAlignmentLabelBtn) submitAlignmentLabelBtn.addEventListener('click', submitAlignmentLabel);
  const lockAlignmentLabelSnapshotBtn = $('lockAlignmentLabelSnapshotBtn');
  if (lockAlignmentLabelSnapshotBtn) lockAlignmentLabelSnapshotBtn.addEventListener('click', lockAlignmentLabelSnapshot);
  const buildAlignmentSampleBtn = $('buildAlignmentSampleBtn');
  if (buildAlignmentSampleBtn) buildAlignmentSampleBtn.addEventListener('click', buildAlignmentSample);
  const exportAlignmentLabelSnapshotBtn = $('exportAlignmentLabelSnapshotBtn');
  if (exportAlignmentLabelSnapshotBtn) exportAlignmentLabelSnapshotBtn.addEventListener('click', exportAlignmentLabelSnapshot);
  onOptional('previewAssistedLabelsBtn', 'click', previewAssistedLabels);
  onOptional('selectAllAssistedLabelsBtn', 'click', selectAllAssistedLabels);
  onOptional('confirmAssistedLabelsBtn', 'click', confirmAssistedLabels);
  onOptional('lockAssistedSnapshotBtn', 'click', lockAssistedSnapshot);
  const assistedLabelRows = $('assistedLabelRows');
  if (assistedLabelRows) assistedLabelRows.addEventListener('change', () => {
    const button = $('confirmAssistedLabelsBtn');
    if (button) button.disabled = !document.querySelector('.assisted-label-checkbox:checked');
  });

  const refreshDhetOfoBtn = $('refreshDhetOfoBtn');
  if (refreshDhetOfoBtn) refreshDhetOfoBtn.addEventListener('click', () => {
    loadDhetOfoSource();
    loadDhetOfoMappings();
    loadDhetOfoStats();
  });
  const discoverDhetOfoBtn = $('discoverDhetOfoBtn');
  if (discoverDhetOfoBtn) discoverDhetOfoBtn.addEventListener('click', discoverDhetOfo);
  const downloadDhetOfoBtn = $('downloadDhetOfoBtn');
  if (downloadDhetOfoBtn) downloadDhetOfoBtn.addEventListener('click', downloadDhetOfo);
  const dhetOfoConfirmCheck = $('dhetOfoConfirmCheck');
  if (dhetOfoConfirmCheck) dhetOfoConfirmCheck.addEventListener('change', () => {
    if (downloadDhetOfoBtn) downloadDhetOfoBtn.disabled = !dhetOfoConfirmCheck.checked;
  });
  const uploadDhetOfoBtn = $('uploadDhetOfoBtn');
  if (uploadDhetOfoBtn) uploadDhetOfoBtn.addEventListener('click', () => $('dhetOfoFileInput')?.click());
  const dhetOfoFileInput = $('dhetOfoFileInput');
  if (dhetOfoFileInput) dhetOfoFileInput.addEventListener('change', uploadDhetOfo);
  const dhetOfoAcquisitionRows = $('dhetOfoAcquisitionRows');
  if (dhetOfoAcquisitionRows) dhetOfoAcquisitionRows.addEventListener('click', (event) => {
    const validateBtn = event.target.closest('.dhet-validate-btn');
    if (validateBtn) { validateDhetOfo(validateBtn.dataset.acqId); return; }
    const importBtn = event.target.closest('.dhet-import-btn');
    if (importBtn) importDhetOfo(importBtn.dataset.acqId);
  });
  const proposeDhetOfoMappingBtn = $('proposeDhetOfoMappingBtn');
  if (proposeDhetOfoMappingBtn) proposeDhetOfoMappingBtn.addEventListener('click', proposeDhetOfoMapping);
  const refreshDhetOfoMappingsBtn = $('refreshDhetOfoMappingsBtn');
  if (refreshDhetOfoMappingsBtn) refreshDhetOfoMappingsBtn.addEventListener('click', () => {
    loadDhetOfoMappings();
    loadDhetOfoStats();
  });
  const refreshDhetOfoBreakdownBtn = $('refreshDhetOfoBreakdownBtn');
  if (refreshDhetOfoBreakdownBtn) refreshDhetOfoBreakdownBtn.addEventListener('click', loadDhetOfoBreakdown);
  const dhetOfoMappingRows = $('dhetOfoMappingRows');
  if (dhetOfoMappingRows) dhetOfoMappingRows.addEventListener('click', (event) => {
    const button = event.target.closest('.dhet-mapping-review-btn');
    if (button) openDhetOfoReview(button.dataset.mappingId);
  });
  const closeDhetOfoReviewBtn = $('closeDhetOfoReviewBtn');
  if (closeDhetOfoReviewBtn) closeDhetOfoReviewBtn.addEventListener('click', closeDhetOfoReview);
  const submitDhetOfoReviewBtn = $('submitDhetOfoReviewBtn');
  if (submitDhetOfoReviewBtn) submitDhetOfoReviewBtn.addEventListener('click', submitDhetOfoReview);

  $('logoutBtn').addEventListener('click', () => {
    auth.clearToken();
    window.location.href = 'index.html';
  });

  $('changePasswordBtn').addEventListener('click', () => {
    $('cpCurrentPassword').value = '';
    $('cpNewPassword').value = '';
    $('cpConfirmPassword').value = '';
    $('changePasswordModal').classList.remove('hidden');
  });

  $('cpCancelBtn').addEventListener('click', () => {
    $('changePasswordModal').classList.add('hidden');
  });

  $('cpConfirmBtn').addEventListener('click', async () => {
    const current = $('cpCurrentPassword').value;
    const newPwd = $('cpNewPassword').value;
    const confirm = $('cpConfirmPassword').value;

    if (!current || !newPwd || !confirm) {
      showToast('Please fill in all fields.', 'error');
      return;
    }
    if (newPwd.length < 8) {
      showToast('New password must be at least 8 characters.', 'error');
      return;
    }
    if (newPwd !== confirm) {
      showToast('New password and confirmation do not match.', 'error');
      return;
    }

    $('cpConfirmBtn').disabled = true;
    try {
      const res = await auth.fetch(API_ENDPOINTS.AUTH.CHANGE_PASSWORD, {
        method: 'POST',
        body: JSON.stringify({
          current_password: current,
          new_password: newPwd,
          confirm_new_password: confirm,
        }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Password change failed');
      }
      $('changePasswordModal').classList.add('hidden');
      showToast('Password changed successfully.', 'ok');
    } catch (e) {
      showToast('Error: ' + e.message, 'error');
    } finally {
      $('cpConfirmBtn').disabled = false;
    }
  });

  $('changePasswordModal').addEventListener('click', (e) => {
    if (e.target === $('changePasswordModal')) $('changePasswordModal').classList.add('hidden');
  });
}

function canAccessDefaultView(view) {
  const roles = (state.user?.roles || []).map((r) => String(r).toLowerCase());
  const isAdmin = Boolean(state.user?.is_admin) || roles.some((r) => ['admin', 'administrator'].includes(r));
  const isAnalyst = roles.some((r) => ['analyst', 'data_analyst', 'data scientist', 'data_scientist'].includes(r));
  const isDataScientist = roles.some((r) => ['data scientist', 'data_scientist'].includes(r));
  if (view === 'systemOperations') return isAdmin;
  if (view === 'dataOperations') return isAdmin || isAnalyst;
  if (view === 'modelLab') return isAdmin || isDataScientist;
  return true;
}

wireEventListeners();
window.switchView = switchView;
const requestedDecisionView = new URLSearchParams(window.location.search).get('view');
if (requestedDecisionView && ['executive', 'curriculum', 'skills', 'forecast', 'governance', 'reports', 'systemDocumentation'].includes(requestedDecisionView)) {
  switchView(requestedDecisionView);
}
// Specialist entry pages should display their intended workspace immediately
// while authenticated profile/data requests are still loading. Access is
// re-checked against the loaded user below.
if (window.FUTURE_DEFAULT_VIEW) {
  switchView(window.FUTURE_DEFAULT_VIEW);
}
loadDashboard().then(() => {
  if (window.FUTURE_DEFAULT_VIEW) {
    if (canAccessDefaultView(window.FUTURE_DEFAULT_VIEW)) {
      switchView(window.FUTURE_DEFAULT_VIEW);
    } else {
      showToast('You do not have access to this restricted page.', 'error');
      switchView('executive');
    }
  }
  startIngestionMonitor();
});





