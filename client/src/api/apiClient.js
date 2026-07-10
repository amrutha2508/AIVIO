// src/api/apiClient.js

const API_BASE_URL = "http://localhost:8000";

console.log("API_BASE_URL:", API_BASE_URL);

export const apiClient = {
  async get(endpoint) {
    const response = await fetch(`${API_BASE_URL}${endpoint}`);

    if (!response.ok) {
      throw new Error(`API Error: ${response.status}`);
    }

    return response.json();
  },

  async post(endpoint, data) {
    const response = await fetch(`${API_BASE_URL}${endpoint}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(data),
    });

    if (!response.ok) {
      const error = await response.text();
      throw new Error(error || `API Error: ${response.status}`);
    }

    return response.json();
  },

  async put(endpoint, data) {
    const response = await fetch(`${API_BASE_URL}${endpoint}`, {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(data),
    });

    if (!response.ok) {
      const error = await response.text();
      throw new Error(error || `API Error: ${response.status}`);
    }

    return response.json();
  },

  async delete(endpoint) {
    const response = await fetch(`${API_BASE_URL}${endpoint}`, {
      method: "DELETE",
    });

    if (!response.ok) {
      const error = await response.text();
      throw new Error(error || `API Error: ${response.status}`);
    }

    return response.json();
  },
};