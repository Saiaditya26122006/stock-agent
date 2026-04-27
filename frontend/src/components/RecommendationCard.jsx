import { TrendingUp, Target, ShieldAlert, Clock, Info, Zap, BarChart2 } from 'lucide-react';

function HorizonBadge({ horizon }) {
  const map = {
    SHORT_TERM: { label: "Short-Term", cls: "bg-amber-100 text-amber-700 border-amber-200" },
    LONG_TERM:  { label: "Long-Term",  cls: "bg-indigo-100 text-indigo-700 border-indigo-200" },
    BOTH:       { label: "Both",       cls: "bg-emerald-100 text-emerald-700 border-emerald-200" },
  };
  const entry = map[horizon];
  if (!entry) return null;
  return (
    <span className={`rounded-full border px-2.5 py-0.5 text-xs font-bold tracking-wide ${entry.cls}`}>
      {entry.label}
    </span>
  );
}

export default function RecommendationCard({ rec }) {
  const action = (rec.action || "SKIP").toUpperCase();
  const stock = rec.stock || rec.symbol || "N/A";
  const horizon = rec.horizon;

  const actionMap = {
    BUY:  "bg-emerald-100 text-emerald-800 border-emerald-200",
    SELL: "bg-rose-100 text-rose-800 border-rose-200",
    WATCH:"bg-slate-100 text-slate-700 border-slate-200",
    SKIP: "bg-slate-100 text-slate-700 border-slate-200",
  };
  const actionClass = actionMap[action] || actionMap.SKIP;

  // Prefer nested short_term / long_term blocks if present
  const st = rec.short_term || {};
  const lt = rec.long_term  || {};

  const entryPrice  = st.entry  || rec.entry_price;
  const target      = st.target || rec.target;
  const stopLoss    = st.stop_loss || rec.stop_loss;
  const holdPeriod  = st.hold   || rec.hold_period;
  const exitTrigger = st.exit_trigger;

  const accumulateBelow = lt.accumulate_below;
  const target6m        = lt.target_6m;
  const target12m       = lt.target_12m;
  const stopLossMon     = lt.stop_loss_monthly_close;
  const reviewDate      = lt.review_date;
  const thesis          = lt.thesis || rec.reasoning;

  const showLevels = entryPrice > 0 || target > 0 || stopLoss > 0;
  const isLongOnly  = horizon === "LONG_TERM";

  return (
    <article className="group relative rounded-2xl border border-slate-200 bg-white p-5 shadow-sm transition-all hover:shadow-md hover:border-indigo-200">

      {/* Header row */}
      <div className="mb-4 flex items-center justify-between border-b border-slate-100 pb-4">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-50 text-indigo-700 font-bold border border-indigo-100 shadow-sm text-sm">
            {stock.substring(0, 2)}
          </div>
          <h3 className="text-xl font-bold text-slate-800">{stock}</h3>
        </div>
        <div className="flex items-center flex-wrap gap-2 justify-end">
          <span className={`rounded-full border px-3 py-1 text-xs font-bold tracking-wide ${actionClass}`}>{action}</span>
          {horizon && <HorizonBadge horizon={horizon} />}
          {!horizon && (
            <span className="rounded-full border border-indigo-100 bg-indigo-50 px-3 py-1 text-xs font-bold tracking-wide text-indigo-700">
              {(rec.style || "intraday").toUpperCase()}
            </span>
          )}
        </div>
      </div>

      {/* Short-term levels */}
      {!isLongOnly && showLevels && (
        <div className="grid grid-cols-2 gap-y-3 gap-x-6 text-sm text-slate-600 px-1 mb-4">
          <div className="flex items-center gap-2">
            <TrendingUp size={15} className="text-indigo-400 shrink-0" />
            <span className="font-medium">Entry:</span>
            <span className="text-slate-900 font-semibold">₹{entryPrice ?? "-"}</span>
          </div>
          <div className="flex items-center gap-2">
            <Target size={15} className="text-emerald-500 shrink-0" />
            <span className="font-medium">Target:</span>
            <span className="text-emerald-600 font-bold">₹{target ?? "-"}</span>
          </div>
          <div className="flex items-center gap-2">
            <ShieldAlert size={15} className="text-rose-400 shrink-0" />
            <span className="font-medium">SL:</span>
            <span className="text-slate-900 font-semibold">₹{stopLoss ?? "-"}</span>
          </div>
          <div className="flex items-center gap-2">
            <Info size={15} className="text-amber-500 shrink-0" />
            <span className="font-medium">Risk:</span>
            <span className={`font-semibold ${rec.risk_score > 6 ? "text-rose-600" : "text-slate-900"}`}>
              {rec.risk_score ?? "-"}
            </span>
          </div>
          <div className="col-span-2 flex items-center gap-2 border-t border-slate-100 pt-3">
            <Clock size={15} className="text-slate-400 shrink-0" />
            <span className="font-medium text-slate-500">Hold:</span>
            <span className="text-slate-800 font-semibold">{holdPeriod || "N/A"}</span>
          </div>
          {exitTrigger && (
            <div className="col-span-2 flex items-start gap-2">
              <Zap size={15} className="text-amber-500 shrink-0 mt-0.5" />
              <span className="text-xs text-amber-700 font-medium leading-snug">Exit if: {exitTrigger}</span>
            </div>
          )}
        </div>
      )}

      {/* Long-term investment block */}
      {(isLongOnly || horizon === "BOTH") && (accumulateBelow || target6m || target12m) && (
        <div className="mb-4 rounded-xl bg-indigo-50 border border-indigo-100 p-4 space-y-2 text-sm">
          <div className="font-bold text-indigo-800 flex items-center gap-1.5 mb-1">
            <BarChart2 size={15} /> Investment Levels
          </div>
          {accumulateBelow && (
            <div className="flex justify-between text-slate-700">
              <span>Accumulate below</span>
              <span className="font-bold text-indigo-700">₹{accumulateBelow}</span>
            </div>
          )}
          {target6m && (
            <div className="flex justify-between text-slate-700">
              <span>6-month target</span>
              <span className="font-bold text-emerald-600">₹{target6m}</span>
            </div>
          )}
          {target12m && (
            <div className="flex justify-between text-slate-700">
              <span>12-month target</span>
              <span className="font-bold text-emerald-700">₹{target12m}</span>
            </div>
          )}
          {stopLossMon && (
            <div className="flex justify-between text-slate-700">
              <span>Monthly SL close</span>
              <span className="font-bold text-rose-600">₹{stopLossMon}</span>
            </div>
          )}
          {reviewDate && (
            <div className="text-xs text-indigo-500 pt-1">Review date: {reviewDate}</div>
          )}
        </div>
      )}

      {/* Reasoning / thesis */}
      <div className="rounded-xl bg-slate-50 p-4 border border-slate-100">
        <p className="text-sm leading-relaxed text-slate-700">{thesis || "No reasoning available."}</p>
      </div>
    </article>
  );
}
