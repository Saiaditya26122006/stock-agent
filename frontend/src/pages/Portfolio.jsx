import { useEffect, useState } from "react";
import client from "../api/client";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine,
} from "recharts";
import { TrendingUp, TrendingDown, Briefcase, Clock, Activity, ChevronRight } from "lucide-react";

function HorizonBadge({ horizon }) {
  if (!horizon) return null;
  const styles = {
    SHORT_TERM: "bg-amber-100 text-amber-700",
    LONG_TERM:  "bg-indigo-100 text-indigo-700",
    BOTH:       "bg-emerald-100 text-emerald-700",
  };
  const labels = { SHORT_TERM: "Short", LONG_TERM: "Long", BOTH: "Both" };
  return (
    <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${styles[horizon] || "bg-slate-100 text-slate-500"}`}>
      {labels[horizon] || horizon}
    </span>
  );
}

function PnlBadge({ pnl }) {
  if (pnl == null) return <span className="text-slate-400 text-sm">—</span>;
  const positive = pnl >= 0;
  return (
    <span className={`font-bold text-sm ${positive ? "text-emerald-600" : "text-rose-600"}`}>
      {positive ? "+" : ""}Rs.{Number(pnl).toLocaleString("en-IN", { maximumFractionDigits: 0 })}
    </span>
  );
}

const OUTCOME_LABELS = {
  hit_target: { label: "Target Hit", color: "bg-emerald-100 text-emerald-700" },
  hit_sl: { label: "SL Hit", color: "bg-rose-100 text-rose-700" },
  paper_hit_target: { label: "Paper Target", color: "bg-teal-100 text-teal-700" },
  paper_hit_sl: { label: "Paper SL", color: "bg-orange-100 text-orange-700" },
  expired: { label: "Expired", color: "bg-slate-100 text-slate-500" },
  still_open: { label: "Open", color: "bg-indigo-100 text-indigo-700" },
};

export default function Portfolio() {
  const [openPositions, setOpenPositions] = useState([]);
  const [equityCurve, setEquityCurve] = useState([]);
  const [closedTrades, setClosedTrades] = useState([]);
  const [winrate, setWinrate] = useState({ win_rate: 0, wins: 0, losses: 0, total: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [tab, setTab] = useState("open");

  useEffect(() => {
    let mounted = true;
    const load = async () => {
      setLoading(true);
      setError("");
      try {
        const [openResp, histResp, wrResp] = await Promise.all([
          client.get("/recommendations/open"),
          client.get("/recommendations/history?last_n=60"),
          client.get("/recommendations/winrate?last_n=20"),
        ]);
        if (!mounted) return;
        setOpenPositions(openResp.data.positions || []);
        setEquityCurve(histResp.data.equity_curve || []);
        setClosedTrades(histResp.data.trades || []);
        setWinrate(wrResp.data || {});
      } catch (err) {
        if (mounted) setError(err?.response?.data?.detail || "Failed to load portfolio.");
      } finally {
        if (mounted) setLoading(false);
      }
    };
    load();
    return () => { mounted = false; };
  }, []);

  const totalUnrealisedPnl = openPositions.reduce((acc, p) => acc + (Number(p.pnl) || 0), 0);
  const equityMin = equityCurve.length ? Math.min(...equityCurve.map(d => d.equity)) : 0;
  const equityMax = equityCurve.length ? Math.max(...equityCurve.map(d => d.equity)) : 0;
  const lastEquity = equityCurve.length ? equityCurve[equityCurve.length - 1].equity : 0;

  return (
    <div className="space-y-8 animate-in fade-in duration-500">

      {/* Header */}
      <div className="rounded-3xl bg-white p-8 shadow-sm border border-slate-200">
        <h2 className="text-3xl font-extrabold text-slate-800 tracking-tight flex items-center gap-2">
          Portfolio <Briefcase size={28} className="text-indigo-500" />
        </h2>
        <p className="text-slate-500 font-medium mt-1">Real-time P&amp;L, open positions &amp; equity curve.</p>
      </div>

      {error && (
        <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700 font-medium">{error}</div>
      )}

      {/* KPI strip */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="bg-white rounded-2xl p-5 border border-slate-200 shadow-sm">
          <div className="text-slate-400 text-xs font-semibold uppercase tracking-wider mb-1">Open Positions</div>
          <div className="text-3xl font-black text-slate-800">{openPositions.length}</div>
        </div>
        <div className="bg-white rounded-2xl p-5 border border-slate-200 shadow-sm">
          <div className="text-slate-400 text-xs font-semibold uppercase tracking-wider mb-1">Win Rate (20)</div>
          <div className={`text-3xl font-black ${winrate.win_rate >= 55 ? "text-emerald-600" : winrate.win_rate >= 45 ? "text-amber-500" : "text-rose-600"}`}>
            {winrate.win_rate}%
          </div>
        </div>
        <div className="bg-white rounded-2xl p-5 border border-slate-200 shadow-sm">
          <div className="text-slate-400 text-xs font-semibold uppercase tracking-wider mb-1">Net Equity</div>
          <div className={`text-3xl font-black ${lastEquity >= 0 ? "text-emerald-600" : "text-rose-600"}`}>
            {lastEquity >= 0 ? "+" : ""}Rs.{Math.abs(lastEquity).toLocaleString("en-IN", { maximumFractionDigits: 0 })}
          </div>
        </div>
        <div className="bg-white rounded-2xl p-5 border border-slate-200 shadow-sm">
          <div className="text-slate-400 text-xs font-semibold uppercase tracking-wider mb-1">W / L</div>
          <div className="text-3xl font-black text-slate-800">
            <span className="text-emerald-600">{winrate.wins}</span>
            <span className="text-slate-300 mx-1">/</span>
            <span className="text-rose-600">{winrate.losses}</span>
          </div>
        </div>
      </div>

      {/* Equity Curve */}
      <div className="bg-white rounded-3xl p-6 border border-slate-200 shadow-sm">
        <h3 className="text-lg font-bold text-slate-800 mb-4 flex items-center gap-2">
          <Activity size={20} className="text-indigo-500" /> Equity Curve (last 60 trades)
        </h3>
        {loading ? (
          <div className="h-56 flex items-center justify-center text-slate-400">Loading...</div>
        ) : equityCurve.length < 2 ? (
          <div className="h-56 flex items-center justify-center text-slate-400 font-medium text-sm">
            Not enough closed trades yet — equity curve appears after your first completed trades.
          </div>
        ) : (
          <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={equityCurve} margin={{ top: 4, right: 4, left: 0, bottom: 4 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f1f5f9" />
                <XAxis dataKey="date" tick={{ fill: "#94a3b8", fontSize: 11 }} axisLine={false} tickLine={false} interval="preserveStartEnd" />
                <YAxis tick={{ fill: "#94a3b8", fontSize: 11 }} axisLine={false} tickLine={false}
                  tickFormatter={(v) => `₹${(v / 1000).toFixed(1)}k`} domain={[equityMin * 1.1 - 100, equityMax * 1.1 + 100]} />
                <Tooltip
                  contentStyle={{ borderRadius: "12px", border: "none", boxShadow: "0 4px 6px -1px rgb(0 0 0 / 0.1)" }}
                  formatter={(v) => [`₹${Number(v).toLocaleString("en-IN")}`, "Equity"]}
                  labelFormatter={(l) => `Date: ${l}`}
                />
                <ReferenceLine y={0} stroke="#e5e7eb" strokeDasharray="4 4" />
                <Line
                  type="monotone" dataKey="equity" stroke="#6366f1" strokeWidth={2.5}
                  dot={false} activeDot={{ r: 5, fill: "#6366f1" }}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

      {/* Tabs: Open Positions / Trade History */}
      <div className="bg-white rounded-3xl border border-slate-200 shadow-sm overflow-hidden">
        <div className="flex border-b border-slate-100">
          {[
            { key: "open",    label: `Open Positions (${openPositions.length})`,  icon: Clock },
            { key: "history", label: `Trade History (${closedTrades.length})`,    icon: TrendingUp },
          ].map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              onClick={() => setTab(key)}
              className={`flex items-center gap-2 px-6 py-4 text-sm font-semibold transition-colors border-b-2 -mb-px ${
                tab === key
                  ? "border-indigo-500 text-indigo-600"
                  : "border-transparent text-slate-500 hover:text-slate-700"
              }`}
            >
              <Icon size={16} />
              {label}
            </button>
          ))}
        </div>

        {loading ? (
          <div className="p-12 flex justify-center text-indigo-500">
            <Activity className="animate-spin" size={28} />
          </div>
        ) : tab === "open" ? (
          openPositions.length === 0 ? (
            <div className="p-12 text-center text-slate-400 font-medium text-sm">
              No open BUY positions. Run analysis to find new entries.
            </div>
          ) : (
            <div className="divide-y divide-slate-50">
              {openPositions.map((pos) => (
                <div key={pos.id} className="flex items-center justify-between px-6 py-4 hover:bg-slate-50 transition-colors">
                  <div className="flex items-center gap-3 min-w-0">
                    <div className="min-w-0">
                      <div className="font-bold text-slate-800 text-sm flex items-center gap-2">
                        {pos.stock || pos.symbol}
                        <HorizonBadge horizon={pos.horizon} />
                      </div>
                      <div className="text-xs text-slate-400 mt-0.5">
                        Entry Rs.{pos.entry_price} &middot; {pos.date}
                      </div>
                    </div>
                  </div>
                  <div className="text-right">
                    <PnlBadge pnl={pos.pnl} />
                    <div className="text-xs text-slate-400 mt-0.5">
                      {pos.target ? `Target Rs.${pos.target}` : ""}
                      {pos.stop_loss ? ` · SL Rs.${pos.stop_loss}` : ""}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )
        ) : (
          closedTrades.length === 0 ? (
            <div className="p-12 text-center text-slate-400 font-medium text-sm">
              No closed trades yet — outcomes will appear here after positions are resolved.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead>
                  <tr className="bg-slate-50 border-b border-slate-100">
                    <th className="px-6 py-3 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">Stock</th>
                    <th className="px-6 py-3 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">Horizon</th>
                    <th className="px-6 py-3 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">Date</th>
                    <th className="px-6 py-3 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">Outcome</th>
                    <th className="px-6 py-3 text-right text-xs font-semibold text-slate-400 uppercase tracking-wider">P&amp;L</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-50">
                  {closedTrades.map((t, i) => {
                    const oc = OUTCOME_LABELS[t.outcome] || { label: t.outcome, color: "bg-slate-100 text-slate-500" };
                    return (
                      <tr key={i} className="hover:bg-slate-50 transition-colors">
                        <td className="px-6 py-3 font-semibold text-slate-800">{t.stock}</td>
                        <td className="px-6 py-3"><HorizonBadge horizon={t.horizon} /></td>
                        <td className="px-6 py-3 text-slate-500">{t.date}</td>
                        <td className="px-6 py-3">
                          <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${oc.color}`}>{oc.label}</span>
                        </td>
                        <td className="px-6 py-3 text-right"><PnlBadge pnl={t.pnl} /></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )
        )}
      </div>
    </div>
  );
}
