/**
 * TypeScript interfaces matching the backend API responses.
 */

export interface HealthStatus {
  status: string;
  components: {
    api: boolean;
    database: boolean;
  };
}

export interface BoundaryEdge {
  parent: string;
  child: string;
  source: string;
  confidence: number;
}

export interface Incident {
  id: number;
  kind: 'span' | 'dt' | 'feeder' | 'sensor_only';
  status: string;
  boundary_edges: BoundaryEdge[];
  dark_pole_count: number;
  dark_pole_ids?: string[];
  centroid_lat: number;
  centroid_lon: number;
  pincode: string | null;
  dt_id: string;
  feeder_id: string;
  households_affected: number;
  confidence: number;
  confidence_breakdown?: Record<string, number>;
  topology_basis: 'surveyed' | 'inferred' | 'mixed';
  created_at: string;
  resolved_at: string | null;
}

export interface HistoryEntry {
  ts: string;
  from: string | null;
  to: string;
  actor: string;
  reason: string;
}

export interface Ticket {
  id: number;
  incident_id: number;
  status: string;
  ai_narrative: string | null;
  history: HistoryEntry[];
  created_at: string;
  updated_at: string;
  incident: Incident;
}

export interface PoleData {
  pole_id: string;
  lat: number;
  lon: number;
  dt_id: string;
  feeder_id: string;
  device_id: string | null;
  has_device: boolean;
  pincode: string | null;
  energized: boolean | null;
  classification: 'ok' | 'dark_confirmed' | 'sensor_suspect' | 'unknown';
}

export interface TransformerData {
  dt_id: string;
  feeder_id: string;
  lat: number;
  lon: number;
  capacity_kva: number;
  households_served: number;
}

export interface NetworkStats {
  total_poles: number;
  total_dts: number;
  pole_states: Record<string, number>;
  active_incidents: number;
}

export interface SimulationTarget {
  transformers: Array<{ dt_id: string; feeder_id: string; households: number }>;
  feeders: string[];
  poles: Array<{ pole_id: string; dt_id: string; device_id: string }>;
}

export interface Scenario {
  id: string;
  name: string;
  description: string;
  endpoint: string;
}
