// config.js
// FUTURE Platform Frontend Configuration

// =====================================================
// ENVIRONMENT DETECTION
// =====================================================

const hostname = window.location.hostname;

const isLocalhost =
  hostname === 'localhost' ||
  hostname === '127.0.0.1';

// =====================================================
// API BASE URL
// =====================================================

// IMPORTANT:
// - In DEV â†’ always call FastAPI directly (port 8000)
// - In PROD â†’ use relative path (NGINX proxy)

const API_BASE_URL = isLocalhost
  ? 'http://127.0.0.1:8000/api/v1'
  : '/api/v1';

// =====================================================
// GLOBAL CONFIGURATION
// =====================================================

export const CONFIG = {
  // ---------------------------------------------------
  // API
  // ---------------------------------------------------
  API_BASE_URL,

  // ---------------------------------------------------
  // Application Metadata
  // ---------------------------------------------------
  APP_NAME: 'FUTURE Platform',
  APP_VERSION: '1.0.0',

  // ---------------------------------------------------
  // Authentication
  // ---------------------------------------------------
  TOKEN_KEY: 'access_token',

  // Refresh token slightly before expiry
  TOKEN_EXPIRY_BUFFER_MS: 5 * 60 * 1000,

  // ---------------------------------------------------
  // Network / Timeout
  // ---------------------------------------------------
  DEFAULT_TIMEOUT_MS: 30000,
  MAX_LOGIN_ATTEMPTS: 3,

  // ---------------------------------------------------
  // Feature Flags
  // ---------------------------------------------------
  ENABLE_REGISTRATION: true,
  ENABLE_PASSWORD_RESET: false,

  // ---------------------------------------------------
  // Labour Market Settings
  // ---------------------------------------------------
  POLL_INTERVAL_MS: 2000,
};

// =====================================================
// API ENDPOINT BUILDER
// =====================================================

function build(path) {
  return `${CONFIG.API_BASE_URL}${path}`;
}

// =====================================================
// API ENDPOINTS
// =====================================================

