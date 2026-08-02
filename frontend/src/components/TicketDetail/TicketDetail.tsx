/**
 * TicketDetail — full ticket view with lifecycle buttons, confidence breakdown, and audit log.
 */

import { useState } from 'react';
import { Ticket } from '../../types';
import { api } from '../../api/client';

interface Props {
  ticket: Ticket;
  onUpdate: () => void;
}

const STATUS_FLOW = ['detected', 'acknowledged', 'crew_assigned', 'resolved', 'verified', 'closed'];

const NEXT_ACTIONS: Record<string, { label: string; target: string; style: string } | null> = {
  detected: { label: 'Acknowledge', target: 'acknowledged', style: 'btn-primary' },
  acknowledged: { label: 'Assign Crew', target: 'crew_assigned', style: 'btn-primary' },
  crew_assigned: { label: 'Mark Resolved', target: 'resolved', style: 'btn-success' },
  resolved: null, // System auto-verifies
  verified: { label: 'Close Ticket', target: 'closed', style: 'btn-ghost' },
  closed: null,
};

const CONFIDENCE_FACTOR_LABELS: Record<string, { label: string; icon: string }> = {
  topology: { label: 'Topology', icon: '🗺' },
  device_coverage: { label: 'Device Coverage', icon: '📡' },
  recency: { label: 'Data Recency', icon: '⏱' },
  rssi: { label: 'Signal Strength', icon: '📶' },
};

