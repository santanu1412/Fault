/**
 * IncidentList — sorted list of incidents with severity indicators and filter tabs.
 */

import { useState } from 'react';
import { Ticket } from '../../types';

interface Props {
  tickets: Ticket[];
  selectedId: number | null;
  onSelect: (ticket: Ticket) => void;
}

const KIND_LABELS: Record<string, string> = {
  span: 'Span Fault',
  dt: 'DT Fault',
  feeder: 'Feeder Fault',
  sensor_only: 'Sensor Issue',
};

const KIND_ICONS: Record<string, string> = {
  span: '⚡',
  dt: '🔌',
  feeder: '🏭',
  sensor_only: '📡',
};

const STATUS_COLORS: Record<string, string> = {
  detected: 'bg-red-500',
  acknowledged: 'bg-orange-500',
  crew_assigned: 'bg-yellow-500',
  resolved: 'bg-blue-500',
  verified: 'bg-green-500',
  closed: 'bg-gray-500',
};

type FilterTab = 'all' | 'active' | 'resolved';

const ACTIVE_STATUSES = ['detected', 'acknowledged', 'crew_assigned'];
const RESOLVED_STATUSES = ['resolved', 'verified', 'closed'];

function getConfidenceLabel(confidence: number): { text: string; class: string } {
  if (confidence >= 0.8) return { text: 'HIGH', class: 'confidence-high' };
  if (confidence >= 0.5) return { text: 'MEDIUM', class: 'confidence-medium' };
  return { text: 'LOW', class: 'confidence-low' };
}

function timeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export default function IncidentList({ tickets, selectedId, onSelect }: Props) {
  const [filter, setFilter] = useState<FilterTab>('all');

  // Filter tickets
  const filtered = tickets.filter(t => {
    if (filter === 'active') return ACTIVE_STATUSES.includes(t.status);
    if (filter === 'resolved') return RESOLVED_STATUSES.includes(t.status);
    return true;
  });

  // Sort by: active first, then households affected (severity), then confidence
  const sorted = [...filtered].sort((a, b) => {
    const aActive = ACTIVE_STATUSES.includes(a.status) ? 0 : 1;
    const bActive = ACTIVE_STATUSES.includes(b.status) ? 0 : 1;
    if (aActive !== bActive) return aActive - bActive;

    if (a.incident.households_affected !== b.incident.households_affected) {
      return b.incident.households_affected - a.incident.households_affected;
    }

    return b.incident.confidence - a.incident.confidence;
  });

  const activeCount = tickets.filter(t => ACTIVE_STATUSES.includes(t.status)).length;
  const resolvedCount = tickets.filter(t => RESOLVED_STATUSES.includes(t.status)).length;

  return (
    <div className="h-full flex flex-col">
      <div className="panel-header">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold text-gray-200 uppercase tracking-wider">
            Incidents
          </h2>
          {activeCount > 0 && (
            <span className="badge badge-dark fault-pulse">{activeCount} active</span>
          )}
        </div>
      </div>

      {/* Filter tabs */}
      <div className="flex border-b border-surface-500/30 shrink-0">
        {([
          { key: 'all' as FilterTab, label: 'All', count: tickets.length },
          { key: 'active' as FilterTab, label: 'Active', count: activeCount },
          { key: 'resolved' as FilterTab, label: 'Resolved', count: resolvedCount },
        ]).map(tab => (
          <button
            key={tab.key}
            id={`filter-${tab.key}`}
            onClick={() => setFilter(tab.key)}
            className={`flex-1 px-3 py-2 text-xs font-medium transition-colors
              ${filter === tab.key 
                ? 'text-accent-primary border-b-2 border-accent-primary bg-surface-700/30' 
                : 'text-gray-500 hover:text-gray-300 hover:bg-surface-700/20'}`}
          >
            {tab.label} <span className="text-[10px] opacity-60">({tab.count})</span>
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto">
        {sorted.length === 0 ? (
          <div className="px-4 py-8 text-center text-gray-500 text-sm">
            <div className="text-3xl mb-2">
              {filter === 'active' ? '✅' : filter === 'resolved' ? '📋' : '✅'}
            </div>
            {filter === 'active' ? 'No active incidents' : 
             filter === 'resolved' ? 'No resolved incidents' : 
             'No incidents'}
          </div>
        ) : (
          sorted.map((ticket) => {
            const inc = ticket.incident;
            const conf = getConfidenceLabel(inc.confidence);
            const isSelected = ticket.id === selectedId;

            return (
              <button
                key={ticket.id}
                id={`ticket-${ticket.id}`}
                onClick={() => onSelect(ticket)}
                className={`w-full text-left px-4 py-3 border-b border-surface-500/20 
                  hover:bg-surface-700/50 transition-colors cursor-pointer
                  ${isSelected ? 'bg-surface-700/70 border-l-2 border-l-accent-primary' : ''}
                `}
              >
                <div className="flex items-start justify-between gap-2 mb-1">
                  <div className="flex items-center gap-2">
                    <span className="text-base">{KIND_ICONS[inc.kind] || '⚠'}</span>
                    <span className="text-sm font-medium text-gray-200">
                      {KIND_LABELS[inc.kind] || inc.kind}
                    </span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <div className={`w-2 h-2 rounded-full ${STATUS_COLORS[ticket.status] || 'bg-gray-500'}`} />
                    <span className="text-xs text-gray-400 capitalize">{ticket.status.replace('_', ' ')}</span>
                  </div>
                </div>

                <div className="flex items-center gap-3 text-xs text-gray-400 mb-1">
                  <span>{inc.dt_id || inc.feeder_id}</span>
                  <span>•</span>
                  <span>{inc.dark_pole_count} poles</span>
                  <span>•</span>
                  <span>~{inc.households_affected} homes</span>
                </div>

                <div className="flex items-center justify-between text-xs">
                  <div className="flex items-center gap-2">
                    <span className={conf.class + ' font-mono font-medium'}>{conf.text}</span>
                    {inc.topology_basis === 'inferred' && (
                      <span className="text-grid-inferred text-[10px]">⚠ INFERRED</span>
                    )}
                  </div>
                  {inc.pincode && (
                    <span className="text-gray-500 font-mono">PIN: {inc.pincode}</span>
                  )}
                </div>

                <div className="text-[10px] text-gray-500 mt-1">
                  {timeAgo(ticket.created_at)}
                </div>
              </button>
            );
          })
        )}
      </div>
    </div>
  );
}
