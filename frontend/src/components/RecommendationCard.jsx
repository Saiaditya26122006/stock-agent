import { TrendingUp, Target, ShieldAlert, Clock, Info } from 'lucide-react';

export default function RecommendationCard({ rec }) {
  const action = (rec.action || "SKIP").toUpperCase();
  const stock = rec.stock || rec.symbol || "N/A";

  const actionMap = {
    BUY: "bg-emerald-100 text-emerald-800 border-emerald-200",
    SELL: "bg-rose-100 text-rose-800 border-rose-200",
    WATCH: "bg-slate-100 text-slate-700 border-slate-200",
    SKIP: "bg-slate-100 text-slate-700 border-slate-200"
  };

  const actionClass = actionMap[action] || actionMap.SKIP;

  const showLevels = rec.entry_price > 0 || rec.target > 0 || rec.stop_loss > 0;

  return (
    <article className="group relative rounded-2xl border border-slate-200 bg-white p-5 shadow-sm transition-all hover:shadow-md hover:border-indigo-200">
      <div className="mb-4 flex items-center justify-between border-b border-slate-100 pb-4">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-50 text-indigo-700 font-bold border border-indigo-100 shadow-sm">
            {stock.substring(0, 2)}
          </div>
          <h3 className="text-xl font-bold text-slate-800">{stock}</h3>
        </div>
        <div className="flex items-center flex-wrap gap-2 justify-end">
          <span className={`rounded-full border px-3 py-1 text-xs font-bold tracking-wide ${actionClass}`}>{action}</span>
          <span className="rounded-full border border-indigo-100 bg-indigo-50 px-3 py-1 text-xs font-bold tracking-wide text-indigo-700">
            {(rec.style || "intraday").toUpperCase()}
          </span>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-y-4 gap-x-6 text-sm text-slate-600 px-1">
        
        {showLevels && (
           <>
             <div className="flex items-center gap-2">
               <TrendingUp size={16} className="text-indigo-400" />
               <span className="font-medium">Entry:</span> <span className="text-slate-900 font-semibold">₹{rec.entry_price ?? "-"}</span>
             </div>
             <div className="flex items-center gap-2">
               <Target size={16} className="text-emerald-500" />
               <span className="font-medium">Target:</span> <span className="text-emerald-600 font-bold">₹{rec.target ?? "-"}</span>
             </div>
             <div className="flex items-center gap-2">
               <ShieldAlert size={16} className="text-rose-400" />
               <span className="font-medium">Stop Loss:</span> <span className="text-slate-900 font-semibold">₹{rec.stop_loss ?? "-"}</span>
             </div>
           </>
        )}

        <div className="flex items-center gap-2">
          <Info size={16} className="text-amber-500" />
          <span className="font-medium">Risk:</span> 
          <span className={`font-semibold ${rec.risk_score > 6 ? 'text-rose-600' : 'text-slate-900'}`}>{rec.risk_score ?? "-"} (Sent: {rec.sentiment_score ?? 0})</span>
        </div>
        
        <div className="col-span-2 flex items-center gap-2 border-t border-slate-100 pt-4 mt-1">
          <Clock size={16} className="text-slate-400" />
          <span className="font-medium text-slate-500">Hold Period:</span>
          <span className="text-slate-800 font-semibold">{rec.hold_period || "N/A"}</span>
        </div>
      </div>

      <div className="mt-5 rounded-xl bg-slate-50 p-4 border border-slate-100">
        <p className="text-sm leading-relaxed text-slate-700">{rec.reasoning || "No reasoning available."}</p>
      </div>
    </article>
  );
}
