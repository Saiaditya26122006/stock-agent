import { useEffect, useState, useRef } from "react";
import client from "../api/client";
import RecommendationCard from "../components/RecommendationCard";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip,
  ResponsiveContainer, PieChart, Pie, Cell,
} from "recharts";
import { Play, TrendingUp, TrendingDown, Zap, Server, Activity, PieChart as PieChartIcon, BarChart2, Clock, LayoutList, XCircle } from "lucide-react";

const HORIZON_TABS = [
  { key: "all",        label: "All",        icon: LayoutList },
  { key: "SHORT_TERM", label: "Short-Term", icon: Clock },
  { key: "LONG_TERM",  label: "Long-Term",  icon: TrendingUp },
  { key: "skipped",    label: "Skipped",    icon: XCircle },
];

const COLORS = ["#6366f1", "#10b981", "#f43f5e", "#f59e0b", "#06b6d4", "#8b5cf6", "#ec4899"];

export default function Dashboard() {
  const [recs, setRecs] = useState([]);
  const [summary, setSummary] = useState({ total: 0, win_rate: 0, wins: 0, losses: 0 });
  const [sectors, setSectors] = useState([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [countdown, setCountdown] = useState(0);
  const [error, setError] = useState("");
  const [runError, setRunError] = useState("");
  const [activeTab, setActiveTab] = useState("all");
  const pollIntervalRef = useRef(null);
  const countdownTimerRef = useRef(null);

  useEffect(() => {
    return () => {
      clearInterval(pollIntervalRef.current);
      clearInterval(countdownTimerRef.current);
    };
  }, []);

  const refreshData = async () => {
    try {
      const [todayResp, winrateResp, sectorResp] = await Promise.all([
        client.get("/recommendations/today"),
        client.get("/recommendations/winrate"),
        client.get("/watchlist/by-sector"),
      ]);
      setRecs(todayResp.data.recommendations || []);
      setSummary({
        total: todayResp.data.count || 0,
        win_rate: winrateResp.data.win_rate || 0,
        wins: winrateResp.data.wins || 0,
        losses: winrateResp.data.losses || 0,
      });
      const sectorMap = sectorResp.data || {};
      const formattedSectors = Object.keys(sectorMap)
        .filter((k) => k !== "count" && k !== "total_sectors")
        .map((key) => ({ name: key, value: sectorMap[key].length }));
      setSectors(formattedSectors.sort((a, b) => b.value - a.value));
    } catch {
      // silently ignore refresh failures
    }
  };

  useEffect(() => {
    let isMounted = true;
    const controller = new AbortController();

    const fetchInitial = async () => {
      setLoading(true);
      setError("");
      try {
        const [todayResp, winrateResp, sectorResp] = await Promise.all([
          client.get("/recommendations/today", { signal: controller.signal }),
          client.get("/recommendations/winrate", { signal: controller.signal }),
          client.get("/watchlist/by-sector", { signal: controller.signal }),
        ]);
        if (isMounted) {
          setRecs(todayResp.data.recommendations || []);
          setSummary({
            total: todayResp.data.count || 0,
            win_rate: winrateResp.data.win_rate || 0,
            wins: winrateResp.data.wins || 0,
            losses: winrateResp.data.losses || 0,
          });
          const sectorMap = sectorResp.data || {};
          const formattedSectors = Object.keys(sectorMap)
            .filter((k) => k !== "count" && k !== "total_sectors")
            .map((key) => ({ name: key, value: sectorMap[key].length }));
          setSectors(formattedSectors.sort((a, b) => b.value - a.value));
        }
      } catch (err) {
        if (err?.code === "ERR_CANCELED") return;
        if (isMounted) {
          if (err?.response?.status === 404) {
            setRecs([]);
          } else {
            setError(err?.response?.data?.detail || "Failed to fetch dashboard data.");
          }
        }
      } finally {
        if (isMounted) setLoading(false);
      }
    };

    fetchInitial();
    return () => {
      isMounted = false;
      controller.abort();
    };
  }, []);

  const runAnalysisNow = async () => {
    clearInterval(pollIntervalRef.current);
    clearInterval(countdownTimerRef.current);
    setRunning(true);
    setLoading(false);
    setRunError("");
    setError("");

    const FALLBACK_COUNT = 40;
    let secs = FALLBACK_COUNT * 7;
    setCountdown(secs);

    countdownTimerRef.current = setInterval(() => {
      secs -= 1;
      setCountdown(secs);
      if (secs <= 0) clearInterval(countdownTimerRef.current);
    }, 1000);

    client.post("/scheduler/trigger-morning").catch(() => {});

    let pollAttempts = 0;
    const maxPollAttempts = 30;

    pollIntervalRef.current = setInterval(async () => {
      pollAttempts += 1;
      try {
        const res = await client.get("/recommendations/today");
        const recData = res.data.recommendations || [];
        if (recData.length > 0 || pollAttempts >= maxPollAttempts) {
          clearInterval(pollIntervalRef.current);
          clearInterval(countdownTimerRef.current);
          setRunning(false);
          setCountdown(0);
          refreshData();
        }
      } catch {
        // ignore poll errors
      }
    }, 20000);
  };

  // Real performance data from API — wins vs losses (last 20 trades)
  const performanceData = [
    { name: "Wins", value: summary.wins, fill: "#10b981" },
    { name: "Losses", value: summary.losses, fill: "#f43f5e" },
    { name: "Open", value: Math.max(0, summary.total - summary.wins - summary.losses), fill: "#6366f1" },
  ].filter((d) => d.value > 0);

  return (
    <div className="space-y-8 animate-in fade-in duration-500">

      {/* Top Header & Trigger Action */}
      <div className="flex flex-col gap-6 md:flex-row md:items-center md:justify-between rounded-3xl bg-white p-8 shadow-sm border border-slate-200">
        <div className="space-y-2">
          <h2 className="text-3xl font-extrabold text-slate-800 tracking-tight flex items-center gap-2">
            Intelligence Overview <Zap size={28} className="text-indigo-500" />
          </h2>
          <p className="text-slate-500 font-medium">Your automated trading agent performance &amp; daily signals.</p>
        </div>

        <button
          onClick={runAnalysisNow}
          disabled={running}
          className="relative overflow-hidden group rounded-2xl bg-gradient-to-tr from-indigo-600 to-violet-500 px-6 py-4 text-sm font-bold text-white transition-all hover:scale-105 hover:shadow-lg hover:shadow-indigo-200 disabled:cursor-not-allowed disabled:opacity-70 disabled:hover:scale-100 flex items-center justify-center gap-3"
        >
          <div className="absolute inset-0 bg-white/20 transition-transform group-hover:translate-x-full translate-x-[-100%]" />
          {running ? (
            <>
              <Activity size={20} className="animate-pulse" />
              Scanning Matrix ({Math.floor(countdown / 60)}m {countdown % 60}s)
            </>
          ) : (
            <>
              <Play size={20} fill="currentColor" />
              Run Deep Analysis
            </>
          )}
        </button>
      </div>

      {runError && (
        <div className="rounded-xl border border-rose-500/30 bg-rose-50 p-4 text-sm text-rose-700 font-medium">
          {runError}
        </div>
      )}

      {running && (
        <div className="rounded-xl border border-indigo-200 bg-indigo-50 p-4 text-sm text-indigo-800 font-bold flex items-center gap-3">
          <Server className="animate-bounce" size={20} />
          {countdown > 0
            ? "Deep Analysing stocks... High compute resources allocated."
            : "Agent is finalizing report... Hold on."}
        </div>
      )}

      {error && (
        <div className="rounded-xl border border-rose-500/30 bg-rose-50 p-4 text-sm text-rose-700 font-medium">
          {error}
        </div>
      )}

      {/* KPI Stats Row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="bg-white rounded-2xl p-6 border border-slate-200 shadow-sm">
          <div className="text-slate-400 font-semibold mb-1 text-sm uppercase tracking-wider">Today&apos;s Recs</div>
          <div className="text-3xl font-black text-slate-800">{summary.total}</div>
        </div>
        <div className="bg-white rounded-2xl p-6 border border-slate-200 shadow-sm relative overflow-hidden">
          <div className="absolute right-0 top-0 w-24 h-24 bg-emerald-50 rounded-bl-full pointer-events-none" />
          <div className="text-slate-400 font-semibold mb-1 text-sm uppercase tracking-wider">Win Rate</div>
          <div className="text-3xl font-black text-emerald-600 flex items-baseline gap-1">
            {summary.win_rate}%
            <TrendingUp size={24} className="text-emerald-500 translate-y-1" />
          </div>
        </div>
        <div className="bg-white rounded-2xl p-6 border border-slate-200 shadow-sm">
          <div className="text-slate-400 font-semibold mb-1 text-sm uppercase tracking-wider">Total Wins</div>
          <div className="text-3xl font-black text-slate-800">{summary.wins}</div>
        </div>
        <div className="bg-white rounded-2xl p-6 border border-slate-200 shadow-sm">
          <div className="text-slate-400 font-semibold mb-1 text-sm uppercase tracking-wider">Total Losses</div>
          <div className="text-3xl font-black text-rose-600 flex items-baseline gap-1">
            {summary.losses}
            <TrendingDown size={24} className="text-rose-500 translate-y-1" />
          </div>
        </div>
      </div>

      {/* Charts Row */}
      <div className="grid md:grid-cols-2 gap-6">
        <div className="bg-white rounded-3xl p-6 border border-slate-200 shadow-sm">
          <h3 className="text-lg font-bold text-slate-800 mb-6 flex items-center gap-2">
            <PieChartIcon size={20} className="text-indigo-500" /> Watchlist Sector Exposure
          </h3>
          <div className="h-64">
            {sectors.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={sectors}
                    cx="50%"
                    cy="50%"
                    innerRadius={60}
                    outerRadius={80}
                    paddingAngle={5}
                    dataKey="value"
                  >
                    {sectors.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                    ))}
                  </Pie>
                  <RechartsTooltip
                    contentStyle={{ borderRadius: "12px", border: "none", boxShadow: "0 4px 6px -1px rgb(0 0 0 / 0.1)" }}
                  />
                </PieChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-full flex items-center justify-center text-slate-400 font-medium">Scanning metadata...</div>
            )}
          </div>
        </div>

        <div className="bg-white rounded-3xl p-6 border border-slate-200 shadow-sm">
          <h3 className="text-lg font-bold text-slate-800 mb-6 flex items-center gap-2">
            <BarChart2 size={20} className="text-emerald-500" /> Trade Outcomes (Last 20)
          </h3>
          <div className="h-64">
            {performanceData.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={performanceData} barCategoryGap="30%">
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f1f5f9" />
                  <XAxis dataKey="name" axisLine={false} tickLine={false} tick={{ fill: "#94a3b8" }} />
                  <YAxis axisLine={false} tickLine={false} tick={{ fill: "#94a3b8" }} allowDecimals={false} />
                  <RechartsTooltip
                    contentStyle={{ borderRadius: "12px", border: "none", boxShadow: "0 4px 6px -1px rgb(0 0 0 / 0.1)" }}
                  />
                  <Bar dataKey="value" radius={[6, 6, 0, 0]}>
                    {performanceData.map((entry, index) => (
                      <Cell key={`bar-${index}`} fill={entry.fill} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-full flex items-center justify-center text-slate-400 font-medium">
                No closed trades yet — run analysis to populate.
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Recs Listing with horizon tabs */}
      <div className="bg-slate-100/50 -mx-4 px-4 py-8 rounded-t-[3rem]">
        <div className="max-w-7xl mx-auto">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-6 px-2">
            <h3 className="text-2xl font-extrabold text-slate-800">Actionable Signals</h3>

            {/* Horizon tab pills */}
            <div className="flex gap-2 flex-wrap">
              {HORIZON_TABS.map(({ key, label, icon: Icon }) => {
                const count =
                  key === "all"     ? recs.filter(r => r.action !== "SKIP").length
                  : key === "skipped" ? recs.filter(r => r.action === "SKIP").length
                  : recs.filter(r => r.horizon === key && r.action !== "SKIP").length;
                const active = activeTab === key;
                return (
                  <button
                    key={key}
                    onClick={() => setActiveTab(key)}
                    className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-sm font-semibold transition-all ${
                      active
                        ? key === "SHORT_TERM" ? "bg-amber-500 text-white"
                          : key === "LONG_TERM"  ? "bg-indigo-600 text-white"
                          : key === "skipped"    ? "bg-slate-500 text-white"
                          : "bg-slate-800 text-white"
                        : "bg-white border border-slate-200 text-slate-600 hover:border-slate-400"
                    }`}
                  >
                    <Icon size={14} />
                    {label}
                    <span className={`ml-0.5 text-xs px-1.5 py-0.5 rounded-full ${active ? "bg-white/25" : "bg-slate-100 text-slate-500"}`}>
                      {count}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          {loading ? (
            <div className="rounded-3xl border border-white bg-white/50 backdrop-blur p-12 flex justify-center text-indigo-500">
              <Activity className="animate-spin" size={32} />
            </div>
          ) : activeTab === "skipped" ? (
            /* Skipped stocks — plain-English explainer */
            (() => {
              const skipped = recs.filter(r => r.action === "SKIP");
              return skipped.length === 0 ? (
                <div className="rounded-3xl border border-dashed border-slate-300 bg-white/50 p-12 text-center text-slate-500 font-medium">
                  No stocks were skipped today — the agent found clean setups for all analysed stocks.
                </div>
              ) : (
                <div className="grid gap-4 md:grid-cols-2">
                  {skipped.map((rec) => (
                    <div key={rec.id || rec.stock} className="bg-white rounded-2xl border border-slate-200 p-5 shadow-sm">
                      <div className="flex items-center justify-between mb-2">
                        <span className="font-bold text-slate-800 text-base">{rec.stock || rec.symbol}</span>
                        <span className="text-xs bg-slate-100 text-slate-500 font-semibold px-2 py-0.5 rounded-full">SKIPPED</span>
                      </div>
                      <p className="text-sm text-slate-600 leading-relaxed">
                        {rec.reasoning || "No clear entry signal — conflicting indicators or low volume. The agent chose to wait for a better setup."}
                      </p>
                    </div>
                  ))}
                </div>
              );
            })()
          ) : (
            (() => {
              const filtered = activeTab === "all"
                ? recs.filter(r => r.action !== "SKIP")
                : recs.filter(r => r.horizon === activeTab && r.action !== "SKIP");

              if (filtered.length === 0 && !running && !error) {
                const emptyMsg = activeTab === "SHORT_TERM"
                  ? "No short-term trades today — the agent found no high-probability intraday or swing setups."
                  : activeTab === "LONG_TERM"
                  ? "No long-term entries today — wait for better accumulation zones or run a fresh scan."
                  : "No recommendations generated today. Run analysis or wait for the morning scan.";
                return (
                  <div className="rounded-3xl border border-dashed border-slate-300 bg-white/50 p-12 text-center text-slate-500 font-medium">
                    {emptyMsg}
                  </div>
                );
              }

              return (
                <>
                  {activeTab === "SHORT_TERM" && (
                    <div className="mb-4 rounded-xl bg-amber-50 border border-amber-200 px-4 py-3 text-sm text-amber-800 font-medium">
                      ⚡ Short-term trades — hold for 1 day to 1 week. Exit immediately if stop-loss is hit. Watch for the exit trigger.
                    </div>
                  )}
                  {activeTab === "LONG_TERM" && (
                    <div className="mb-4 rounded-xl bg-indigo-50 border border-indigo-200 px-4 py-3 text-sm text-indigo-800 font-medium">
                      📈 Long-term investments — accumulate below the entry price, target 6–12 months. Use monthly closing price for stop-loss decisions.
                    </div>
                  )}
                  <div className="grid gap-6 md:grid-cols-2">
                    {filtered.map((rec) => (
                      <RecommendationCard key={rec.id || `${rec.stock}-${rec.created_at}`} rec={rec} />
                    ))}
                  </div>
                </>
              );
            })()
          )}
        </div>
      </div>
    </div>
  );
}
