import { useState } from "react";
import client from "../api/client";
import RecommendationCard from "../components/RecommendationCard";
import { Cpu, Clock, TrendingUp, Zap, Activity, ChevronRight } from "lucide-react";

function ScannerCard({ candidate }) {
  const signals = candidate.signals || [];
  const horizon = candidate.horizon || "SHORT_TERM";
  const horizonStyle = {
    SHORT_TERM: "bg-amber-100 text-amber-700",
    LONG_TERM:  "bg-indigo-100 text-indigo-700",
    BOTH:       "bg-emerald-100 text-emerald-700",
  }[horizon] || "bg-slate-100 text-slate-500";

  return (
    <div className="bg-white rounded-2xl border border-slate-200 p-4 shadow-sm">
      <div className="flex items-center justify-between mb-2">
        <span className="font-bold text-slate-800">{candidate.symbol}</span>
        <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${horizonStyle}`}>
          {horizon.replace("_", " ")}
        </span>
      </div>
      <div className="text-sm text-slate-500 mb-3">
        {candidate.sector} &middot; ₹{candidate.current_price}
        <span className={`ml-2 font-semibold ${candidate.price_change_pct >= 0 ? "text-emerald-600" : "text-rose-600"}`}>
          {candidate.price_change_pct >= 0 ? "+" : ""}{candidate.price_change_pct}%
        </span>
      </div>
      <div className="flex gap-1.5 flex-wrap mb-3">
        {signals.map((s) => (
          <span key={s} className="text-xs bg-slate-100 text-slate-600 px-2 py-0.5 rounded-full font-medium">
            {s.replace(/_/g, " ")}
          </span>
        ))}
      </div>
      <div className="flex gap-3 text-xs text-slate-500">
        <span>ST score: <strong className="text-slate-700">{candidate.short_term_score}</strong></span>
        <span>LT score: <strong className="text-slate-700">{candidate.long_term_score}</strong></span>
        <span>Signals: <strong className="text-slate-700">{candidate.signal_count}</strong></span>
      </div>
    </div>
  );
}

export default function AutoDiscover() {
  const [result, setResult] = useState(null);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState("");
  const [tab, setTab] = useState("short");

  const runDiscover = async () => {
    setScanning(true);
    setError("");
    setResult(null);
    try {
      const { data } = await client.get("/auto-discover", { timeout: 600_000 });
      setResult(data);
      setTab("short");
    } catch (err) {
      setError(
        err?.response?.data?.detail ||
        "Auto-discovery failed. The scan can take 5-10 minutes — please try again."
      );
    } finally {
      setScanning(false);
    }
  };

  const shortRecs  = result?.short_term  || [];
  const longRecs   = result?.long_term   || [];
  const candidates = result?.candidates  || { short_term: [], long_term: [] };

  return (
    <div className="space-y-8 animate-in fade-in duration-500">

      {/* Header */}
      <div className="rounded-3xl bg-white p-8 shadow-sm border border-slate-200">
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-6">
          <div>
            <h2 className="text-3xl font-extrabold text-slate-800 tracking-tight flex items-center gap-2">
              Auto-Discover <Cpu size={28} className="text-indigo-500" />
            </h2>
            <p className="text-slate-500 font-medium mt-1">
              The agent scans Nifty 500, scores every stock, and builds AI recommendations — no stock picking required.
            </p>
          </div>
          <button
            onClick={runDiscover}
            disabled={scanning}
            className="relative overflow-hidden group rounded-2xl bg-gradient-to-tr from-indigo-600 to-violet-500 px-6 py-4 text-sm font-bold text-white transition-all hover:scale-105 hover:shadow-lg hover:shadow-indigo-200 disabled:cursor-not-allowed disabled:opacity-70 disabled:hover:scale-100 flex items-center gap-3 shrink-0"
          >
            {scanning ? (
              <>
                <Activity size={20} className="animate-pulse" />
                Scanning Nifty 500…
              </>
            ) : (
              <>
                <Zap size={20} fill="currentColor" />
                Run Auto-Discovery
              </>
            )}
          </button>
        </div>

        {/* How it works */}
        <div className="mt-6 grid grid-cols-1 sm:grid-cols-3 gap-4 text-sm text-slate-600">
          {[
            { icon: Cpu,       label: "Step 1",  desc: "Screens all Nifty 500 stocks for momentum, volume spike, near-high and F&O activity" },
            { icon: Activity,  label: "Step 2",  desc: "Runs multi-timeframe confluence (15min / daily / weekly) and scores for Short-Term or Long-Term" },
            { icon: TrendingUp,label: "Step 3",  desc: "Gemini AI writes the trade plan — entry, target, stop-loss, thesis and exit triggers" },
          ].map(({ icon: Icon, label, desc }) => (
            <div key={label} className="flex gap-3 bg-slate-50 rounded-xl p-4 border border-slate-100">
              <Icon size={18} className="text-indigo-400 shrink-0 mt-0.5" />
              <div>
                <div className="font-semibold text-slate-700">{label}</div>
                <div className="text-slate-500 mt-0.5 leading-snug">{desc}</div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {scanning && (
        <div className="rounded-xl border border-indigo-200 bg-indigo-50 p-5 text-sm text-indigo-800 font-medium flex items-center gap-3">
          <Activity className="animate-spin shrink-0" size={20} />
          <div>
            <div className="font-bold">Full universe scan in progress</div>
            <div className="mt-0.5 font-normal text-indigo-600">
              Screening ~150 stocks → scoring → running AI synthesis. This takes 5-10 minutes.
            </div>
          </div>
        </div>
      )}

      {error && (
        <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700 font-medium">
          {error}
        </div>
      )}

      {result && (
        <>
          {/* Summary strip */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="bg-white rounded-2xl p-5 border border-slate-200 shadow-sm">
              <div className="text-slate-400 text-xs font-semibold uppercase tracking-wider mb-1">Screened</div>
              <div className="text-3xl font-black text-slate-800">{result.total_screened ?? "—"}</div>
            </div>
            <div className="bg-white rounded-2xl p-5 border border-slate-200 shadow-sm">
              <div className="text-slate-400 text-xs font-semibold uppercase tracking-wider mb-1">Qualified</div>
              <div className="text-3xl font-black text-slate-800">{result.total_qualified ?? "—"}</div>
            </div>
            <div className="bg-white rounded-2xl p-5 border border-slate-200 shadow-sm">
              <div className="text-slate-400 text-xs font-semibold uppercase tracking-wider mb-1">Short-Term Picks</div>
              <div className="text-3xl font-black text-amber-600">{shortRecs.length}</div>
            </div>
            <div className="bg-white rounded-2xl p-5 border border-slate-200 shadow-sm">
              <div className="text-slate-400 text-xs font-semibold uppercase tracking-wider mb-1">Long-Term Picks</div>
              <div className="text-3xl font-black text-indigo-600">{longRecs.length}</div>
            </div>
          </div>

          {/* Tab switcher */}
          <div className="flex gap-2 flex-wrap">
            {[
              { key: "short",      label: "Short-Term Trades",      icon: Clock,       count: shortRecs.length },
              { key: "long",       label: "Long-Term Investments",  icon: TrendingUp,  count: longRecs.length },
              { key: "candidates", label: "All Candidates",         icon: Cpu,         count: (candidates.short_term?.length || 0) + (candidates.long_term?.length || 0) },
            ].map(({ key, label, icon: Icon, count }) => (
              <button
                key={key}
                onClick={() => setTab(key)}
                className={`flex items-center gap-2 px-4 py-2 rounded-full text-sm font-semibold transition-all ${
                  tab === key
                    ? key === "short" ? "bg-amber-500 text-white"
                      : key === "long" ? "bg-indigo-600 text-white"
                      : "bg-slate-700 text-white"
                    : "bg-white border border-slate-200 text-slate-600 hover:border-slate-400"
                }`}
              >
                <Icon size={14} />
                {label}
                <span className={`text-xs px-1.5 py-0.5 rounded-full ${tab === key ? "bg-white/25" : "bg-slate-100 text-slate-500"}`}>
                  {count}
                </span>
              </button>
            ))}
          </div>

          {/* Content */}
          {tab === "short" && (
            <div>
              {shortRecs.length === 0 ? (
                <div className="rounded-3xl border border-dashed border-slate-300 bg-white/50 p-12 text-center text-slate-500 font-medium">
                  No short-term setups found in this scan — try again tomorrow or after market open.
                </div>
              ) : (
                <>
                  <div className="mb-4 rounded-xl bg-amber-50 border border-amber-200 px-4 py-3 text-sm text-amber-800 font-medium">
                    ⚡ These are agent-selected short-term trades. Exit if stop-loss is hit. Watch the exit trigger.
                  </div>
                  <div className="grid gap-6 md:grid-cols-2">
                    {shortRecs.map((rec) => (
                      <RecommendationCard key={rec.id || rec.stock} rec={rec} />
                    ))}
                  </div>
                </>
              )}
            </div>
          )}

          {tab === "long" && (
            <div>
              {longRecs.length === 0 ? (
                <div className="rounded-3xl border border-dashed border-slate-300 bg-white/50 p-12 text-center text-slate-500 font-medium">
                  No long-term investment candidates found. Check back after a market correction or sector dip.
                </div>
              ) : (
                <>
                  <div className="mb-4 rounded-xl bg-indigo-50 border border-indigo-200 px-4 py-3 text-sm text-indigo-800 font-medium">
                    📈 Long-term accumulation plays. Use the 6/12-month targets and exit only on monthly close below stop-loss.
                  </div>
                  <div className="grid gap-6 md:grid-cols-2">
                    {longRecs.map((rec) => (
                      <RecommendationCard key={rec.id || rec.stock} rec={rec} />
                    ))}
                  </div>
                </>
              )}
            </div>
          )}

          {tab === "candidates" && (
            <div>
              <p className="text-sm text-slate-500 mb-4">
                All stocks that passed the screener (≥2 signals) before AI synthesis.
              </p>
              <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
                {[...(candidates.short_term || []), ...(candidates.long_term || [])].map((c) => (
                  <ScannerCard key={c.symbol} candidate={c} />
                ))}
              </div>
            </div>
          )}
        </>
      )}

      {!result && !scanning && (
        <div className="rounded-3xl border border-dashed border-slate-300 bg-white/50 p-16 text-center">
          <Cpu size={48} className="mx-auto text-slate-300 mb-4" />
          <p className="text-slate-500 font-medium">
            Hit <strong>Run Auto-Discovery</strong> and the agent will autonomously find the best trades from the entire Nifty 500.
          </p>
        </div>
      )}
    </div>
  );
}
