/**
 * SimulatorPanel — fault injection controls for demo/testing.
 */

import { useState, useEffect } from 'react';
import { api } from '../../api/client';
import { SimulationTarget } from '../../types';

interface Props {
  onClose: () => void;
  onInject: () => void;
}

export default function SimulatorPanel({ onClose, onInject }: Props) {
  const [targets, setTargets] = useState<SimulationTarget | null>(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.getTargets().then(t => setTargets(t as SimulationTarget)).catch(() => {});
  }, []);

  const runAction = async (name: string, action: () => Promise<unknown>) => {
    setLoading(true);
    setResult(null);
    setError(null);
    try {
      const res = await action();
      setResult(`✅ ${name}: ${JSON.stringify(res, null, 2).slice(0, 200)}`);
      onInject();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed');
    } finally {
      setLoading(false);
    }
  };

  const firstDt = targets?.transformers?.[0]?.dt_id || '';
  const firstFeeder = targets?.feeders?.[0] || '';
  const firstPole = targets?.poles?.[0]?.pole_id || '';

  return (
    <div className="h-full flex flex-col bg-surface-800 border-l border-surface-500/30 animate-slide-in">
      <div className="panel-header">
        <h2 className="text-sm font-semibold text-gray-200 uppercase tracking-wider">
          🧪 Fault Simulator
        </h2>
        <button
          onClick={onClose}
          className="text-gray-400 hover:text-white transition-colors text-lg"
        >
          ✕
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        <p className="text-xs text-gray-500 mb-2">
          Inject faults through the telemetry pipeline. Watch tickets appear in real-time.
        </p>

        {/* Scenario buttons */}
        <div className="space-y-2">
          <ScenarioButton
            id="sim-span-fault"
            icon="⚡"
            title="Span Fault"
            description={`Wire break on ${firstDt || 'a DT'}`}
            loading={loading}
            onClick={() => runAction('Span Fault', () => api.injectSpanFault(firstDt))}
            disabled={!firstDt}
          />

          <ScenarioButton
            id="sim-dt-fault"
            icon="🔌"
            title="DT Fuse Blow"
            description={`Entire ${firstDt || 'DT'} goes dark`}
            loading={loading}
            onClick={() => runAction('DT Fault', () => api.injectDtFault(firstDt))}
            disabled={!firstDt}
          />

          <ScenarioButton
            id="sim-feeder-fault"
            icon="🏭"
            title="Feeder Fault"
            description={`All DTs on ${firstFeeder || 'feeder'}`}
            loading={loading}
            onClick={() => runAction('Feeder Fault', () => api.injectFeederFault(firstFeeder))}
            disabled={!firstFeeder}
          />

          <ScenarioButton
            id="sim-sensor-death"
            icon="📡"
            title="Dead Sensor (Noise)"
            description="Should NOT create a ticket"
            loading={loading}
            onClick={() => runAction('Sensor Death', () => api.injectSensorDeath(firstPole))}
            disabled={!firstPole}
          />

          <ScenarioButton
            id="sim-heartbeat"
            icon="💓"
            title="Heartbeat Burst"
            description="500 normal heartbeats"
            loading={loading}
            onClick={() => runAction('Heartbeat Burst', () => api.heartbeatBurst(500))}
          />
        </div>

        {/* Targets info */}
        {targets && (
          <div className="text-[10px] text-gray-600 mt-4">
            <p>{targets.transformers?.length || 0} DTs available</p>
            <p>{targets.feeders?.length || 0} feeders available</p>
            <p>{targets.poles?.length || 0} poles with devices</p>
          </div>
        )}

        {/* Result/Error display */}
        {result && (
          <div className="bg-accent-success/10 border border-accent-success/30 rounded-lg px-3 py-2 text-xs text-accent-success font-mono whitespace-pre-wrap">
            {result}
          </div>
        )}
        {error && (
          <div className="bg-accent-danger/10 border border-accent-danger/30 rounded-lg px-3 py-2 text-xs text-accent-danger">
            {error}
          </div>
        )}
      </div>
    </div>
  );
}


function ScenarioButton({
  id,
  icon,
  title,
  description,
  loading,
  onClick,
  disabled = false,
}: {
  id: string;
  icon: string;
  title: string;
  description: string;
  loading: boolean;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      id={id}
      onClick={onClick}
      disabled={loading || disabled}
      className="w-full text-left panel px-3 py-2.5 hover:bg-surface-700/50 transition-colors
        disabled:opacity-40 disabled:cursor-not-allowed"
    >
      <div className="flex items-center gap-2">
        <span className="text-base">{icon}</span>
        <div>
          <p className="text-sm font-medium text-gray-200">{title}</p>
          <p className="text-[10px] text-gray-500">{description}</p>
        </div>
        {loading && (
          <div className="ml-auto w-4 h-4 border-2 border-accent-primary/30 border-t-accent-primary rounded-full animate-spin" />
        )}
      </div>
    </button>
  );
}
