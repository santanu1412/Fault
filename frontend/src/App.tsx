/**
 * KSPDB Fault Monitor — Main Application
 * 
 * Operator console with map, incident list, ticket detail, and simulator.
 * Polls backend every 3 seconds for data, and connects via SSE for instant alerts.
 */

import { useState, useCallback, useEffect } from 'react';
import { usePolling } from './hooks/usePolling';
import { useSSE } from './hooks/useSSE';
import { api } from './api/client';
import { Ticket, PoleData, TransformerData, NetworkStats, HealthStatus } from './types';
import IncidentList from './components/IncidentList/IncidentList';
import TicketDetail from './components/TicketDetail/TicketDetail';
import SimulatorPanel from './components/Simulator/SimulatorPanel';
import MapView from './components/Map/MapView';

const POLL_INTERVAL = 3000;

function App() {
  const [selectedTicket, setSelectedTicket] = useState<Ticket | null>(null);
  const [showSimulator, setShowSimulator] = useState(false);
  const [pollKey, setPollKey] = useState(0);
  const [alertBanner, setAlertBanner] = useState<string | null>(null);

  // Force refetch by incrementing the key
  const triggerRefetch = useCallback(() => {
    setPollKey(k => k + 1);
  }, []);

  // SSE Stream integration for sub-second notifications
  const { isConnected: isSseConnected, lastEvent } = useSSE('/api/events/stream');

  useEffect(() => {
    if (!lastEvent) return;

    // Trigger instant UI refresh when an SSE event arrives
    triggerRefetch();

    if (lastEvent.event === 'override_executed') {
      const msg = lastEvent.data.message || `Supervisor override executed for Ticket #${lastEvent.data.ticket_id}`;
      setAlertBanner(`🔓 ${msg}`);
    } else if (lastEvent.event === 'fault_detected') {
      const msg = `⚡ Fault detected on DT ${lastEvent.data.dt_id || ''} (~${lastEvent.data.households || 0} homes affected)`;
      setAlertBanner(msg);
    } else if (lastEvent.event === 'ticket_updated') {
      setAlertBanner(`📋 Ticket #${lastEvent.data.ticket_id} updated to '${lastEvent.data.status}'`);
    }

    // Auto-dismiss alert banner after 6 seconds
    const timer = setTimeout(() => setAlertBanner(null), 6000);
    return () => clearTimeout(timer);
  }, [lastEvent, triggerRefetch]);

  // Polling hooks for data
  const ticketsFetcher = useCallback(async () => {
    return api.getTickets() as Promise<Ticket[]>;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pollKey]);

  const polesFetcher = useCallback(async () => {
    return api.getPoles() as Promise<PoleData[]>;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pollKey]);

  const dtsFetcher = useCallback(async () => {
    return api.getTransformers() as Promise<TransformerData[]>;
  }, []);

  const statsFetcher = useCallback(async () => {
    return api.getStats() as Promise<NetworkStats>;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pollKey]);

  const healthFetcher = useCallback(async () => {
    return api.health() as Promise<HealthStatus>;
  }, []);

  const { data: tickets } = usePolling(ticketsFetcher, POLL_INTERVAL);
  const { data: poles } = usePolling(polesFetcher, POLL_INTERVAL);
  const { data: transformers } = usePolling(dtsFetcher, 30000); // DTs rarely change
  const { data: stats } = usePolling(statsFetcher, POLL_INTERVAL);
  const { data: health } = usePolling(healthFetcher, 5000);

  const handleSelectTicket = (ticket: Ticket) => {
    setSelectedTicket(ticket);
  };

  const activeCount = tickets?.filter(t =>
    ['detected', 'acknowledged', 'crew_assigned'].includes(t.status)
  ).length || 0;

  return (
    <div className="h-full flex flex-col">
      {/* Real-time alert banner */}
      {alertBanner && (
        <div className="bg-accent-primary text-white text-xs px-4 py-1.5 flex items-center justify-between font-medium z-30 animate-pulse-slow">
          <span>{alertBanner}</span>
          <button onClick={() => setAlertBanner(null)} className="text-gray-300 hover:text-white text-sm font-bold">×</button>
        </div>
      )}

      {/* Header */}
      <header className="bg-surface-800 border-b border-surface-500/30 px-4 py-2.5 flex items-center justify-between shrink-0 z-20">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <svg className="w-6 h-6 text-accent-primary" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
            <h1 className="text-base font-semibold text-white tracking-tight">KSPDB Fault Monitor</h1>
          </div>
          <span className="text-[10px] text-gray-600 font-mono">v1.0</span>
        </div>

        {/* Stats bar */}
        <div className="flex items-center gap-4 text-xs">
          {stats && (
            <>
              <div className="flex items-center gap-1.5">
                <span className="text-gray-500">Poles:</span>
                <span className="text-gray-300 font-mono">{stats.total_poles?.toLocaleString()}</span>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="text-gray-500">DTs:</span>
                <span className="text-gray-300 font-mono">{stats.total_dts}</span>
              </div>
              {stats.pole_states?.dark_confirmed > 0 && (
                <div className="flex items-center gap-1.5">
                  <span className="text-grid-dark">🔴</span>
                  <span className="text-grid-dark font-mono">{stats.pole_states.dark_confirmed} dark</span>
                </div>
              )}
            </>
          )}

          {activeCount > 0 && (
            <div className="flex items-center gap-1.5 bg-accent-danger/20 px-2 py-0.5 rounded-full fault-pulse">
              <span className="text-accent-danger font-medium">{activeCount} ACTIVE</span>
            </div>
          )}

          <div className="flex items-center gap-1.5">
            <div className={`w-2 h-2 rounded-full ${isSseConnected ? 'bg-grid-live animate-pulse-slow' : health?.status === 'healthy' ? 'bg-accent-warning' : 'bg-grid-dark'
              }`} />
            <span className="text-gray-500 font-mono">
              {isSseConnected ? 'SSE LIVE' : health?.status === 'healthy' ? 'POLLING' : 'OFFLINE'}
            </span>
          </div>

          <button
            id="toggle-simulator"
            onClick={() => setShowSimulator(!showSimulator)}
            className={`btn-ghost text-xs py-1 px-2 ${showSimulator ? 'bg-surface-600' : ''}`}
          >
            🧪 Simulator
          </button>
        </div>
      </header>

      {/* Main layout */}
      <div className="flex-1 flex min-h-0">
        {/* Left panel — Incident list */}
        <div className="w-72 shrink-0 border-r border-surface-500/30 bg-surface-800">
          <IncidentList
            tickets={tickets || []}
            selectedId={selectedTicket?.id || null}
            onSelect={handleSelectTicket}
          />
        </div>

        {/* Center — Map */}
        <div className="flex-1 relative">
          <MapView
            poles={poles || []}
            transformers={transformers || []}
            selectedTicket={selectedTicket}
          />
        </div>

        {/* Right panel — Ticket detail or simulator */}
        {(selectedTicket || showSimulator) && (
          <div className="w-80 shrink-0 border-l border-surface-500/30 bg-surface-800">
            {showSimulator ? (
              <SimulatorPanel
                onClose={() => setShowSimulator(false)}
                onInject={triggerRefetch}
              />
            ) : selectedTicket ? (
              <TicketDetail
                ticket={selectedTicket}
                onUpdate={triggerRefetch}
              />
            ) : null}
          </div>
        )}
      </div>
    </div>
  );
}

export default App;
