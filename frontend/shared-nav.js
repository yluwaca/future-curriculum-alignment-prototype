// shared-nav.js - Shared navigation component for all FUTURE portal pages
// Provides consistent sidebar, breadcrumbs, and role-aware navigation

import { auth, parseJwt } from './auth.js';

const NAV_ITEMS = {
  decision: [
    { id: 'executive', label: 'Overview', page: 'dashboard.html', view: 'executive' },
    { id: 'curriculum', label: 'Curriculum Evidence', page: 'dashboard.html', view: 'curriculum' },
    { id: 'skills', label: 'Skills Alignment', page: 'dashboard.html', view: 'skills' },
    { id: 'forecast', label: 'Demand Outlook', page: 'dashboard.html', view: 'forecast' },
    { id: 'governance', label: 'Decision History', page: 'dashboard.html', view: 'governance' },
    { id: 'reports', label: 'Reports & Exports', page: 'dashboard.html', view: 'reports' },
    { id: 'systemDocumentation', label: 'System Documentation', page: 'dashboard.html', view: 'systemDocumentation' },
    { id: 'recommendations', label: 'Recommendations', page: 'recommendations.html' },
  ],
  modelLab: [
    { id: 'modelLab', label: 'Model Lab', page: 'model-lab.html', view: 'modelLab', roles: ['admin', 'data_scientist'] },
  ],
  dataOps: [
    { id: 'dataOperations', label: 'Data Operations', page: 'data-operations.html', view: 'dataOperations', roles: ['admin', 'analyst', 'data_scientist'] },
  ],
  systemOps: [
    { id: 'systemOperations', label: 'System Operations', page: 'system-operations.html', view: 'systemOperations', roles: ['admin'] },
  ],
  admin: [
    { id: 'admin', label: 'User Admin', page: 'admin.html', roles: ['admin'] },
  ],
  help: [
    { id: 'helpManual', label: 'Help & Tasks', page: 'help-manual.html' },
  ],
};

const PAGE_TITLES = {
  executive: { title: 'Overview', subtitle: 'Available evidence, alignment readiness, demand signals, and decisions at a glance.' },
  curriculum: { title: 'Curriculum Evidence', subtitle: 'Programme and module evidence, coverage, quality, and provenance.' },
  skills: { title: 'Skills Alignment', subtitle: 'Reviewed mappings and evidence-led indicators of curriculum alignment.' },
  forecast: { title: 'Demand Outlook', subtitle: 'Interpretable labour-market demand signals, confidence, and limitations.' },
  governance: { title: 'Decision History', subtitle: 'Recorded recommendation decisions, rationale, feedback, and status history.' },
  reports: { title: 'Reports & Exports', subtitle: 'Decision-ready snapshots for curriculum review and committee meetings.' },
  systemDocumentation: { title: 'System Documentation', subtitle: 'Complete system reference: purpose, roles, requirements, deployment, architecture, operating procedure, testing and limitations.' },
  modelLab: { title: 'Model Lab', subtitle: 'Candidate training, evaluation evidence, and model lifecycle decisions.' },
  dataOperations: { title: 'Data Operations', subtitle: 'Source ingestion, import queues, normalisation, quality checks, and processing.' },
  systemOperations: { title: 'System Operations', subtitle: 'Service health, security readiness, backups, deployment, and UAT checks.' },
  admin: { title: 'User Administration', subtitle: 'Pending approvals, role assignment, and account management.' },
  recommendations: { title: 'Recommendations', subtitle: 'Inspect recommendation evidence, confidence, status, and decision history.' },
  'user-guide': { title: 'User Guide', subtitle: 'Practical guidance for accessing and using the FUTURE Platform.' },
  'help-manual': { title: 'Help Manual', subtitle: 'Step-by-step instructions for completing tasks in your authorised workspace.' },
};

let authenticatedUser = null;

function getPageKey() {
  const path = window.location.pathname.split('/').pop() || 'dashboard.html';
  return path.replace('.html', '');
}

function getCurrentView() {
  const params = new URLSearchParams(window.location.search);
  return params.get('view') || window.FUTURE_DEFAULT_VIEW || 'executive';
}

function getUserRoles() {
  if (authenticatedUser) {
    const roles = (authenticatedUser.roles || []).map((role) =>
      String(role).toLowerCase().replaceAll(' ', '_')
    );
    if (authenticatedUser.is_admin && !roles.includes('admin')) {
      roles.push('admin');
    }
    return roles;
  }
  const token = auth.getToken();
  if (!token) return [];
  const payload = parseJwt(token);
  if (!payload) return [];
  const roles = payload.roles || [];
  return roles.map(r => r.toLowerCase());
}

export function setNavigationUser(user) {
  authenticatedUser = user || null;
}

function isAdmin() {
  const roles = getUserRoles();
  return roles.includes('admin') || roles.includes('administrator');
}

function canAccess(item) {
  if (!item.roles || item.roles.length === 0) return true;
  const userRoles = getUserRoles();
  return userRoles.some(r => item.roles.includes(r));
}

