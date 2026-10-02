// auth.js - Reusable authentication utilities
// Usage: import { auth, isAuthenticated, requireAuth } from './auth.js';

import { API_ENDPOINTS, CONFIG } from './config.js';

export const auth = {
  /**
   * Get stored access token
   * @returns {string|null}
   */
  getToken() {
    return localStorage.getItem(CONFIG.TOKEN_KEY);
  },

  /**
   * Store access token
   * @param {string} token 
   */
  setToken(token) {
    localStorage.setItem(CONFIG.TOKEN_KEY, token);
  },

  /**
   * Clear stored token
   */
  clearToken() {
    localStorage.removeItem(CONFIG.TOKEN_KEY);
  },

  /**
   * Check if user is authenticated
   * @returns {boolean}
   */
  isAuthenticated() {
    return !!this.getToken();
  },

  /**
   * Make authenticated fetch request
   * @param {string} url 
   * @param {RequestInit} options 
   * @returns {Promise<Response>}
   */
  async fetch(url, options = {}) {
    const token = this.getToken();
    const headers = {
      'Content-Type': 'application/json',
      ...(options.headers || {})
    };

    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), CONFIG.DEFAULT_TIMEOUT_MS);

    try {
      const response = await fetch(url, {
        ...options,
        headers,
        signal: controller.signal
      });
      clearTimeout(timeoutId);
      return response;
    } catch (error) {
      clearTimeout(timeoutId);
      if (error.name === 'AbortError') {
        throw new Error('Request timeout - please check your connection');
      }
      throw error;
    }
  },

  /**
   * Handle 401 responses - clear token and redirect
   */
  handleUnauthorized() {
    this.clearToken();
    if (window.location.pathname !== '/index.html' && window.location.pathname !== '/') {
      window.location.href = 'index.html?session_expired=1';
    }
  }
};

/**
 * Redirect to login if not authenticated
 * @param {string} redirectUrl - Optional URL to redirect back to after login
 */
export function requireAuth(redirectUrl = null) {
  if (!auth.isAuthenticated()) {
    const target = redirectUrl || window.location.pathname + window.location.search;
    window.location.href = `index.html?redirect=${encodeURIComponent(target)}`;
  }
}

/**
 * Parse JWT token payload (without verification - for UI display only)
 * @param {string} token 
 * @returns {object|null}
 */
export function parseJwt(token) {
  try {
    const base64Url = token.split('.')[1];
    const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/');
    const jsonPayload = decodeURIComponent(
      atob(base64).split('').map(c => 
        '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2)
      ).join('')
    );
    return JSON.parse(jsonPayload);
  } catch {
    return null;
  }
}

export default auth;