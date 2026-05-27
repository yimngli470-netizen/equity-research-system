import { useSyncExternalStore } from 'react';
import { api } from '../api/client';

export interface PipelineState {
  running: boolean;
  message: string | null;
}

const EMPTY: PipelineState = { running: false, message: null };

const states = new Map<string, PipelineState>();
const listeners = new Set<() => void>();

function notify() {
  for (const cb of listeners) cb();
}

function subscribe(cb: () => void) {
  listeners.add(cb);
  return () => {
    listeners.delete(cb);
  };
}

function getState(ticker: string): PipelineState {
  return states.get(ticker) ?? EMPTY;
}

function setState(ticker: string, s: PipelineState) {
  if (!s.running && !s.message) states.delete(ticker);
  else states.set(ticker, s);
  notify();
}

export function usePipelineState(ticker: string): PipelineState {
  return useSyncExternalStore(
    subscribe,
    () => getState(ticker),
    () => EMPTY,
  );
}

// Promise per ticker so a duplicate click during a run returns the same promise
// instead of kicking off a second pipeline. Cleared when the run resolves.
const inFlight = new Map<string, Promise<void>>();

export function runPipeline(ticker: string): Promise<void> {
  const existing = inFlight.get(ticker);
  if (existing) return existing;

  const promise = (async () => {
    setState(ticker, { running: true, message: 'Refreshing market data…' });
    try {
      const ingestionResults = await api.ingestion.run([ticker]);
      const ingestion =
        ingestionResults.find((r) => r.ticker === ticker) ?? ingestionResults[0];
      const ingestionSummary = ingestion
        ? `${ingestion.prices} prices · ${ingestion.financials} financials · ${ingestion.news} news`
        : 'no ingestion result';
      setState(ticker, {
        running: true,
        message: `Data refreshed (${ingestionSummary}). Running agents…`,
      });

      const agentResult = await api.analysis.run(ticker, { force: true, ingestFirst: false });
      const agentFailures = agentResult.results.filter((r) => !r.success);
      if (agentFailures.length > 0) {
        const detail = agentFailures
          .map((r) => `${r.agent_type}${r.error ? `: ${r.error}` : ''}`)
          .join(' · ');
        throw new Error(`Agent refresh failed (${detail})`);
      }
      const agentSummary = agentResult.results.map((r) => `${r.agent_type}=ok`).join(' · ');
      setState(ticker, {
        running: true,
        message: `Agents done (${agentSummary}). Calculating score…`,
      });

      const scoreResult = await api.scoring.run(ticker);
      const decisionResult = await api.decision.run(ticker);

      const flagCount = decisionResult.risk_flags.length;
      setState(ticker, {
        running: false,
        message: `Pipeline complete · ${scoreResult.feature_count} features · score ${scoreResult.composite_score.toFixed(3)} · ${decisionResult.final_signal} (${decisionResult.confidence}, ${flagCount} flag${flagCount !== 1 ? 's' : ''})`,
      });
    } catch (err) {
      setState(ticker, {
        running: false,
        message: err instanceof Error ? err.message : 'Pipeline failed',
      });
    } finally {
      inFlight.delete(ticker);
    }
  })();

  inFlight.set(ticker, promise);
  return promise;
}

export function clearPipelineMessage(ticker: string) {
  const s = getState(ticker);
  if (s.message && !s.running) setState(ticker, EMPTY);
}
