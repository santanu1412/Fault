/**
 * API client for the KSPDB Fault Localization System.
 */

const API_BASE = '/api';

async function apiFetch<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${url}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `API error: ${res.status}`);
  }
  return res.json();
}

export const api = {
  // Health
  health: () => apiFetch('/health'),

  // Network
  getStats: () => apiFetch('/network/stats'),
  getPoles: (dtId?: string) =>
    apiFetch(`/poles${dtId ? `?dt_id=${dtId}` : '?limit=3000'}`),
  getTransformers: () => apiFetch('/transformers'),

  // Incidents
  getIncidents: (status?: string) =>
    apiFetch(`/incidents${status ? `?status=${status}` : ''}`),
  getIncident: (id: number) => apiFetch(`/incidents/${id}`),

  // Tickets
  getTickets: (status?: string) =>
    apiFetch(`/tickets${status ? `?status=${status}` : ''}`),
  getTicket: (id: number) => apiFetch(`/tickets/${id}`),
  transitionTicket: (id: number, targetStatus: string, reason?: string) =>
    apiFetch(`/tickets/${id}/transition`, {
      method: 'PATCH',
      body: JSON.stringify({ target_status: targetStatus, reason }),
    }),
  askQuestion: (id: number, question: string) =>
    apiFetch(`/tickets/${id}/ask`, {
      method: 'POST',
      body: JSON.stringify({ question }),
    }),

  // Simulator
  getTargets: () => apiFetch('/simulate/targets'),
  getScenarios: () => apiFetch('/simulate/scenarios'),
  injectSpanFault: (dtId: string, startIndex: number = 3) =>
    apiFetch('/simulate/fault/span', {
      method: 'POST',
      body: JSON.stringify({ dt_id: dtId, start_pole_index: startIndex }),
    }),
  injectDtFault: (dtId: string) =>
    apiFetch('/simulate/fault/dt', {
      method: 'POST',
      body: JSON.stringify({ dt_id: dtId }),
    }),
  injectFeederFault: (feederId: string) =>
    apiFetch('/simulate/fault/feeder', {
      method: 'POST',
      body: JSON.stringify({ feeder_id: feederId }),
    }),
  injectSensorDeath: (poleId: string) =>
    apiFetch('/simulate/sensor-death', {
      method: 'POST',
      body: JSON.stringify({ pole_id: poleId }),
    }),
  repairIncident: (incidentId: number) =>
    apiFetch('/simulate/repair', {
      method: 'POST',
      body: JSON.stringify({ incident_id: incidentId }),
    }),
  heartbeatBurst: (count: number = 500) =>
    apiFetch('/simulate/heartbeat-burst', {
      method: 'POST',
      body: JSON.stringify({ count }),
    }),
};
