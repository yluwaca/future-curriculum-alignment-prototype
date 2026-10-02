import { auth, requireAuth, parseJwt } from './auth.js';
import { CONFIG, API_ENDPOINTS } from './config.js';

requireAuth();

const $ = (id) => document.getElementById(id);
const userName = $('userName');
const userEmail = $('userEmail');
const statusBox = $('statusBox');
const userTableBody = $('userTableBody');
const pagination = $('pagination');
const searchInput = $('searchInput');

let currentUser = null;
let currentTab = 'pending';
let currentPage = 1;
let allRoles = [];
const PAGE_SIZE = 15;

// ---- Init ----

async function init() {
  const token = auth.getToken();
  const payload = parseJwt(token);
  if (payload && payload.sub) {
    userName.textContent = payload.sub;
  }

  try {
    const me = await auth.fetch(API_ENDPOINTS.AUTH.ME);
    if (me.ok) {
      const user = await me.json();
      currentUser = user;
      userName.textContent = user.identity_id;
      userEmail.textContent = user.email || '';
      if (!user.is_admin && !(user.roles || []).some(r => r.toLowerCase() === 'admin' || r.toLowerCase() === 'administrator')) {
        window.location.replace('dashboard.html?view=executive&access_denied=user_administration');
        return;
      }
    } else {
      window.location.replace('index.html');
      return;
    }
  } catch (e) {
    window.location.replace('index.html');
    return;
  }

  await loadRoles();
  await loadUsers();
  wireEvents();
}

// ---- Load roles ----

async function loadRoles() {
  try {
    const res = await auth.fetch(API_ENDPOINTS.ADMIN.ROLES);
    if (res.ok) {
      const data = await res.json();
      allRoles = data.roles || [];
      const roleSelect = $('approveRole');
      roleSelect.innerHTML = allRoles.map((role) =>
        `<option value="${esc(role.role_id)}">${esc(role.role_name)} — ${esc(role.description || 'No description')}</option>`
      ).join('');
      [...roleSelect.options].forEach((option, index) => {
        const role = allRoles[index];
        option.textContent = `${role.role_name}: ${role.description || 'No description'}`;
      });
      roleSelect.disabled = allRoles.length === 0;
      $('approveConfirmBtn').disabled = allRoles.length === 0;
      if (!allRoles.length) {
        showStatus('No active roles are available. Apply the RBAC migration before approving users.', 'error');
      }
      return;
    }
    throw new Error('Role catalogue request failed');
  } catch (e) {
    allRoles = [];
    $('approveRole').innerHTML = '<option value="">Roles unavailable</option>';
    $('approveRole').disabled = true;
    $('approveConfirmBtn').disabled = true;
    showStatus('Unable to load the role catalogue. User approval has been disabled for safety.', 'error');
  }
}

// ---- Load users ----

async function loadUsers() {
  showStatus('Loading users...', 'info');

  const params = new URLSearchParams();
  if (currentTab !== 'all') {
    params.set('approval_status', currentTab);
  }
  params.set('page', currentPage);
  params.set('page_size', PAGE_SIZE);

  const search = searchInput.value.trim();
  if (search) {
    params.set('search', search);
  }

  try {
    const res = await auth.fetch(`${API_ENDPOINTS.ADMIN.USERS}?${params}`);
    if (!res.ok) throw new Error('Failed to load users');
    const data = await res.json();

    renderUsers(data.users || []);
    renderPagination(data.total || 0, data.page || 1, data.pages || 1);
    updateCounts();
    hideStatus();
  } catch (e) {
    showStatus('Error loading users: ' + e.message, 'error');
  }
}

// ---- Render users ----

function renderUsers(users) {
  if (!users.length) {
    userTableBody.innerHTML = '<tr><td colspan="6" class="empty">No users found</td></tr>';
    return;
  }

  userTableBody.innerHTML = users.map(u => {
    const statusBadge = getApprovalBadge(u.approval_status, u.is_active);
    const roles = (u.roles || []).map(r => `<span class="badge info">${esc(r)}</span>`).join(' ');
    const date = u.created_at ? new Date(u.created_at).toLocaleDateString() : '-';
    const actions = getActions(u);

    return `<tr>
      <td><strong>${esc(u.identity_id)}</strong></td>
      <td>${esc(u.email || '-')}</td>
      <td>${statusBadge}</td>
      <td>${roles || '<span style="color:var(--text-muted)">none</span>'}</td>
      <td>${date}</td>
      <td>${actions}</td>
    </tr>`;
  }).join('');
}

function getApprovalBadge(status, isActive) {
  if (!isActive) return '<span class="badge bad">Locked</span>';
  if (status === 'approved') return '<span class="badge good">Approved</span>';
  if (status === 'rejected') return '<span class="badge bad">Rejected</span>';
  return '<span class="badge warn">Pending</span>';
}

