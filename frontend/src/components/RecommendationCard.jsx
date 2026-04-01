function actionClasses(action) {
  if (action === "BUY") return "bg-emerald-500/20 text-emerald-300";
  if (action === "SELL") return "bg-rose-500/20 text-rose-300";
  return "bg-slate-500/20 text-slate-300";
}

export default function RecommendationCard({ rec }) {
  const action = (rec.action || "SKIP").toUpperCase();
  const stock = rec.stock || rec.symbol || "N/A";
  return (
    <article className="rounded-xl border border-slate-700 bg-slate-800 p-4 shadow-sm">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-2xl font-bold text-white">{stock}</h3>
        <div className="flex gap-2">
          <span className={`rounded px-2 py-1 text-xs font-semibold ${actionClasses(action)}`}>{action}</span>
          <span className="rounded bg-indigo-500/20 px-2 py-1 text-xs font-semibold text-indigo-300">
            {(rec.style || "intraday").toUpperCase()}
          </span>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-2 text-sm text-slate-200 sm:grid-cols-2">
        <p>Entry: Rs.{rec.entry_price ?? "-"}</p>
        <p>Target: Rs.{rec.target ?? "-"}</p>
        <p>Stop Loss: Rs.{rec.stop_loss ?? "-"}</p>
        <p>Risk Score: {rec.risk_score ?? "-"}/10</p>
        <p className="sm:col-span-2">Hold Period: {rec.hold_period || "N/A"}</p>
      </div>

      <p className="mt-3 text-sm leading-6 text-slate-300">{rec.reasoning || "No reasoning available."}</p>
    </article>
  );
}
