import type { WatchlistRow } from './rows';

/** Post-earnings notification marker.
 *
 *  Deliberately passive: it says "this company reported and your analysis predates it", and
 *  nothing more. Clicking through to the stock and hitting Run Full Pipeline is what actually
 *  spends the LLM call — the system stays pull-model for all analysis.
 */
export default function EarningsAlertDot({ alert }: { alert: WatchlistRow['earnings_alert'] }) {
  if (!alert) return null;
  const reported = alert.severity === 'reported';
  return (
    <span
      title={
        reported
          ? `Reported since the last earnings analysis — ${alert.reason}`
          : `New transcript since the last earnings analysis — ${alert.reason}`
      }
      style={{
        display: 'inline-block',
        width: 6,
        height: 6,
        borderRadius: '50%',
        marginLeft: 6,
        verticalAlign: 'middle',
        background: reported ? 'var(--color-neg-fg)' : 'var(--color-warn-fg)',
      }}
    />
  );
}