export function renderSidebar(activeView) {
  const sidebar = document.querySelector('.sidebar');
  if (!sidebar) return;

  const userRoles = getUserRoles();
  const admin = isAdmin();
  const elevated = admin || userRoles.some(role => [
    'analyst',
    'data_scientist',
    'curriculum_approver',
    'curriculum approver',
  ].includes(role));
  const viewerOnly = !elevated;
  const analyst = userRoles.includes('analyst');
  const dataScientist = userRoles.includes('data_scientist');
  const currentPage = window.location.pathname.split('/').pop();
  document.body.classList.toggle('viewer-audience', viewerOnly);
  document.body.classList.toggle('operational-audience', elevated);
  document.body.classList.toggle('analyst-audience', analyst);
  document.body.classList.toggle('data-scientist-audience', dataScientist);
  document.body.classList.toggle('admin-audience', admin);

  let html = `
    <div class="brand">
      <h1>FUTURE</h1>
      <p>Curriculum-Labour Market Alignment</p>
    </div>
    <nav class="nav">
  `;

  // Decision portal items (viewer-facing)
  NAV_ITEMS.decision.forEach(item => {
    const isActive = item.page === currentPage &&
      (item.view ? item.view === activeView : item.id === activeView);
    const cls = isActive ? 'class="active"' : '';
    if (item.page === currentPage) {
      html += item.view
        ? `<button ${cls} data-view-button="${item.view}">${item.label}</button>`
        : `<button ${cls}>${item.label}</button>`;
    } else {
      const href = item.view
        ? `${item.page}?view=${encodeURIComponent(item.view)}`
        : item.page;
      html += `<a href="${href}">${item.label}</a>`;
    }
  });

  // Separator
  html += '<div class="nav-separator"></div>';

  // Model Lab (data_scientist, admin only)
  if (admin || userRoles.includes('data_scientist')) {
    NAV_ITEMS.modelLab.forEach(item => {
      const isActive = item.page === currentPage;
      if (isActive) {
        html += `<button class="active" data-view-button="${item.view}">${item.label}</button>`;
      } else {
        html += `<a href="${item.page}">${item.label}</a>`;
      }
    });
  }

  // Data Operations (admin, analyst, data_scientist)
  if (admin || userRoles.includes('analyst') || userRoles.includes('data_scientist')) {
    NAV_ITEMS.dataOps.forEach(item => {
      const isActive = item.page === currentPage;
      if (isActive) {
        html += `<button class="active" data-view-button="${item.view}">${item.label}</button>`;
      } else {
        html += `<a href="${item.page}">${item.label}</a>`;
      }
    });
  }

  // System Operations (admin only)
  if (admin) {
    NAV_ITEMS.systemOps.forEach(item => {
      const isActive = item.page === currentPage;
      if (isActive) {
        html += `<button class="active" data-view-button="${item.view}">${item.label}</button>`;
      } else {
        html += `<a href="${item.page}">${item.label}</a>`;
      }
    });
  }

  // User Admin (admin only)
  if (admin) {
    html += '<div class="nav-separator"></div>';
    NAV_ITEMS.admin.forEach(item => {
      const isActive = item.page === currentPage;
      if (isActive) {
        html += `<button class="active nav-admin">${item.label}</button>`;
      } else {
        html += `<a href="${item.page}" class="nav-admin">${item.label}</a>`;
      }
    });
  }

  // Help
  html += '<div class="nav-separator"></div>';
  NAV_ITEMS.help.forEach(item => {
    const isActive = item.page === currentPage;
    if (isActive) {
      html += `<button class="active nav-help">${item.label}</button>`;
    } else {
      html += `<a href="${item.page}" class="nav-help">${item.label}</a>`;
    }
  });

  html += '</nav>';
  sidebar.innerHTML = html;
  wireSidebarViewButtons();
}

function wireSidebarViewButtons() {
  document.querySelectorAll('[data-view-button]').forEach((button) => {
    button.addEventListener('click', () => {
      const view = button.dataset.viewButton;
      if (typeof window.switchView !== 'function') return;
      window.switchView(view);
      renderBreadcrumbs(view);
      document.querySelectorAll('.nav [data-view-button]').forEach((item) => {
        item.classList.toggle('active', item === button);
      });
      const url = new URL(window.location.href);
      url.searchParams.set('view', view);
      window.history.replaceState({}, '', url);
    });
  });
}

export function renderBreadcrumbs(activeView) {
  const pageKey = getPageKey();
  const pageInfo = PAGE_TITLES[activeView] || PAGE_TITLES[pageKey] || { title: 'FUTURE Platform', subtitle: '' };

  const pageTitle = document.getElementById('pageTitle');
  const pageSubtitle = document.getElementById('pageSubtitle');
  if (pageTitle) pageTitle.textContent = pageInfo.title;
  if (pageSubtitle) pageSubtitle.textContent = pageInfo.subtitle;
}

export function renderUserbox() {
  const token = auth.getToken();
  if (!token) return;

  const payload = parseJwt(token);
  if (!payload) return;

  const userName = document.getElementById('userName');
  const userEmail = document.getElementById('userEmail');
  if (userName) userName.textContent = payload.sub || payload.email || 'User';
  if (userEmail) userEmail.textContent = payload.email || '';
}

export function initPage(defaultView) {
  const view = defaultView || getCurrentView();
  renderSidebar(view);
  renderBreadcrumbs(view);
  renderUserbox();

}

export { PAGE_TITLES, NAV_ITEMS };
