import { auth, requireAuth } from './auth.js';
import { API_ENDPOINTS } from './config.js';
import { initPage, setNavigationUser } from './shared-nav.js';

requireAuth();

try {
  const response = await auth.fetch(API_ENDPOINTS.ME);
  if (response.status === 401) {
    auth.handleUnauthorized();
  } else if (response.ok) {
    setNavigationUser(await response.json());
  }
} catch {
  // The manual remains usable if profile refresh is temporarily unavailable.
}
initPage('helpManual');

const cards = [...document.querySelectorAll('.task-card')];
const search = document.getElementById('manualSearch');
const noResults = document.getElementById('noManualResults');
let activeRole = 'all';

function applyFilters() {
  const term = search.value.trim().toLowerCase();
  let visible = 0;
  cards.forEach((card) => {
    const roleMatch = activeRole === 'all' || card.dataset.roles.split(' ').includes(activeRole);
    const haystack = `${card.dataset.search} ${card.textContent}`.toLowerCase();
    const show = roleMatch && (!term || haystack.includes(term));
    card.classList.toggle('hidden', !show);
    if (show) visible += 1;
  });
  noResults.classList.toggle('hidden', visible !== 0);
}

document.querySelectorAll('[data-manual-filter]').forEach((button) => {
  button.addEventListener('click', () => {
    activeRole = button.dataset.manualFilter;
    document.querySelectorAll('[data-manual-filter]').forEach((item) => item.classList.toggle('active', item === button));
    applyFilters();
  });
});
search.addEventListener('input', applyFilters);
document.getElementById('logoutBtn').addEventListener('click', () => {
  auth.clearToken();
  window.location.href = 'index.html';
});

const faqSection = document.getElementById('faqSection');
const faqExpand = document.getElementById('faqExpandAll');
const faqCollapse = document.getElementById('faqCollapseAll');
if (faqSection && faqExpand && faqCollapse) {
  const items = [...faqSection.querySelectorAll('details')];
  faqExpand.addEventListener('click', () => items.forEach((d) => { d.open = true; }));
  faqCollapse.addEventListener('click', () => items.forEach((d) => { d.open = false; }));
}
