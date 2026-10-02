// dashboard-utils.js - Pure utility functions
// No external dependencies

    const $ = (id) => document.getElementById(id);
    function showToast(message, type = '') {
      const container = $('toastContainer');
      if (!container) return;
      const toast = document.createElement('div');
      toast.className = `toast ${type}`;
      toast.textContent = message;
      container.appendChild(toast);
      setTimeout(() => { toast.remove(); }, 4000);
    }

    function showConfirm(title, message) {
      return new Promise((resolve) => {
        const modal = $('confirmModal');
        $('confirmTitle').textContent = title;
        $('confirmMessage').textContent = message;
        modal.classList.remove('hidden');
        const cleanup = () => { modal.classList.add('hidden'); };
        $('confirmOkBtn').onclick = () => { cleanup(); resolve(true); };
        $('confirmCancelBtn').onclick = () => { cleanup(); resolve(false); };
        modal.onclick = (e) => { if (e.target === modal) { cleanup(); resolve(false); } };
      });
    }
    function showSpinner(id) { const el = $(id); if (el) el.classList.remove('hidden'); }
    function hideSpinner(id) { const el = $(id); if (el) el.classList.add('hidden'); }
    function setupSearch(inputId, renderFn, setFilterFn) {
      const input = $(inputId);
      if (!input) return;
      input.addEventListener('input', () => { if (setFilterFn) setFilterFn(input.value.toLowerCase()); renderFn(); });
    }

    function paginate(data, page, pageSize) {
      const totalPages = Math.max(1, Math.ceil(data.length / pageSize));
      const safePage = Math.min(Math.max(1, page), totalPages);
      const start = (safePage - 1) * pageSize;
      return { items: data.slice(start, start + pageSize), page: safePage, pages: totalPages };
    }

    function renderPagination(id, page, pages, onPage) {
      const el = $(id);
      if (!el) return;
      if (pages <= 1) { el.innerHTML = ''; return; }
      let html = `<button ${page <= 1 ? 'disabled' : ''} data-page="${page - 1}">&laquo;</button>`;
      for (let i = Math.max(1, page - 2); i <= Math.min(pages, page + 2); i++) {
        html += `<button class="${i === page ? 'active' : ''}" data-page="${i}">${i}</button>`;
      }
      html += `<button ${page >= pages ? 'disabled' : ''} data-page="${page + 1}">&raquo;</button>`;
      html += `<span>Page ${page} of ${pages}</span>`;
      el.innerHTML = html;
      el.querySelectorAll('[data-page]').forEach((btn) => {
        btn.addEventListener('click', () => { if (!btn.disabled) onPage(Number(btn.dataset.page)); });
      });
    }

    function renderKeyValueRows(id, rows) {
      const target = $(id);
      if (!target) return;
      target.innerHTML = rows.map(([label, value, extra]) => `
        <tr><th>${escapeHtml(label)}</th><td>${escapeHtml(String(value))}</td><td>${extra}</td></tr>
      `).join('');
    }

    function renderBars(id, rows) {
      const target = $(id);
      if (!target) return;
      const total = rows.reduce((sum, row) => sum + Number(row[1] || 0), 0);
      if (!rows.length || total === 0) {
        target.innerHTML = '<div class="empty">No data available yet.</div>';
        return;
      }
      target.innerHTML = rows.map(([label, value, tone]) => {
        const width = total ? Math.max(3, (value / total) * 100) : 0;
        return `
          <div class="bar-row">
            <div class="bar-label">${escapeHtml(label)}</div>
            <div class="bar-track"><div class="bar-fill ${tone || ''}" style="width:${width}%"></div></div>
            <strong>${formatNumber(value)}</strong>
          </div>
        `;
      }).join('');
    }

    const DECISION_EMPTY_STATES = {
      recommendations: {
        title: 'No reviewable recommendations yet',
        reason: 'Recommendations are created only after curriculum evidence, skill mappings, alignment and forecasts pass their validation gates.',
        action: 'Open Data Operations to review the blocked gates and regenerate validated outputs.',
        limitation: 'An empty list is not evidence that the curriculum is aligned or that no action is needed.',
      },
      skillMappings: {
        title: 'No governed skill mappings yet',
        reason: 'Curriculum and labour-market terms have not yet been mapped to approved skills.',
        action: 'Complete mapping review in Data Operations before interpreting gaps.',
        limitation: 'Coverage and gap calculations are not meaningful without reviewed mappings.',
      },
      skillGaps: {
        title: 'No validated skill-gap results yet',
        reason: 'Gap analysis needs validated curriculum evidence, approved mappings and labour-market evidence.',
        action: 'Complete the evidence gates, then run validated output regeneration.',
        limitation: 'An empty result is not evidence that no skills gap exists.',
      },
      forecasts: {
        title: 'No validated forecasts yet',
        reason: 'Forecasts are withheld until sufficient traceable chronological labour-market evidence is available.',
        action: 'Review signal coverage and forecast readiness in Data Operations or Model Lab.',
        limitation: 'Forecasts are uncertain decision-support estimates, not guarantees of future demand.',
      },
      governance: {
        title: 'No governance decisions recorded',
        reason: 'A decision appears here only after an authorised person documents a review or committee outcome.',
        action: 'Review eligible recommendations and record the rationale; never create a decision merely to populate this list.',
        limitation: 'Model outputs and expert reviews do not replace final committee authority.',
      },
      reports: {
        title: 'No archived evidence reports yet',
        reason: 'Reports are generated only from eligible evidence snapshots and completed workflows.',
        action: 'Complete the relevant readiness gates before generating a report.',
        limitation: 'A report is a fixed evidence snapshot, not proof that its recommendations were adopted.',
      },
    };

    function emptyStateHtml(message) {
      const detail = typeof message === 'string' ? { title: message } : (message || {});
      return `<div class="empty empty-state-detail">
        <strong>${escapeHtml(detail.title || 'No data available')}</strong>
        ${detail.reason ? `<span><b>Why:</b> ${escapeHtml(detail.reason)}</span>` : ''}
        ${detail.action ? `<span><b>Next step:</b> ${escapeHtml(detail.action)}</span>` : ''}
        ${detail.limitation ? `<span class="empty-limitation"><b>Do not infer:</b> ${escapeHtml(detail.limitation)}</span>` : ''}
      </div>`;
    }

    function decisionEmptyState(key, override = {}) {
      return { ...(DECISION_EMPTY_STATES[key] || {}), ...override };
    }

    function renderEmpty(body, columns, message) {
      if (!body) return;
      body.innerHTML = `<tr><td colspan="${columns}">${emptyStateHtml(message)}</td></tr>`;
    }

    function countBy(items, key) {
      return items.reduce((acc, item) => {
        const value = item[key] || 'unknown';
        acc[value] = (acc[value] || 0) + 1;
        return acc;
      }, {});
    }

    function average(values) {
      const valid = values.filter((value) => Number.isFinite(value));
      return valid.length ? valid.reduce((sum, value) => sum + value, 0) / valid.length : 0;
    }

    function percent(value) {
      return `${Math.round(Number(value || 0) * 100)}%`;
    }

    function formatNumber(value) {
      return new Intl.NumberFormat().format(Number(value || 0));
    }

    function skillName(skillId, skills) {
      return (skills || []).find((item) => item.skill_id === skillId)?.name || 'Unmapped skill';
    }

    function priorityTone(value) {
      if (value === 'high') return 'bad';
      if (value === 'medium') return 'warn';
      return 'good';
    }

    function statusTone(value) {
      if (['approved', 'active', 'generated', 'native'].includes(value)) return 'good';
      if (['completed', 'cleaned', 'passed'].includes(value)) return 'good';
      if (['pending_review', 'modified_pending_review', 'fallback', 'queued', 'running', 'warning', 'retry_scheduled'].includes(value)) return 'warn';
      if (['rejected', 'failed'].includes(value)) return 'bad';
      return '';
    }

    function statusBadge(text, tone = '') {
      return `<span class="badge ${tone}">${escapeHtml(String(text || '-'))}</span>`;
    }

    function escapeHtml(value) {
      return String(value ?? '').replace(/[&<>"']/g, (char) => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;',
      }[char]));
    }

    function formatFileSize(bytes) {
      if (!bytes || bytes === 0) return '-';
      const units = ['B', 'KB', 'MB', 'GB'];
      let i = 0;
      let size = bytes;
      while (size >= 1024 && i < units.length - 1) { size /= 1024; i += 1; }
      return `${size.toFixed(1)} ${units[i]}`;
    }

    function toCsv(rows) {
      if (!rows.length) return '';
      const columns = Array.from(rows.reduce((set, row) => {
        Object.keys(row).forEach((key) => set.add(key));
        return set;
      }, new Set()));
      const escape = (value) => `"${String(value ?? '').replace(/"/g, '""')}"`;
      return [
        columns.map(escape).join(','),
        ...rows.map((row) => columns.map((column) => {
          const value = row[column];
          return escape(typeof value === 'object' && value !== null ? JSON.stringify(value) : value);
        }).join(',')),
      ].join('\n');
    }

    function download(filename, content, type) {
      const blob = new Blob([content], { type });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      link.click();
      URL.revokeObjectURL(url);
    }

export { $, showToast, showConfirm, showSpinner, hideSpinner, setupSearch, paginate, renderPagination, renderKeyValueRows, renderBars, renderEmpty, emptyStateHtml, decisionEmptyState, countBy, average, percent, formatNumber, skillName, priorityTone, statusTone, statusBadge, escapeHtml, formatFileSize, toCsv, download };
