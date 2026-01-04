// Auth Module - Token yönetimi ve API çağrıları
const Auth = {
  TOKEN_KEY: "access_token",
  REFRESH_KEY: "refresh_token",
  ROLE_KEY: "user_role",
  USER_KEY: "user_data",

  getToken() {
    return localStorage.getItem(this.TOKEN_KEY);
  },

  getRefreshToken() {
    return localStorage.getItem(this.REFRESH_KEY);
  },

  getRole() {
    return localStorage.getItem(this.ROLE_KEY);
  },

  isAdmin() {
    return this.getRole() === "admin";
  },

  setTokens(accessToken, refreshToken, role) {
    localStorage.setItem(this.TOKEN_KEY, accessToken);
    localStorage.setItem(this.REFRESH_KEY, refreshToken);
    if (role) localStorage.setItem(this.ROLE_KEY, role);
  },

  setUser(user) {
    localStorage.setItem(this.USER_KEY, JSON.stringify(user));
    if (user.role) localStorage.setItem(this.ROLE_KEY, user.role);
  },

  getUser() {
    const user = localStorage.getItem(this.USER_KEY);
    return user ? JSON.parse(user) : null;
  },

  clearAuth() {
    localStorage.removeItem(this.TOKEN_KEY);
    localStorage.removeItem(this.REFRESH_KEY);
    localStorage.removeItem(this.ROLE_KEY);
    localStorage.removeItem(this.USER_KEY);
  },

  isAuthenticated() {
    return !!this.getToken();
  },

  getAuthHeaders() {
    const token = this.getToken();
    return token
      ? { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }
      : { "Content-Type": "application/json" };
  },

  async refreshTokens() {
    const refreshToken = this.getRefreshToken();
    if (!refreshToken) return false;

    try {
      const response = await fetch("/api/auth/refresh", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });

      if (response.ok) {
        const data = await response.json();
        this.setTokens(data.access_token, data.refresh_token, data.role);
        return true;
      }
    } catch (e) {
      console.error("Token refresh failed:", e);
    }

    this.clearAuth();
    return false;
  },

  async fetchWithAuth(url, options = {}) {
    const token = this.getToken();
    if (!token) {
      window.location.href = "/login";
      return null;
    }

    const headers = {
      "Content-Type": "application/json",
      ...options.headers,
      Authorization: `Bearer ${token}`,
    };

    let response = await fetch(url, { ...options, headers });

    if (response.status === 401) {
      const refreshed = await this.refreshTokens();
      if (refreshed) {
        headers["Authorization"] = `Bearer ${this.getToken()}`;
        response = await fetch(url, { ...options, headers });
      } else {
        window.location.href = "/login";
        return null;
      }
    }

    return response;
  },

  async fetchUserInfo() {
    const response = await this.fetchWithAuth("/api/auth/me");
    if (response && response.ok) {
      const user = await response.json();
      this.setUser(user);
      return user;
    }
    return null;
  },

  logout() {
    this.clearAuth();
    window.location.href = "/login";
  },

  requireAuth() {
    if (!this.isAuthenticated()) {
      window.location.href = "/login";
      return false;
    }
    return true;
  },

  requireAdmin() {
    if (!this.isAuthenticated() || !this.isAdmin()) {
      window.location.href = "/login";
      return false;
    }
    return true;
  },
};

window.Auth = Auth;
