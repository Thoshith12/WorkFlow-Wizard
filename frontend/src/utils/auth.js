export function getToken() {
  return localStorage.getItem('access_token') || sessionStorage.getItem('access_token');
}

export function getUser() {
  return localStorage.getItem('user_display_name') || localStorage.getItem('user_id') || 'Admin';
}

export function setAuthSession(data, usernameStr = '') {
  localStorage.setItem('access_token', data.access_token);
  localStorage.setItem('user_display_name', usernameStr || data.username || 'Admin');
  localStorage.setItem('user_id', data.user_id || 'Admin');
  localStorage.setItem('token_type', data.token_type || 'bearer');
}

export function clearAuthSession() {
  localStorage.clear();
  sessionStorage.clear();
}

export function isTokenExpired(token) {
  if (!token) return true;
  try {
    const payloadBase64 = token.split('.')[1];
    if (!payloadBase64) return false;
    const decoded = JSON.parse(atob(payloadBase64.replace(/-/g, '+').replace(/_/g, '/')));
    if (decoded.exp) {
      const now = Math.floor(Date.now() / 1000);
      return decoded.exp < now;
    }
  } catch (e) {
    console.warn('Failed to parse token expiration:', e);
  }
  return false;
}

export function checkAuthenticated() {
  const token = getToken();
  if (!token) return false;
  if (isTokenExpired(token)) {
    clearAuthSession();
    return false;
  }
  return true;
}
