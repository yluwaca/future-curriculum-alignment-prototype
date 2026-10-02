    import { auth, parseJwt } from './auth.js';
    import { API_ENDPOINTS, CONFIG } from './config.js';

    const loginForm = document.getElementById('loginForm');
    const loginBtn = document.getElementById('loginBtn');
    const loginBtnText = document.getElementById('loginBtnText');
    const loginSpinner = document.getElementById('loginSpinner');
    const alertContainer = document.getElementById('alertContainer');
    const sessionExpiredMsg = document.getElementById('sessionExpiredMsg');
    const registerLink = document.getElementById('registerLink');
    const usernameInput = document.getElementById('username');
    const passwordInput = document.getElementById('password');
    const togglePassword = document.getElementById('togglePassword');
    const capsLockMessage = document.getElementById('capsLockMessage');

    togglePassword.addEventListener('click', () => {
      const reveal = passwordInput.type === 'password';
      passwordInput.type = reveal ? 'text' : 'password';
      togglePassword.textContent = reveal ? 'Hide' : 'Show';
      togglePassword.setAttribute('aria-pressed', String(reveal));
      passwordInput.focus();
    });

    passwordInput.addEventListener('keyup', (event) => {
      capsLockMessage.classList.toggle('hidden', !event.getModifierState('CapsLock'));
    });

    const urlParams = new URLSearchParams(window.location.search);
    if (urlParams.get('session_expired') === '1') {
      sessionExpiredMsg.classList.remove('hidden');
      showAlert('Your session has expired. Please sign in again.', 'info');
    }

    const redirectUrl = urlParams.get('redirect');

    if (urlParams.get('registered') === '1') {
      showAlert('Your access request was submitted. Please wait for administrator approval before signing in.', 'info');
    }

    if (auth.isAuthenticated()) {
      const token = auth.getToken();
      const payload = parseJwt(token);
      if (payload && payload.exp && Date.now() >= (payload.exp * 1000 - CONFIG.TOKEN_EXPIRY_BUFFER_MS)) {
        auth.clearToken();
      } else {
        window.location.href = redirectUrl || 'dashboard.html';
      }
    }

    if (!CONFIG.ENABLE_REGISTRATION) {
      registerLink.style.display = 'none';
    }

    loginForm.addEventListener('submit', async function(e) {
      e.preventDefault();

      const username = document.getElementById('username').value.trim();
      const password = document.getElementById('password').value.trim();

      if (!username || !password) {
        showAlert('Please enter both username and password.', 'error');
        (!username ? usernameInput : passwordInput).focus();
        return;
      }

      setLoading(true);
      clearAlerts();

      try {
        const response = await auth.fetch(API_ENDPOINTS.LOGIN, {
          method: 'POST',
          body: JSON.stringify({ identifier: username, password })
        });

        const data = await response.json();

        if (!response.ok) {
          let errorMsg = 'Login failed';
          if (Array.isArray(data.detail)) {
            errorMsg = data.detail.map(err => err.msg).join(', ');
          } else if (typeof data.detail === 'string') {
            errorMsg = data.detail;
          } else if (data.message) {
            errorMsg = data.message;
          }
          if (response.status === 403 && errorMsg.includes('pending admin approval')) {
            errorMsg = 'Your account is pending admin approval. Please wait for an administrator to approve your registration before logging in.';
          }
          throw new Error(errorMsg);
        }

        if (!data.access_token) {
          throw new Error('Server did not return access token');
        }

        auth.setToken(data.access_token);
        showAlert('Login successful! Redirecting...', 'success');

        setTimeout(() => {
          window.location.href = redirectUrl || 'dashboard.html';
        }, 800);
      } catch (error) {
        console.error('Login error:', error);
        const msg = error.message || '';
        if (msg.includes('Failed to fetch') || msg.includes('NetworkError') || msg.includes('Network request failed') || error.name === 'TypeError') {
          showAlert('Unable to reach the server. Please ensure the backend is running and try again.', 'error');
        } else {
          showAlert(msg || 'An unexpected error occurred. Please try again.', 'error');
        }
      } finally {
        setLoading(false);
      }
    });

    function setLoading(loading) {
      loginBtn.disabled = loading;
      loginBtnText.classList.toggle('hidden', loading);
      loginSpinner.classList.toggle('hidden', !loading);
    }

    function showAlert(message, type = 'error') {
      const icons = { error: '!', success: '\u2713', info: 'i' };
      const alert = document.createElement('div');
      alert.className = `alert alert-${type}`;
      const icon = document.createElement('span');
      icon.className = 'alert-icon';
      icon.setAttribute('aria-hidden', 'true');
      icon.textContent = icons[type] || '';
      alert.append(icon, document.createTextNode(message));
      alertContainer.appendChild(alert);
      if (type !== 'error') {
        setTimeout(() => { alert.remove(); }, 5000);
      }
    }

    function clearAlerts() {
      alertContainer.innerHTML = '';
    }
