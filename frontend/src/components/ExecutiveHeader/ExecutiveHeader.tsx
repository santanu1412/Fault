import React from 'react';
import { NetworkStats, HealthStatus } from '../../types';

interface ExecutiveHeaderProps {
  stats: NetworkStats | null;
  health: HealthStatus | null;
  isSseConnected: boolean;
  activeCount: number;
  showSimulator: boolean;
  onToggleSimulator: () => void;
  alertBanner: string | null;
  onDismissAlert: () => void;
}

export const ExecutiveHeader: React.FC<ExecutiveHeaderProps> = ({
  stats,
  health,
  isSseConnected,
  activeCount,
  showSimulator,
  onToggleSimulator,
  alertBanner,
  onDismissAlert,
}) => {
  const totalPoles = stats?.total_poles || 0;
  const darkPoles = stats?.pole_states?.dark_confirmed || 0;
  const livePoles = stats?.pole_states?.live_confirmed || (totalPoles - darkPoles);
  const gridHealthPct = totalPoles > 0 ? ((livePoles / totalPoles) * 100).toFixed(1) : '100.0';

  return (
    <header className="bg-surface-900/90 backdrop-blur-md border-b border-surface-500/20 px-5 py-3 shrink-0 z-30 flex flex-col gap-2 shadow-2xl">
      {/* Alert Toast Banner */}
      {alertBanner && (
        <div className="bg-gradient-to-r from-accent-primary to-indigo-600 text-white text-xs px-4 py-2 rounded-lg flex items-center justify-between font-medium shadow-lg animate-pulse-slow">
          <div className="flex items-center gap-2">
            <span className="text-sm">🔔</span>
            <span>{alertBanner}</span>
          </div>
          <button
            onClick={onDismissAlert}
            className="text-gray-200 hover:text-white text-base font-bold px-1"
          >
            ×
          </button>
        </div>
      )}

      {/* Main Top Bar */}
      <div className="flex items-center justify-between">
        {/* Brand & Title */}
        <div className="flex items-center gap-4">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center shadow-lg shadow-indigo-500/20">
            <svg className="w-6 h-6 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-lg font-bold text-white tracking-tight font-display">KSPDB Fault Console</h1>
              <span className="bg-surface-700/60 border border-surface-500/30 text-indigo-400 text-[10px] font-mono font-semibold px-2 py-0.5 rounded-full">
                EXEC-OPS v1.0
              </span>
            </div>
            <p className="text-xs text-gray-400">Radial Power Network Telemetry & Fault Localization</p>
          </div>
        </div>

        {/* Executive KPI Cards */}
        <div className="flex items-center gap-3">
          {/* Grid Health Index */}
          <div className="bg-surface-800/80 border border-surface-500/30 px-3.5 py-1.5 rounded-xl flex items-center gap-3 shadow-inner">
            <div>
              <div className="text-[10px] uppercase font-bold text-gray-400 tracking-wider">Grid Health</div>
              <div className={`text-sm font-extrabold font-mono ${Number(gridHealthPct) > 98 ? 'text-emerald-400' : 'text-amber-400'}`}>
                {gridHealthPct}%
              </div>
            </div>
            <div className="w-8 h-8 rounded-lg bg-surface-700/50 flex items-center justify-center text-xs font-bold text-emerald-400">
              ⚡
            </div>
          </div>

          {/* Active Faults */}
          <div className={`border px-3.5 py-1.5 rounded-xl flex items-center gap-3 shadow-inner ${
            activeCount > 0 ? 'bg-red-950/40 border-red-500/40 fault-pulse' : 'bg-surface-800/80 border-surface-500/30'
          }`}>
            <div>
              <div className="text-[10px] uppercase font-bold text-gray-400 tracking-wider">Active Faults</div>
              <div className={`text-sm font-extrabold font-mono ${activeCount > 0 ? 'text-red-400' : 'text-emerald-400'}`}>
                {activeCount} {activeCount === 1 ? 'Incident' : 'Incidents'}
              </div>
            </div>
            <div className={`w-8 h-8 rounded-lg flex items-center justify-center text-xs font-bold ${
              activeCount > 0 ? 'bg-red-900/50 text-red-400' : 'bg-surface-700/50 text-gray-400'
            }`}>
              🚨
            </div>
          </div>

          {/* Telemetry Stream Status */}
          <div className="bg-surface-800/80 border border-surface-500/30 px-3.5 py-1.5 rounded-xl flex items-center gap-3">
            <div>
              <div className="text-[10px] uppercase font-bold text-gray-400 tracking-wider">Telemetry Stream</div>
              <div className="flex items-center gap-1.5 text-xs font-bold font-mono">
                <span className={`w-2 h-2 rounded-full ${
                  isSseConnected ? 'bg-emerald-400 animate-ping' : health?.status === 'healthy' ? 'bg-amber-400' : 'bg-red-500'
                }`} />
                <span className={isSseConnected ? 'text-emerald-400' : 'text-gray-300'}>
                  {isSseConnected ? 'SSE REALTIME' : health?.status === 'healthy' ? 'POLLING' : 'OFFLINE'}
                </span>
              </div>
            </div>
          </div>

          {/* Simulator Toggle Button */}
          <button
            onClick={onToggleSimulator}
            className={`flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold transition-all duration-200 shadow-md ${
              showSimulator
                ? 'bg-indigo-600 text-white shadow-indigo-500/30 ring-2 ring-indigo-400'
                : 'bg-surface-800 text-gray-200 hover:bg-surface-700 border border-surface-500/40 hover:border-gray-400'
            }`}
          >
            <span>🧪</span>
            <span>Fault Simulator</span>
          </button>
        </div>
      </div>
    </header>
  );
};

export default ExecutiveHeader;
