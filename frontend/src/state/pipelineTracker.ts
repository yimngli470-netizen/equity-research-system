import { useSyncExternalStore } from 'react';
import { api } from '../api/client';

export interface PipelineState {
  running: boolean;
  message: string | null;
  warnings?: string[];
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

export interface PipelineResult {
  ticker: string;
  ok: boolean;
  error?: string;
  usageLimited?: boolean; // failed because the subscription's 5-hr usage limit was hit
}

// Promise per ticker so a duplicate click during a run returns the same promise
// instead of kicking off a second pipeline. Cleared when the run resolves.
const inFlight = new Map<string, Promise<PipelineResult>>();

export function runPipeline(ticker: string): Promise<PipelineResult> {
  const existing = inFlight.get(ticker);
  if (existing) return existing;

  const promise = (async (): Promise<PipelineResult> => {
    setState(ticker, { running: true, message: 'Refreshing market data…' });
    try {
      const ingestionResults = await api.ingestion.run([ticker]);
      const ingestion =
        ingestionResults.find((r) => r.ticker === ticker) ?? ingestionResults[0];
      const ingestionSummary = ingestion
        ? `${ingestion.prices} prices · ${ingestion.financials} financials · ${ingestion.news} news`
        : 'no ingestion result';
      const warnings = ingestion?.warnings ?? [];
      setState(ticker, {
        running: true,
        message: `Data refreshed (${ingestionSummary}). Running agents…`,
        warnings,
      });

      // Smart mode (2026-06-11): each agent re-runs ONLY if its inputs changed since its last
      // report (new filing/transcript/estimates/material news — just-ingested above). A quiet-day
      // run costs ~0 LLM calls; an earnings day cascades the full re-run automatically.
      const agentResult = await api.analysis.run(ticker, { mode: 'smart', ingestFirst: false });
      const agentFailures = agentResult.results.filter((r) => !r.success);
      if (agentFailures.length > 0) {
        const usageLimited = agentFailures.some((r) => r.usage_limited);
        const detail = agentFailures
          .map((r) => `${r.agent_type}${r.error ? `: ${r.error}` : ''}`)
          .join(' · ');
        const err = new Error(
          usageLimited
            ? 'Subscription usage limit hit — re-run later to resume (smart-cache finishes the rest)'
            : `Agent refresh failed (${detail})`,
        ) as Error & { usageLimited?: boolean };
        err.usageLimited = usageLimited;
        throw err;
      }
      const cachedCount = agentResult.results.filter((r) => r.cached).length;
      const freshCount = agentResult.results.length - cachedCount;
      const agentSummary =
        cachedCount > 0
          ? `${freshCount} re-ran · ${cachedCount} reused (inputs unchanged)`
          : `${freshCount} agents re-ran`;
      setState(ticker, {
        running: true,
        message: `Agents done (${agentSummary}). Calculating score…`,
        warnings,
      });

      const scoreResult = await api.scoring.run(ticker);
      const decisionResult = await api.decision.run(ticker);

      const flagCount = decisionResult.risk_flags.length;
      setState(ticker, {
        running: false,
        message: `Pipeline complete · ${scoreResult.feature_count} features · score ${scoreResult.composite_score.toFixed(3)} · ${decisionResult.final_signal} (${decisionResult.confidence}, ${flagCount} flag${flagCount !== 1 ? 's' : ''})`,
        warnings,
      });
      return { ticker, ok: true };
    } catch (err) {
      const error = err instanceof Error ? err.message : 'Pipeline failed';
      const usageLimited = !!(err as { usageLimited?: boolean })?.usageLimited;
      setState(ticker, { running: false, message: error });
      return { ticker, ok: false, error, usageLimited };
    } finally {
      inFlight.delete(ticker);
    }
  })();

  inFlight.set(ticker, promise);
  return promise;
}

// NOTE: bulk "Run All" used to loop over tickers HERE in the browser, which meant a single
// dropped/stuck request silently stalled the whole watchlist and closing the tab killed it. That
// loop now lives in the backend (POST /api/pipeline/run-all + status polling, see
// app/pipeline/runner.py and Dashboard.runAll). This module keeps only the single-ticker pipeline
// (the per-stock "Run" button in StockDetail).

export function clearPipelineMessage(ticker: string) {
  const s = getState(ticker);
  if (s.message && !s.running) setState(ticker, EMPTY);
}