export default function TicketDetail({ ticket, onUpdate }: Props) {
  const [transitioning, setTransitioning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [question, setQuestion] = useState('');
  const [answer, setAnswer] = useState<string | null>(null);
  const [asking, setAsking] = useState(false);

  const inc = ticket.incident;
  const nextAction = NEXT_ACTIONS[ticket.status];

  const handleTransition = async () => {
    if (!nextAction) return;
    setTransitioning(true);
    setError(null);

    try {
      await api.transitionTicket(ticket.id, nextAction.target);
      onUpdate();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Transition failed');
    } finally {
      setTransitioning(false);
    }
  };

  const handleRepair = async () => {
    setTransitioning(true);
    setError(null);
    try {
      await api.repairIncident(ticket.incident_id);
      onUpdate();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Repair simulation failed');
    } finally {
      setTransitioning(false);
    }
  };

  const handleAsk = async () => {
    if (!question.trim()) return;
    setAsking(true);
    try {
      const res = await api.askQuestion(ticket.id, question) as { answer: string };
      setAnswer(res.answer);
    } catch {
      setAnswer('Failed to get answer. Please try again.');
    } finally {
      setAsking(false);
    }
  };

  const confidencePct = Math.round(inc.confidence * 100);
  const breakdown = (inc as any).confidence_breakdown as Record<string, number> | undefined;

  return (
    <div className="h-full flex flex-col overflow-y-auto">
      <div className="panel-header">
        <h2 className="text-sm font-semibold text-gray-200 uppercase tracking-wider">
          Ticket #{ticket.id}
        </h2>
        <span className={`badge ${
          ['detected', 'acknowledged', 'crew_assigned'].includes(ticket.status)
            ? 'badge-dark'
            : ticket.status === 'verified' || ticket.status === 'closed'
            ? 'badge-live'
            : 'badge-suspect'
        }`}>
          {ticket.status.replace('_', ' ').toUpperCase()}
        </span>
      </div>

      <div className="flex-1 p-4 space-y-4">
        {/* Status progress bar */}
        <div className="flex items-center gap-1">
          {STATUS_FLOW.map((s, i) => (
            <div key={s} className="flex items-center">
              <div className={`w-3 h-3 rounded-full border-2 ${
                STATUS_FLOW.indexOf(ticket.status) >= i
                  ? 'bg-accent-primary border-accent-primary'
                  : 'border-surface-500 bg-transparent'
              }`} />
              {i < STATUS_FLOW.length - 1 && (
                <div className={`w-6 h-0.5 ${
                  STATUS_FLOW.indexOf(ticket.status) > i
                    ? 'bg-accent-primary'
                    : 'bg-surface-500'
                }`} />
              )}
            </div>
          ))}
        </div>

        {/* Fault info */}
        <div className="grid grid-cols-2 gap-3 text-sm">
          <div>
            <span className="text-gray-500 text-xs">Fault Type</span>
            <p className="text-gray-200 font-medium">
              {inc.kind === 'span' ? 'Span Fault' :
               inc.kind === 'dt' ? 'DT Fault' :
               inc.kind === 'feeder' ? 'Feeder Fault' : inc.kind}
            </p>
          </div>
          <div>
            <span className="text-gray-500 text-xs">Location</span>
            <p className="text-gray-200 font-mono text-xs">
              {inc.centroid_lat?.toFixed(4)}°N, {inc.centroid_lon?.toFixed(4)}°E
            </p>
          </div>
          <div>
            <span className="text-gray-500 text-xs">PIN Code</span>
            <p className="text-gray-200 font-mono">{inc.pincode || '—'}</p>
          </div>
          <div>
            <span className="text-gray-500 text-xs">Households</span>
            <p className="text-gray-200">~{inc.households_affected}</p>
          </div>
          <div>
            <span className="text-gray-500 text-xs">DT / Feeder</span>
            <p className="text-gray-200 font-mono text-xs">{inc.dt_id || '—'} / {inc.feeder_id}</p>
          </div>
          <div>
            <span className="text-gray-500 text-xs">Dark Poles</span>
            <p className="text-gray-200">{inc.dark_pole_count}</p>
          </div>
        </div>

        {/* Confidence with breakdown */}
        <div className="panel px-3 py-2">
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs text-gray-400">Confidence</span>
            <span className={`text-sm font-mono font-bold ${
              confidencePct >= 80 ? 'confidence-high' :
              confidencePct >= 50 ? 'confidence-medium' : 'confidence-low'
            }`}>{confidencePct}%</span>
          </div>
          <div className="w-full bg-surface-600 rounded-full h-1.5">
            <div
              className={`h-1.5 rounded-full transition-all duration-500 ${
                confidencePct >= 80 ? 'bg-accent-success' :
                confidencePct >= 50 ? 'bg-accent-warning' : 'bg-accent-danger'
              }`}
              style={{ width: `${confidencePct}%` }}
            />
          </div>

          {/* Per-factor breakdown */}
          {breakdown && Object.keys(breakdown).filter(k => k !== 'overall').length > 0 && (
            <div className="mt-2 space-y-1.5">
              {Object.entries(CONFIDENCE_FACTOR_LABELS).map(([key, { label, icon }]) => {
                const value = breakdown[key];
                if (value === undefined) return null;
                const pct = Math.round(value * 100);
                return (
                  <div key={key} className="flex items-center gap-2">
                    <span className="text-[10px] w-3">{icon}</span>
                    <span className="text-[10px] text-gray-500 w-24">{label}</span>
                    <div className="flex-1 bg-surface-600 rounded-full h-1">
                      <div
                        className="h-1 rounded-full bg-accent-primary/60 transition-all duration-300"
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                    <span className="text-[10px] text-gray-400 font-mono w-8 text-right">{pct}%</span>
                  </div>
                );
              })}
            </div>
          )}

          <div className="flex items-center gap-2 mt-2">
            <span className="text-[10px] text-gray-500">
              Topology: {inc.topology_basis}
            </span>
            {inc.topology_basis === 'inferred' && (
              <span className="text-[10px] text-grid-inferred font-medium">
                ⚠ Verify span boundaries before dispatch
              </span>
            )}
            {inc.topology_basis === 'mixed' && (
              <span className="text-[10px] text-accent-warning font-medium">
                ⚠ Partial verification recommended
              </span>
            )}
          </div>
        </div>

        {/* Boundary edges */}
        {inc.boundary_edges && inc.boundary_edges.length > 0 && (
          <div>
            <span className="text-xs text-gray-500 block mb-1">Fault Boundary</span>
            <div className="space-y-1">
              {inc.boundary_edges.map((edge, i) => (
                <div key={i} className="flex items-center gap-2 text-xs font-mono">
                  <span className="text-grid-live">{edge.parent}</span>
                  <span className="text-gray-500">→</span>
                  <span className="text-grid-dark">{edge.child}</span>
                  <span className={`text-[10px] ${
                    edge.source === 'surveyed' ? 'text-gray-500' : 'text-grid-inferred'
                  }`}>({edge.source})</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* AI Narrative */}
        {ticket.ai_narrative && (
          <div className="panel px-3 py-2">
            <span className="text-[10px] text-gray-500 uppercase tracking-wider block mb-1">
              AI Dispatch Brief
            </span>
            <p className="text-sm text-gray-300 leading-relaxed">{ticket.ai_narrative}</p>
          </div>
        )}

        {/* Actions */}
        <div className="flex items-center gap-2">
          {nextAction && (
            <button
              id={`transition-${ticket.id}`}
              className={nextAction.style}
              onClick={handleTransition}
              disabled={transitioning}
            >
              {transitioning ? 'Processing...' : nextAction.label}
            </button>
          )}

          {['detected', 'acknowledged', 'crew_assigned'].includes(ticket.status) && (
            <button
              id={`repair-${ticket.id}`}
              className="btn-ghost text-xs"
              onClick={handleRepair}
              disabled={transitioning}
            >
              🔧 Simulate Repair
            </button>
          )}

          {ticket.status === 'resolved' && (
            <span className="text-xs text-gray-500 italic">
              Waiting for telemetry verification...
            </span>
          )}
        </div>

        {error && (
          <div className="bg-accent-danger/20 border border-accent-danger/30 rounded-lg px-3 py-2 text-sm text-accent-danger">
            {error}
          </div>
        )}

        {/* Q&A */}
        <div className="panel px-3 py-2">
          <span className="text-[10px] text-gray-500 uppercase tracking-wider block mb-2">
            Ask about this ticket
          </span>
          <div className="flex gap-2">
            <input
              id={`qa-input-${ticket.id}`}
              type="text"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleAsk()}
              placeholder="e.g., How many poles are affected?"
              className="flex-1 bg-surface-700 border border-surface-500/50 rounded-lg px-3 py-1.5 
                text-sm text-gray-200 placeholder-gray-500
                focus:outline-none focus:border-accent-primary/50"
            />
            <button
              className="btn-primary text-xs px-3"
              onClick={handleAsk}
              disabled={asking || !question.trim()}
            >
              {asking ? '...' : 'Ask'}
            </button>
          </div>
          {answer && (
            <p className="mt-2 text-sm text-gray-300 bg-surface-700 rounded px-3 py-2">
              {answer}
            </p>
          )}
        </div>

        {/* Audit log */}
        <div>
          <span className="text-xs text-gray-500 block mb-2">Audit Log</span>
          <div className="space-y-1">
            {[...ticket.history].reverse().map((entry, i) => (
              <div key={i} className="flex items-start gap-2 text-xs">
                <span className="text-gray-600 font-mono whitespace-nowrap">
                  {new Date(entry.ts).toLocaleTimeString()}
                </span>
                <span className={`uppercase font-medium ${
                  entry.actor === 'system' ? 'text-accent-primary' : 'text-accent-warning'
                }`}>
                  {entry.actor}
                </span>
                <span className="text-gray-400">{entry.reason}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