function getActions(user) {
  const parts = [];
  if (user.approval_status === 'pending') {
    parts.push(`<button class="btn sm primary" onclick="window._approveUser('${esc(user.identity_id)}')">Approve</button>`);
    parts.push(`<button class="btn sm danger" onclick="window._rejectUser('${esc(user.identity_id)}')">Reject</button>`);
  }
  if (!user.is_active) {
    parts.push(`<button class="btn sm warn" onclick="window._unlockUser('${esc(user.identity_id)}')">Unlock</button>`);
  }
  parts.push(`<button class="btn sm" onclick="window._manageRoles('${esc(user.identity_id)}')">Roles</button>`);
  parts.push(`<button class="btn sm warn" onclick="window._resetPassword('${esc(user.identity_id)}')">Reset Password</button>`);
  return parts.join(' ');
}

// ---- Pagination ----

function renderPagination(total, page, pages) {
  if (pages <= 1) {
    pagination.innerHTML = '';
    return;
  }

  let html = '';
  html += `<button ${page <= 1 ? 'disabled' : ''} onclick="window._goPage(${page - 1})">&laquo;</button>`;
  for (let i = Math.max(1, page - 2); i <= Math.min(pages, page + 2); i++) {
    html += `<button class="${i === page ? 'active' : ''}" onclick="window._goPage(${i})">${i}</button>`;
  }
  html += `<button ${page >= pages ? 'disabled' : ''} onclick="window._goPage(${page + 1})">&raquo;</button>`;
  html += `<span>Page ${page} of ${pages} (${total} users)</span>`;
  pagination.innerHTML = html;
}

// ---- Approve ----

window._approveUser = function(userId) {
  if (!allRoles.length) {
    showStatus('Cannot approve a user until the role catalogue is available.', 'error');
    return;
  }
  $('approveUserInfo').textContent = `Approve user "${userId}"?`;
  const viewer = allRoles.find((role) => role.role_id === 'viewer');
  $('approveRole').value = viewer ? viewer.role_id : allRoles[0].role_id;
  $('approveNotes').value = '';
  $('approveModal').classList.remove('hidden');
  $('approveModal').dataset.userId = userId;
};

// ---- Reject ----

window._rejectUser = function(userId) {
  $('rejectUserInfo').textContent = `Reject user "${userId}"?`;
  $('rejectReason').value = '';
  $('rejectModal').classList.remove('hidden');
  $('rejectModal').dataset.userId = userId;
};

// ---- Unlock ----