export const API_ENDPOINTS = {
  // ---------------------------------------------------
  // AUTH
  // ---------------------------------------------------
  AUTH: {
    LOGIN: build('/auth/login'),
    LOGOUT: build('/auth/logout'),
    REGISTER: build('/auth/register'),
    ME: build('/auth/me'),
    REFRESH: build('/auth/refresh'),
    CHANGE_PASSWORD: build('/auth/change-password'),
  },

  // ---------------------------------------------------
  // ADMIN
  // ---------------------------------------------------
  ADMIN: {
    USERS: build('/admin/users'),
    USER_DETAIL: (userId) => build(`/admin/users/${userId}`),
    APPROVE_USER: (userId) => build(`/admin/users/${userId}/approve`),
    REJECT_USER: (userId) => build(`/admin/users/${userId}/reject`),
    UPDATE_ROLES: (userId) => build(`/admin/users/${userId}/roles`),
    UPDATE_STATUS: (userId) => build(`/admin/users/${userId}/status`),
    RESET_PASSWORD: (userId) => build(`/admin/users/${userId}/reset-password`),
    ROLES: build('/admin/roles'),
  },

  // ---------------------------------------------------
  // LABOUR MARKET
  // ---------------------------------------------------
  LABOUR_MARKET: {
    EXTRACT_STATSSA: build('/labour-market/extract/statssa'),
    JOBS: build('/labour-market/jobs'),
    JOBS_UPLOAD: build('/labour-market/jobs/upload'),
    TRENDS_NORMALISE: build('/labour-market/trends/normalise'),
    TRENDS_SUMMARY: build('/labour-market/trends/summary'),
    TRENDS: build('/labour-market/trends'),
    SIGNALS_GENERATE: build('/labour-market/signals/generate'),
    SIGNALS: build('/labour-market/signals'),
    SKILL_PIPELINE: build('/labour-market/jobs/skill-pipeline'),
    SKILL_PIPELINE_SIGNALS: build('/labour-market/jobs/skill-pipeline/signals'),
    SKILL_PIPELINE_RUNS: build('/labour-market/jobs/skill-pipeline/runs'),
    SKILL_PIPELINE_TRIAL_SIGNALS: build('/labour-market/jobs/skill-pipeline/signals'),

    JOB_STATUS: (jobId) => build(`/labour-market/job/${jobId}`),
  },

  // ---------------------------------------------------
  // DYNAMIC INGESTION
  // ---------------------------------------------------
  INGESTION: {
    OPERATIONS_SUMMARY: build('/ingestion/operations-summary'),
    CONNECTORS: build('/ingestion/connectors'),
    CONNECTOR_DETAIL: (connectorKey) => build(`/ingestion/connectors/${connectorKey}`),
    NORMALISERS: build('/ingestion/normalisers'),
    NORMALISER_DETAIL: (normaliserKey) => build(`/ingestion/normalisers/${normaliserKey}`),
    SOURCES: build('/ingestion/sources'),
    SOURCE_DETAIL: (sourceId) => build(`/ingestion/sources/${sourceId}`),
    SOURCE_CLASSIFICATION: (sourceId) => build(`/ingestion/sources/${sourceId}/classification`),
    SOURCE_HEALTH: (sourceId) => build(`/ingestion/sources/${sourceId}/health`),
    SOURCE_HEALTH_HISTORY: (sourceId) => build(`/ingestion/sources/${sourceId}/health/history`),
    SOURCE_ENABLE: (sourceId) => build(`/ingestion/sources/${sourceId}/enable`),
    SOURCE_DISABLE: (sourceId) => build(`/ingestion/sources/${sourceId}/disable`),
    SOURCE_SCHEDULE: (sourceId) => build(`/ingestion/sources/${sourceId}/schedule`),
    SOURCE_AUTH_TEST: (sourceId) => build(`/ingestion/sources/${sourceId}/auth/test`),
    SOURCE_CREDENTIALS: (sourceId) => build(`/ingestion/sources/${sourceId}/credentials`),
    SOURCE_FILES: (sourceId) => build(`/ingestion/sources/${sourceId}/files`),
    GENERIC_INTAKE: build('/ingestion/generic-intake'),
    GENERIC_INTAKE_BATCH: build('/ingestion/generic-intake-batch'),
    KNOWN_SOURCES: build('/ingestion/sources/known'),
    IMPORT_JOB: (jobId) => build(`/ingestion/jobs/${jobId}/import`),
    IMPORT_JOB_ASYNC: (jobId) => build(`/ingestion/jobs/${jobId}/import-async`),
    SOURCE_FRESHNESS: build('/ingestion/source-freshness'),
    READINESS: build('/ingestion/readiness'),
    SCHEDULES_DUE: build('/ingestion/schedules/due'),
    SCHEDULES_RUN_DUE: build('/ingestion/schedules/run-due'),
    JOB_BOARD_CONTRACTS: build('/ingestion/job-board/contracts'),
    JOB_BOARD_SIMULATE: build('/ingestion/job-board/simulate'),
    FILE_DOWNLOAD: build('/ingestion/files/download'),
    JOBS: build('/ingestion/jobs'),
    JOB_DETAIL: (jobId) => build(`/ingestion/jobs/${jobId}`),
    JOB_RETRY: (jobId) => build(`/ingestion/jobs/${jobId}/retry`),
    JOB_FAILURES: (jobId) => build(`/ingestion/jobs/${jobId}/failures`),
    FAILURES: build('/ingestion/failures'),
    START_STATSSA: build('/ingestion/statssa/jobs'),
    START_CHE_VITALSTATS: build('/ingestion/che/vitalstats/jobs'),
    CONTRACTS: build('/ingestion/contracts'),
    CONTRACT_DETAIL: (contractId) => build(`/ingestion/contracts/${contractId}`),
    CONTRACT_CLONE: (contractId) => build(`/ingestion/contracts/${contractId}/clone`),
    CONTRACT_DRIFT: (contractId) => build(`/ingestion/contracts/${contractId}/drift`),
    RECORDS_REVIEW: build('/ingestion/records/review'),
    RECORD_REVIEW: (recordId) => build(`/ingestion/records/${recordId}/review`),
    QUALITY_RUN: (jobId) => build(`/ingestion/jobs/${jobId}/quality/run`),
    QUALITY_SUMMARY: (jobId) => build(`/ingestion/jobs/${jobId}/quality/summary`),
    QUALITY_CHECKS: (jobId) => build(`/ingestion/jobs/${jobId}/quality/checks`),
    CLEANED_RECORDS: (jobId) => build(`/ingestion/jobs/${jobId}/cleaned-records`),
    INGESTION_DATA_QUALITY: build('/ingestion/data-quality/summary'),
    REMAP_TABLE_ROWS: build('/ingestion/data-quality/remap-table-rows'),
  },

  // ---------------------------------------------------
  // PIPELINE ORCHESTRATION
  // ---------------------------------------------------
  PIPELINE: {
    RUN_STATSSA_FULL: build('/pipeline/statssa/full-run'),
    RUNS: build('/pipeline/runs'),
    RUN_DETAIL: (pipelineRunId) => build(`/pipeline/runs/${pipelineRunId}`),
  },

  // ---------------------------------------------------
  // PROCESSING PHASE
  // ---------------------------------------------------
  PROCESSING: {
    SUMMARY: build('/processing/summary'),
    RUN: build('/processing/run'),
    RUN_FULL: build('/processing/run/full'),
    VALIDATED_REGENERATION_READINESS: build('/processing/validated-regeneration/readiness'),
    VALIDATED_REGENERATION_RUN: build('/processing/validated-regeneration/run'),
    RERUN_ALIGNMENT: build('/processing/run/alignment'),
    RERUN_FORECASTS: build('/processing/run/forecasts'),
    RERUN_RECOMMENDATIONS: build('/processing/run/recommendations'),
  },

  // ---------------------------------------------------
  // CURRICULUM DOCUMENTS
  // ---------------------------------------------------
  CURRICULUM: {
    DOCUMENTS: build('/curriculum/documents'),
    HIERARCHY: build('/curriculum/hierarchy'),
    QUALITY_SUMMARY: build('/curriculum/quality/summary'),
    UPLOAD: build('/curriculum/documents/upload'),
    IMPORT_API: build('/curriculum/documents/import-api'),
    DISCOVER_SOURCES: build('/curriculum/sources/discover'),
    IMPORT_CPUT_PROSPECTUS: build('/curriculum/import/cput-prospectus'),
    CPUT_PROSPECTUS_COURSES: (facultyCode) => build(`/curriculum/cput-prospectus/courses?faculty_code=${encodeURIComponent(facultyCode || '220')}`),
    DOCUMENT_DETAIL: (documentId) => build(`/curriculum/documents/${documentId}`),
    DOCUMENT_VERSIONS: (documentId) => build(`/curriculum/documents/${documentId}/versions`),
    VERSION_CHUNKS: (versionId) => build(`/curriculum/versions/${versionId}/chunks`),
    EVIDENCE_REVIEW_QUEUE: build('/curriculum/evidence-reviews/queue'),
    EVIDENCE_REVIEWS: (versionId) => build(`/curriculum/versions/${versionId}/evidence-reviews`),
    GOVERNANCE_CHAIN: build('/curriculum/governance/chain'),
    GOVERNANCE_EVIDENCE: build('/curriculum/governance/evidence'),
    SUBJECT_PROFILES: build('/curriculum/subject-profiles/consolidated'),
    SUBJECT_PROFILE: (profileId) => build(`/curriculum/subject-profiles/${profileId}`),
  },

  // ---------------------------------------------------
  // SKILLS / ESCO
  // ---------------------------------------------------
  SKILLS: {
    SUMMARY: build('/skills/summary'),
    LIST: build('/skills'),
    MAPPINGS: build('/skills/mappings'),
    DEMAND_EVIDENCE: build('/skills/demand-evidence'),
    GENERATE_DEMAND_EVIDENCE: build('/skills/demand-evidence/generate'),
    EXTRACT_CURRICULUM: build('/skills/extract/curriculum'),
    EXTRACT_LABOUR_MARKET: build('/skills/extract/labour-market'),
    EXTRACT_EVIDENCE_JOB: build('/skills/extract/evidence-job'),
    SKILLS_READINESS: build('/skills/readiness'),
    ALIGNMENT_CALIBRATION: build('/skills/alignment-calibration'),
    SEMANTIC_CANDIDATES: (skillId) => build(`/skills/semantic-candidates/${skillId}`),
    GOVERNANCE_WORKBENCH: build('/skills/governance/workbench'),
    MAPPING_REVIEW: (mappingId) => build(`/skills/mappings/${mappingId}/review`),
  },
  ALIGNMENT_LABELS: {
    TASKS: build('/alignment-labels/tasks'),
    GENERATE_TASKS: build('/alignment-labels/tasks/generate'),
    SAMPLE: build('/alignment-labels/tasks/sample'),
    DISAGREEMENTS: build('/alignment-labels/tasks/disagreements'),
    QUALITY: build('/alignment-labels/quality'),
    SUBMIT_LABEL: (taskId) => build(`/alignment-labels/tasks/${taskId}/labels`),
    SNAPSHOTS: build('/alignment-labels/snapshots'),
    LATEST_SNAPSHOT: build('/alignment-labels/snapshots/latest'),
    SNAPSHOT_EXPORT: (snapshotId) => build(`/alignment-labels/snapshots/${snapshotId}/export`),
    LOCK_SNAPSHOT: build('/alignment-labels/snapshots/lock'),
    RULE_ASSISTED_PROPOSALS: build('/alignment-labels/rule-assisted/proposals'),
    RULE_ASSISTED_CONFIRM: build('/alignment-labels/rule-assisted/confirm'),
  },

  // ---------------------------------------------------
  // ANALYTICS / RECOMMENDATIONS
  // ---------------------------------------------------
  ANALYTICS: {
    SUMMARY: build('/analytics/summary'),
    GENERATE: build('/analytics/generate'),
    ALIGNMENT_SCORES: build('/analytics/alignment-scores'),
    SKILL_GAPS: build('/analytics/skill-gaps'),
    SKILL_GAP_EVIDENCE: (skillId) => build(`/analytics/skill-gaps/${skillId}/evidence`),
    FORECASTS: build('/analytics/forecasts'),
    REPORTS: build('/analytics/reports'),
    REPORT_DETAIL: (reportId) => build(`/analytics/reports/${reportId}`),
    RECOMMENDATIONS: build('/analytics/recommendations'),
    RECOMMENDATIONS_GROUPED: build('/analytics/recommendations/grouped'),
    RECOMMENDATION_EXPLANATIONS: (recommendationId) => build(`/analytics/recommendations/${recommendationId}/explanations`),
    RECOMMENDATION_DOSSIER: (recommendationId) => build(`/analytics/recommendations/${recommendationId}/dossier`),
    RECOMMENDATION_DOSSIER_REPORT: (recommendationId) => build(`/analytics/recommendations/${recommendationId}/dossier/report`),
    RECOMMENDATION_LINEAGE: (recommendationId) => build(`/analytics/recommendations/${recommendationId}/lineage`),
    RECOMMENDATION_APPROVE: (recommendationId) => build(`/analytics/recommendations/${recommendationId}/approve`),
    RECOMMENDATION_REJECT: (recommendationId) => build(`/analytics/recommendations/${recommendationId}/reject`),
    RECOMMENDATION_MODIFY: (recommendationId) => build(`/analytics/recommendations/${recommendationId}/modify`),
    RECOMMENDATION_REVIEWS: (recommendationId) => build(`/analytics/recommendations/${recommendationId}/reviews`),
    RECOMMENDATION_FEEDBACK: (recommendationId) => build(`/analytics/recommendations/${recommendationId}/feedback`),
    RECOMMENDATION_STATUS_HISTORY: (recommendationId) => build(`/analytics/recommendations/${recommendationId}/status-history`),
    RECOMMENDATION_GOVERNANCE_READINESS: build('/analytics/recommendation-governance/readiness'),
    RECOMMENDATION_COMMITTEE_PACK: build('/analytics/recommendation-governance/committee-pack'),
    RECOMMENDATION_COMMITTEE_DECISION: (recommendationId) => build(`/analytics/recommendations/${recommendationId}/committee-decision`),
  },

  // ---------------------------------------------------
  // SEMANTIC SEARCH / VECTOR REPOSITORY
  // ---------------------------------------------------
  SEMANTIC: {
    VECTOR_STATUS: build('/semantic/vector/status'),
    INDEX_CURRICULUM: build('/semantic/index/curriculum'),
    SEARCH: build('/semantic/search'),
  },

  // ---------------------------------------------------
  // SECURITY / OPERATIONS
  // ---------------------------------------------------
  OPERATIONS: {
    SECURITY_READINESS: build('/operations/security-readiness'),
    DEPLOYMENT_READINESS: build('/operations/deployment-readiness'),
    ROLLBACK_READINESS: build('/operations/rollback-readiness'),
    ROLLBACK_APPLICATION_REHEARSAL: build('/operations/rollback/application-rehearsal'),
    ROLLBACK_DATABASE_REHEARSAL: build('/operations/rollback/database-rehearsal'),
    RESEARCH_CLAIMS: build('/operations/research-claims'),
    RESEARCH_CLAIMS_ARCHIVE: build('/operations/research-claims/archive'),
    PORTAL_UAT_LATEST: build('/operations/portal-uat/latest'),
    PORTAL_UAT_RUN: build('/operations/portal-uat/run'),
    MONITORING: build('/operations/monitoring'),
    PERFORMANCE: build('/operations/performance'),
    MONITORING_EVALUATE: build('/operations/monitoring/evaluate'),
    ALERTS: build('/operations/alerts'),
    ALERT_ACKNOWLEDGE: (alertId) => build(`/operations/alerts/${alertId}/acknowledge`),
    SCHEDULER: build('/operations/scheduler'),
    BACKUPS: build('/operations/backups'),
    BACKUP_CREATE: build('/operations/backups/create'),
    BACKUP_RETENTION: build('/operations/backups/retention'),
    BACKUP_RETENTION_APPLY: build('/operations/backups/retention/apply'),
    BACKUP_RESTORE_DRILL: build('/operations/backups/restore-drill'),
    BACKUP_RESTORE_READINESS: build('/operations/backups/restore-readiness'),
    BACKUP_MANIFEST: build('/operations/backups/manifest'),
    JOBS: build('/operations/jobs'),
    JOB: (jobId) => build(`/operations/jobs/${jobId}`),
    JOB_RETRY: (jobId) => build(`/operations/jobs/${jobId}/retry`),
    JOB_CANCEL: (jobId) => build(`/operations/jobs/${jobId}/cancel`),
  },

  // ---------------------------------------------------
  // PREDICTIVE ANALYTICS
  // ---------------------------------------------------
  PREDICTIVE: {
    STATUS: build('/predictive/status'),
    INGEST: build('/predictive/ingest'),
    ALIGN: build('/predictive/align'),
    FORECAST: build('/predictive/forecast'),
    MODEL_READINESS: build('/predictive/model-readiness'),
    MODEL_METRICS: build('/predictive/model-metrics'),
    DATASET_SNAPSHOT_LATEST: build('/predictive/dataset-snapshots/latest'),
    DATASET_SNAPSHOTS: build('/predictive/dataset-snapshots'),
    RUN_MODEL_EVALUATION: build('/predictive/model-evaluation/run'),
    FORECAST_QUALITY: build('/predictive/forecast/quality'),
    RANKING_REFRESH: build('/predictive/forecast/recommendation-ranking/refresh'),
    EXPLAINABILITY_REPORT: build('/predictive/forecast/explainability-report'),
    TRAIN_XGBOOST: build('/predictive/train/xgboost'),
    TRAIN_XGBOOST_READINESS: build('/predictive/train/xgboost/readiness'),
    TRAIN_LSTM: build('/predictive/train/lstm'),
    MODEL_REGISTRY: build('/predictive/registry'),
    MODEL_RUNTIME_CONTINUITY: build('/predictive/registry/runtime-continuity'),
    MODEL_REGISTRY_GATES: (entryId) => build(`/predictive/registry/${entryId}/gates`),
    MODEL_REGISTRY_EVALUATE: (entryId) => build(`/predictive/registry/${entryId}/evaluate`),
    MODEL_REGISTRY_APPROVE: (entryId) => build(`/predictive/registry/${entryId}/approve`),
    MODEL_REGISTRY_PROMOTE: (entryId) => build(`/predictive/registry/${entryId}/promote`),
    MODEL_REGISTRY_REJECT: (entryId) => build(`/predictive/registry/${entryId}/reject`),
    MODEL_REGISTRY_TEST_EVIDENCE: (entryId) => build(`/predictive/registry/${entryId}/test-evidence`),
    MODEL_REGISTRY_ROLLBACK: (modelType) => build(`/predictive/registry/rollback/${modelType}`),
  },
};

API_ENDPOINTS.LOGIN = API_ENDPOINTS.AUTH.LOGIN;
API_ENDPOINTS.LOGOUT = API_ENDPOINTS.AUTH.LOGOUT;
API_ENDPOINTS.REGISTER = API_ENDPOINTS.AUTH.REGISTER;
API_ENDPOINTS.ME = API_ENDPOINTS.AUTH.ME;
API_ENDPOINTS.REFRESH = API_ENDPOINTS.AUTH.REFRESH;

// =====================================================
// DEBUG (VERY IMPORTANT FOR YOU NOW)
// =====================================================

console.log('ENV:', isLocalhost ? 'LOCAL' : 'PROD');
console.log('API_BASE_URL:', API_BASE_URL);

// =====================================================
// DEFAULT EXPORT
// =====================================================

export default {
  CONFIG,
  API_ENDPOINTS,
};






