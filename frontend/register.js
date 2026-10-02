    import { auth } from './auth.js';
    import { API_ENDPOINTS, CONFIG } from './config.js';

    if (!CONFIG.ENABLE_REGISTRATION) {
      document.body.innerHTML = `
        <div style="font-family:var(--font);text-align:center;padding:40px;">
          <h2 style="margin-bottom:8px;">Registration Disabled</h2>
          <p style="color:var(--text-secondary);margin-bottom:16px;">New account creation is currently not available.</p>
          <a href="index.html" style="color:var(--accent);font-weight:600;text-decoration:none;">Return to sign in</a>
        </div>
      `;
    }

    const registerForm = document.getElementById('registerForm');
    const registerBtn = document.getElementById('registerBtn');
    const registerBtnText = document.getElementById('registerBtnText');
    const registerSpinner = document.getElementById('registerSpinner');
    const alertContainer = document.getElementById('alertContainer');
    const passwordInput = document.getElementById('password');
    const confirmPasswordInput = document.getElementById('confirmPassword');
    const passwordStrength = document.getElementById('passwordStrength');
    const strengthText = document.getElementById('strengthText');

    document.querySelectorAll('[data-password-target]').forEach((button) => {
      button.addEventListener('click', () => {
        const input = document.getElementById(button.dataset.passwordTarget);
        const reveal = input.type === 'password';
        input.type = reveal ? 'text' : 'password';
        button.textContent = reveal ? 'Hide' : 'Show';
        button.setAttribute('aria-pressed', String(reveal));
        input.focus();
      });
    });

    passwordInput.addEventListener('input', function() {
      const pwd = this.value;
      let score = 0;
      if (pwd.length >= 8) score++;
      if (pwd.match(/[a-z]+/)) score++;
      if (pwd.match(/[A-Z]+/)) score++;
      if (pwd.match(/[0-9]+/)) score++;
      if (pwd.match(/[^a-zA-Z0-9]+/)) score++;
      passwordStrength.className = 'password-strength';
      if (!pwd) {
        strengthText.textContent = '';
      } else if (score <= 2) {
        passwordStrength.classList.add('weak');
        strengthText.textContent = 'Password strength: weak';
      } else if (score <= 4) {
        passwordStrength.classList.add('medium');
        strengthText.textContent = 'Password strength: reasonable';
      } else {
        passwordStrength.classList.add('strong');
        strengthText.textContent = 'Password strength: strong';
      }
    });

    confirmPasswordInput.addEventListener('input', function() {
      if (this.value && this.value !== passwordInput.value) {
        this.setCustomValidity('Passwords do not match');
      } else {
        this.setCustomValidity('');
      }
    });

    registerForm.addEventListener('submit', async function(e) {
      e.preventDefault();

      const username = document.getElementById('username').value.trim();
      const email = document.getElementById('email').value.trim();
      const password = passwordInput.value;
      const confirmPassword = confirmPasswordInput.value;

      if (password !== confirmPassword) {
        showAlert('Passwords do not match.', 'error');
        confirmPasswordInput.focus();
        return;
      }

      if (password.length < 8) {
        showAlert('Password must be at least 8 characters.', 'error');
        passwordInput.focus();
        return;
      }

      setLoading(true);
      clearAlerts();

      try {
        const response = await fetch(API_ENDPOINTS.REGISTER, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username, email, password })
        });

        const data = await response.json();

        if (!response.ok) {
          let errorMsg = 'Registration failed';
          if (Array.isArray(data.detail)) {
            errorMsg = data.detail.map(err => err.msg).join(', ');
          } else if (typeof data.detail === 'string') {
            errorMsg = data.detail;
          } else if (data.message) {
            errorMsg = data.message;
          }
          throw new Error(errorMsg);
        }

        showAlert('Access request submitted. An administrator must approve it before you can sign in.', 'success');
        registerForm.querySelectorAll('input, button').forEach(el => el.disabled = true);

        setTimeout(() => {
          window.location.href = 'index.html?registered=1';
        }, 2000);
      } catch (error) {
        console.error('Registration error:', error);
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
      registerBtn.disabled = loading;
      registerBtnText.classList.toggle('hidden', loading);
      registerSpinner.classList.toggle('hidden', !loading);
      registerForm.querySelectorAll('input').forEach(input => input.disabled = loading);
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
      if (type === 'success') {
        setTimeout(() => { alert.remove(); }, 5000);
      }
    }

    function clearAlerts() {
      alertContainer.innerHTML = '';
    }

    const urlParams = new URLSearchParams(window.location.search);
    if (urlParams.get('registered') === '1') {
      showAlert('Account created. Please sign in with your credentials.', 'info');
    }