window._unlockUser = async function(userId) {
  if (!confirm(`Unlock user "${userId}"? This resets their failed login attempts and reactivates the account.`)) return;
  try {
    const res = await auth.fetch(API_ENDPOINTS.ADMIN.UPDATE_STATUS(userId), {
      method: 'PUT',
      body: JSON.stringify({ is_active: true }),
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Unlock failed');
    }
    showStatus(`User "${userId}" unlocked.`, 'success');
    await loadUsers();
  } catch (e) {
    showStatus('Error: ' + e.message, 'error');
  }
};

// ---- Manage Roles ----

window._manageRoles = async function(userId) {
  $('rolesUserInfo').textContent = `Manage roles for "${userId}"`;

  let userRoles = [];
  try {
    const res = await auth.fetch(API_ENDPOINTS.ADMIN.USER_DETAIL(userId));
    if (res.ok) {
      const data = await res.json();
      userRoles = data.roles || [];
    }
  } catch (e) {
    // ignore
  }

  const checkboxes = allRoles.map(r => {
    const checked = userRoles.includes(r.role_name) ? 'checked' : '';
    return `<div class="role-check">
      <input type="checkbox" id="role_${r.role_id}" value="${esc(r.role_id)}" ${checked}>
      <label for="role_${r.role_id}">
        <span class="role-label">${esc(r.role_name)}</span>
        <span class="role-desc">${esc(r.description || '')}</span>
      </label>
    </div>`;
  }).join('');

  $('rolesCheckboxes').innerHTML = checkboxes || '<p style="color:var(--text-muted)">No roles available</p>';
  $('rolesModal').classList.remove('hidden');
  $('rolesModal').dataset.userId = userId;
};

// ---- Reset Password ----

window._resetPassword = function(userId) {
  $('resetPasswordInfo').textContent = `Set a new password for "${userId}"?`;
  $('resetNewPassword').value = '';
  $('resetPasswordModal').classList.remove('hidden');
  $('resetPasswordModal').dataset.userId = userId;
};

// ---- Wire events ----

function wireEvents() {
  $('refreshBtn').addEventListener('click', loadUsers);

  $('logoutBtn').addEventListener('click', () => {
    auth.clearToken();
    window.location.href = 'index.html';
  });

  document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      currentTab = tab.dataset.tab;
      currentPage = 1;
      loadUsers();
    });
  });

  let searchTimeout;
  searchInput.addEventListener('input', () => {
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(() => {
      currentPage = 1;
      loadUsers();
    }, 300);
  });

  // Approve modal
  $('approveCancelBtn').addEventListener('click', () => {
    $('approveModal').classList.add('hidden');
  });

  $('approveConfirmBtn').addEventListener('click', async () => {
    const userId = $('approveModal').dataset.userId;
    const role = $('approveRole').value;
    const notes = $('approveNotes').value.trim();

    if (!role || !allRoles.some((item) => item.role_id === role)) {
      showStatus('Select an available role before approving the user.', 'error');
      return;
    }

    $('approveConfirmBtn').disabled = true;
    try {
      const res = await auth.fetch(API_ENDPOINTS.ADMIN.APPROVE_USER(userId), {
        method: 'PUT',
        body: JSON.stringify({ default_role: role, notes: notes || null }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Approval failed');
      }
      $('approveModal').classList.add('hidden');
      showStatus(`User "${userId}" approved with role "${role}".`, 'success');
      document.querySelector('.tab[data-tab="approved"]').click();
    } catch (e) {
      showStatus('Error: ' + e.message, 'error');
    } finally {
      $('approveConfirmBtn').disabled = false;
    }
  });

  // Reject modal
  $('rejectCancelBtn').addEventListener('click', () => {
    $('rejectModal').classList.add('hidden');
  });

  $('rejectConfirmBtn').addEventListener('click', async () => {
    const userId = $('rejectModal').dataset.userId;
    const reason = $('rejectReason').value.trim();

    if (!reason) {
      alert('Please provide a rejection reason.');
      return;
    }

    $('rejectConfirmBtn').disabled = true;
    try {
      const res = await auth.fetch(API_ENDPOINTS.ADMIN.REJECT_USER(userId), {
        method: 'PUT',
        body: JSON.stringify({ reason }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Rejection failed');
      }
      $('rejectModal').classList.add('hidden');
      showStatus(`User "${userId}" rejected.`, 'success');
      document.querySelector('.tab[data-tab="rejected"]').click();
    } catch (e) {
      showStatus('Error: ' + e.message, 'error');
    } finally {
      $('rejectConfirmBtn').disabled = false;
    }
  });

  // Roles modal
  $('rolesCancelBtn').addEventListener('click', () => {
    $('rolesModal').classList.add('hidden');
  });

  $('rolesConfirmBtn').addEventListener('click', async () => {
    const userId = $('rolesModal').dataset.userId;
    const selected = [];
    allRoles.forEach(r => {
      const cb = $(`role_${r.role_id}`);
      if (cb && cb.checked) selected.push(r.role_id);
    });

    if (!selected.length) {
      showStatus('Select at least one role. Approved users cannot be saved without access.', 'error');
      return;
    }

    $('rolesConfirmBtn').disabled = true;
    try {
      const res = await auth.fetch(API_ENDPOINTS.ADMIN.UPDATE_ROLES(userId), {
        method: 'PUT',
        body: JSON.stringify({ roles: selected }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Role update failed');
      }
      $('rolesModal').classList.add('hidden');
      showStatus(`Roles updated for "${userId}".`, 'success');
      await loadUsers();
    } catch (e) {
      showStatus('Error: ' + e.message, 'error');
    } finally {
      $('rolesConfirmBtn').disabled = false;
    }
  });

  // Close modals on overlay click
  [$('approveModal'), $('rejectModal'), $('rolesModal'), $('resetPasswordModal')].forEach(modal => {
    modal.addEventListener('click', (e) => {
      if (e.target === modal) modal.classList.add('hidden');
    });
  });

  // Reset Password modal
  $('resetPasswordCancelBtn').addEventListener('click', () => {
    $('resetPasswordModal').classList.add('hidden');
  });

  $('resetPasswordConfirmBtn').addEventListener('click', async () => {
    const userId = $('resetPasswordModal').dataset.userId;
    const newPwd = $('resetNewPassword').value;

    if (!newPwd || newPwd.length < 8) {
      alert('Password must be at least 8 characters.');
      return;
    }

    $('resetPasswordConfirmBtn').disabled = true;
    try {
      const res = await auth.fetch(API_ENDPOINTS.ADMIN.RESET_PASSWORD(userId), {
        method: 'PUT',
        body: JSON.stringify({ new_password: newPwd }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Password reset failed');
      }
      $('resetPasswordModal').classList.add('hidden');
      showStatus(`Password reset for "${userId}".`, 'success');
    } catch (e) {
      showStatus('Error: ' + e.message, 'error');
    } finally {
      $('resetPasswordConfirmBtn').disabled = false;
    }
  });
}

window._goPage = function(page) {
  currentPage = page;
  loadUsers();
};

// ---- Helpers ----

function updateCounts() {
  const base = API_ENDPOINTS.ADMIN.USERS;
  ['pending', 'approved', 'rejected'].forEach(status => {
    auth.fetch(`${base}?page_size=1&approval_status=${status}`)
      .then(r => r.json())
      .then(data => {
        const el = $(`${status}Count`);
        if (el) el.textContent = data.total || 0;
      })
      .catch(() => {});
  });
}

function showStatus(msg, type) {
  statusBox.textContent = msg;
  statusBox.className = `status show ${type || ''}`;
}

function hideStatus() {
  statusBox.className = 'status';
}

function esc(str) {
  if (!str) return '';
  return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

init();
