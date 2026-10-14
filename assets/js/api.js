import { API_ROOT } from './config.js';

export class ApiClient {
  async request(path, options = {}) {
    const response = await fetch(API_ROOT + path, {
      ...options,
      credentials: 'same-origin'
    });

    const data = await response.json();

    if (!response.ok) {
      const error = new Error(
        typeof data.detail === 'string'
          ? data.detail
          : `HTTP ${response.status}`
      );
      error.status = response.status;
      throw error;
    }

    return data;
  }

  health() {
    return this.request('/api/health');
  }

  session() {
    return this.request('/api/session');
  }

  logout() {
    return this.request('/api/logout', { method: 'POST' });
  }

  documents() {
    return this.request('/api/documents');
  }

  login(key) {
    return this.request('/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key })
    });
  }

  ask(question, useSearch) {
    return this.request('/api/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        question,
        use_search: useSearch
      })
    });
  }

  sync(folderId) {
    return this.request('/api/sync', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ folder_id: folderId })
    });
  }
}
