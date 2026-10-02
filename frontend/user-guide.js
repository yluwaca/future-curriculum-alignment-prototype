import { auth, parseJwt } from './auth.js';

if (auth.isAuthenticated()) {
  const payload = parseJwt(auth.getToken());
  const sessionLabel = document.getElementById('guideSessionLabel');
  const requestAccess = document.getElementById('guideRequestAccess');
  const accountLink = document.getElementById('guideAccountLink');

  sessionLabel.textContent = `Signed in as ${payload?.sub || payload?.email || 'user'}`;
  sessionLabel.classList.remove('hidden');
  requestAccess.classList.add('hidden');
  accountLink.textContent = 'Return to portal';
  accountLink.href = 'dashboard.html';
}
