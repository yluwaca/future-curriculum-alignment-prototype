// dashboard-state.js - State management and API helpers
import { auth } from './auth.js';
import { API_ENDPOINTS } from './config.js?v=20260825b';
import { $, showToast, renderPagination, renderKeyValueRows, renderBars, renderEmpty, formatNumber, percent, escapeHtml, statusBadge, statusTone, skillName, countBy, average, formatFileSize } from './dashboard-utils.js?v=20260825b';
import { renderExecutive, renderCurriculum, renderSkills, renderForecasts, renderGovernance, renderReports, renderIngestionQuality } from './dashboard-views.js?v=20260912d';

    const state = {
      user: null,
      documents: [],
      documentDetails: [],
      curriculumHierarchy: { faculties: [], departments: [], programmes: [], modules: [] },
      subjectProfiles: [],
      subjectProfileStatusFilter: 'active_review',
      curriculumQuality: null,
      skillsSummary: {},
      skills: [],
      skillMappings: [],
      analyticsSummary: {},
      alignmentScores: [],
      forecasts: [],
      modelReadiness: null,
      modelMetrics: null,
      modelDatasetSnapshot: null,
      modelDatasetSnapshots: [],
      modelRegistryEntries: [],
      modelRuntimeContinuity: null,
      validatedRegenerationReadiness: null,
      selectedModelRegistryEntry: null,
      forecastQuality: null,
      recommendations: [],
      recommendationGroups: [],
      skillGapSummary: { gaps: [] },
      selectedSkillGapEvidence: null,
      generatedReports: [],
      pipelineRuns: [],
      operationalJobs: [],
      recommendationReviews: [],
      recommendationFeedback: [],
      recommendationHistory: [],
      selectedRecommendationDossier: null,
      ingestionJobs: [],
      ingestionSources: [],
      connectorDefinitions: [],
      normaliserDefinitions: [],
      ingestionContracts: [],
      ingestionFailures: [],
      ingestionOperationsSummary: null,

      selectedContract: null,
      selectedContractDrift: null,
      reviewRecords: [],
      curriculumDiscovery: null,
      qualitySummaries: {},
      qualityChecks: [],
      labourTrendSummary: {},
      vectorStatus: null,
      processingSummary: null,
      ingestionDataQuality: null,
      skillsValidity: null,
      alignmentCalibration: null,
      securityReadiness: null,
      monitoringEvaluation: null,
      systemPerformance: null,
      systemAlerts: [],
      deploymentReadiness: null,
      portalUat: null,
      researchClaims: null,
      selectedSource: null,
      selectedSourceHealth: null,
      selectedSourceHealthHistory: null,
      selectedSourceFiles: [],
      xgboostLastTrained: null,
      lstmLastTrained: null,
      curriculumSearchFilter: '',
      curriculumStatusFilter: '',
      curriculumPage: 1,
      selectedCurriculumDoc: null,
      recommendationSearchFilter: '',
      recommendationStatusFilter: 'pending_review',
      skillMappingSearchFilter: '',
      skillGapSearchFilter: '',
      skillGapTypeFilter: '',
      forecastSearchFilter: '',
      _forecastQualityLoading: false,
      _skillsValidityLoading: false,
      governanceSearchFilter: '',
      recPage: 1,
      skillMappingPage: 1,
      skillGapPage: 1,
      forecastPage: 1,
      governancePage: 1,
    };
    const titles = {
      executive: ['Executive Dashboard', 'System health, alignment status, and actionable priorities at a glance.'],
      curriculum: ['Curriculum Dashboard', 'Document management, version tracking, extraction quality, and ingestion activity.'],
      skills: ['Skill-Gap Dashboard', 'Canonical skills mapped to curriculum and market evidence, with governance-ready gap analysis.'],
      forecast: ['Forecast Dashboard', 'Model-driven skill demand forecasts with trend analysis, model readiness, and ML quality.'],
      modelLab: ['Model Lab', 'RBAC-restricted candidate training, validation evidence, model history, and promotion decisions.'],
      dataOperations: ['Data Operations', 'RBAC-restricted source upload, ingestion, normalisation, quality checks, and processing controls.'],
      systemOperations: ['System Operations', 'RBAC-restricted service health, security, backup, deployment, and UAT readiness.'],
      governance: ['Governance Dashboard', 'Human review, feedback, status history, and vector repository readiness.'],
      reports: ['Reports', 'Exportable snapshots for committees, governance, and curriculum review.'],
      systemDocumentation: ['System Documentation', 'Complete system reference: purpose, roles, requirements, deployment, architecture, operations, testing and limitations.'],
    };
    Object.assign(titles, {
      executive: ['Overview', 'Available evidence, alignment readiness, demand signals, and decisions at a glance.'],
      curriculum: ['Curriculum Evidence', 'Programme and module evidence, coverage, quality, and provenance.'],
      skills: ['Skills Alignment', 'Reviewed mappings and evidence-led indicators of curriculum alignment.'],
      forecast: ['Demand Outlook', 'Interpretable labour-market demand signals, confidence, and limitations.'],
      governance: ['Decision History', 'Recorded recommendation decisions, rationale, feedback, and status history.'],
      reports: ['Reports & Exports', 'Decision-ready snapshots for curriculum review and committee meetings.'],
    });
    function setStatus(message, type = '') {
      const box = $('statusBox');
      if (!box) return;
      box.textContent = message;
      box.className = `status show ${type}`;
    }


    function clearStatus() {
      const box = $('statusBox');
      if (!box) return;
      box.textContent = '';
      box.className = 'status';
    }
    async function getJson(url, fallback, timeoutMs = 300000) {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), timeoutMs);
      try {
        const headers = {};
        const token = auth.getToken();
        if (token) headers.Authorization = `Bearer ${token}`;
        const response = await fetch(url, {
          method: 'GET',
          headers,
          // Operational screens must never reuse a cached pre-action response
          // (for example, an empty model registry immediately after candidate
          // training).  The portal is a live control surface, not a static
          // reporting page.
          cache: 'no-store',
          signal: controller.signal,
        });
        if (response.status === 401) {
          auth.handleUnauthorized();
          return fallback;
        }
        if (!response.ok) {
          showToast(`API error ${response.status}: ${response.statusText} — ${url}`, 'error');
          return fallback;
        }
        return response.json();
      } catch (error) {
        if (error.name === 'AbortError') {
          showToast(`Request timed out after ${Math.round(timeoutMs / 1000)}s — ${url}`, 'error');
        } else {
          showToast(`Network error: ${error.message || 'request failed'} — ${url}`, 'error');
        }
        return fallback;
      } finally {
        clearTimeout(timeout);
      }
    }

    async function postJson(url, payload = {}, method = 'POST', timeoutMs = 300000) {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), timeoutMs);
      try {
        const headers = { 'Content-Type': 'application/json' };
        const token = auth.getToken();
        if (token) headers.Authorization = `Bearer ${token}`;
        const response = await fetch(url, {
          method,
          headers,
          body: JSON.stringify(payload),
          signal: controller.signal,
        });
        if (response.status === 401) {
          auth.handleUnauthorized();
        }
        if (!response.ok) {
          const text = await response.text();
          let detail = text;
          try {
            const parsed = JSON.parse(text);
            detail = parsed.detail || parsed.message || text;
          } catch {}
          const message = `API error ${response.status}: ${detail}`;
          showToast(message, 'error');
          throw new Error(message);
        }
        return response.json();
      } catch (error) {
        if (error.name === 'AbortError') {
          showToast(`Request timed out after ${Math.round(timeoutMs / 1000)}s — ${url}`, 'error');
        } else if (!error.message?.startsWith('API error')) {
          showToast(`Network error: ${error.message || 'request failed'} — ${url}`, 'error');
        }
        throw error;
      } finally {
        clearTimeout(timeout);
      }
    }

    async function postForm(url, formData, timeoutMs = 300000) {
      const headers = {};
      const token = auth.getToken();
      if (token) headers.Authorization = `Bearer ${token}`;
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), timeoutMs);
      try {
        const response = await fetch(url, {
          method: 'POST',
          headers,
          body: formData,
          signal: controller.signal,
        });
        clearTimeout(timeout);
        if (response.status === 401) {
          auth.handleUnauthorized();
        }
        if (!response.ok) {
          if (response.status === 413) {
            throw new Error('File too large — exceeds server upload limit');
          }
          const text = await response.text().catch(() => response.statusText);
          const short = text.length > 200 ? text.slice(0, 200) + '...' : text;
          throw new Error(short || `HTTP ${response.status}`);
        }
        return response.json();
      } catch (error) {
        clearTimeout(timeout);
        if (error.name === 'AbortError') {
          throw new Error(`Upload timed out after ${Math.round(timeoutMs / 1000)}s — file may be too large`);
        }
        if (error.message?.includes('Failed to fetch') || error.message?.includes('NetworkError')) {
          throw new Error('Network error: check your connection or file size may exceed server limit');
        }
        throw error;
      }
    }
    function resetPages() {
      state.recPage = 1;
      state.skillMappingPage = 1;
      state.skillGapPage = 1;
      state.forecastPage = 1;
      state.governancePage = 1;
      state.curriculumPage = 1;
      state.selectedCurriculumDoc = null;
    }

    function renderUser() {
      $('userName').textContent = state.user?.username || state.user?.identity_id || 'User';
      $('userEmail').textContent = state.user?.email || 'No email provided';
      // The Overview is a shared landing page. Never inherit a browser/password-manager
      // username value as a recommendation filter.
      const recommendationSearch = $('recommendationSearch');
      if (recommendationSearch) recommendationSearch.value = '';
      state.recommendationSearchFilter = '';
      const roles = (state.user?.roles || []).map((r) => String(r).toLowerCase());
      const isAdmin = Boolean(state.user?.is_admin) || roles.some((r) => ['admin', 'administrator'].includes(r));
      const isAnalyst = roles.some((r) => ['analyst', 'data_analyst', 'data scientist', 'data_scientist'].includes(r));
      const isDataScientist = roles.some((r) => ['data scientist', 'data_scientist'].includes(r));
      if (isAdmin) {
        const adminLink = $('adminLink');
        if (adminLink) adminLink.style.display = 'block';
      }
      document.querySelectorAll('[data-admin-nav]').forEach((nav) => {
        const view = nav.dataset.viewButton;
        const allowed = isAdmin ||
          (view === 'dataOperations' && isAnalyst) ||
          (view === 'modelLab' && isDataScientist);
        nav.style.display = allowed ? 'block' : 'none';
      });
      document.querySelectorAll('[data-admin-link]').forEach((nav) => {
        const role = nav.dataset.role;
        const allowed = isAdmin ||
          (role === 'analyst' && isAnalyst) ||
          (role === 'data_scientist' && isDataScientist);
        nav.style.display = allowed ? 'block' : 'none';
      });
    }
    function renderAll() {
      renderUser();
      if ($('executive')) renderExecutive();
      if ($('curriculum')) renderCurriculum();
      if ($('skills')) renderSkills();
      if ($('forecast')) renderForecasts();
      if ($('governance')) renderGovernance();
      if ($('reports')) renderReports();
      if ($('dataOperations')) renderIngestionQuality();
    }


    const actions = {};

    export { state, titles, setStatus, clearStatus, getJson, postJson, postForm, resetPages, renderAll, renderUser, actions };





