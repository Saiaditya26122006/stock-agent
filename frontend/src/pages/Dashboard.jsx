import { useEffect, useState, useRef } from "react";
import axios from "axios";
import RecommendationCard from "../components/RecommendationCard";
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip, ResponsiveContainer, PieChart, Pie, Cell } from 'recharts';
import { Play, TrendingUp, TrendingDown, Target, Zap, Server, Activity, PieChart as PieChartIcon } from "lucide-react";

const API_URL = "http://localhost:8000";

const COLORS = ['#6366f1', '#10b981', '#f43f5e', '#f59e0b', '#06b6d4', '#8b5cf6', '#ec4899'];

export default function Dashboard() {
  const [recs, setRecs] = useState([]);
  const [summary, setSummary] = useState({ total: 0, win_rate: 0, wins: 0, losses: 0 });
  const [sectors, setSectors] = useState([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [countdown, setCountdown] = useState(0);
  const [error, setError] = useState("");
  const [runError, setRunError] = useState("");
  const [stockCount, setStockCount] = useState(40);
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
        axios.get(`${API_URL}/recommendations/today`),
        axios.get(`${API_URL}/recommendations/winrate`),
        axios.get(`${API_URL}/watchlist/by-sector`),
      ]);
      setRecs(todayResp.data.recommendations || []);
      setSummary({
        total: todayResp.data.count || 0,
        win_rate: winrateResp.data.win_rate || 0,
        wins: winrateResp.data.wins || 0,
        losses: winrateResp.data.losses || 0,
      });
      // Format sectors
      const sectorMap = sectorResp.data || {};
      const formattedSectors = Object.keys(sectorMap).filter(k => k !== 'count' && k !== 'total_sectors').map((key) => ({
        name: key,
        value: sectorMap[key].length
      }));
      setSectors(formattedSectors.sort((a,b) => b.value - a.value));
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
          axios.get(`${API_URL}/recommendations/today`, { signal: controller.signal }),
          axios.get(`${API_URL}/recommendations/winrate`, { signal: controller.signal }),
          axios.get(`${API_URL}/watchlist/by-sector`, { signal: controller.signal }),
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
          const formattedSectors = Object.keys(sectorMap).filter(k => k !== 'count' && k !== 'total_sectors').map((key) => ({
            name: key,
            value: sectorMap[key].length
          }));
          setSectors(formattedSectors.sort((a,b) => b.value - a.value));
        }
      } catch (err) {
        if (axios.isCancel(err)) return;
        if (isMounted) {
          if (err?.response?.status === 404) {
            setRecs([]);
          } else {
            setError(err?.response?.data?.detail || "Failed to fetch dashboard data.");
          }
        }
      } finally {
        if (isMounted) {
          setLoading(false);
        }
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
    setStockCount(FALLBACK_COUNT);
    let secs = FALLBACK_COUNT * 7;
    setCountdown(secs);

    countdownTimerRef.current = setInterval(() => {
      secs -= 1;
      setCountdown(secs);
      if (secs <= 0) {
        clearInterval(countdownTimerRef.current);
      }
    }, 1000);

    axios.post(`${API_URL}/scheduler/trigger-morning`).catch(() => {});

    let pollAttempts = 0;
    const maxPollAttempts = 30;

    pollIntervalRef.current = setInterval(async () => {
      pollAttempts += 1;
      try {
        const res = await axios.get(`${API_URL}/recommendations/today`);
        const recData = res.data.recommendations || [];
        if (recData.length > 0) {
          clearInterval(pollIntervalRef.current);
          clearInterval(countdownTimerRef.current);
          setRunning(false);
          setCountdown(0);
          refreshData();
          return;
        }
        if (pollAttempts >= maxPollAttempts) {
          clearInterval(pollIntervalRef.current);
          clearInterval(countdownTimerRef.current);
          setRunning(false);
          setCountdown(0);
          refreshData();
        }
      } catch {
      }
    }, 20000);
  };
  
  // Mock performance data for visual appeal
  const performanceData = [
    { day: 'Mon', value: 1200 },
    { day: 'Tue', value: 1800 },
    { day: 'Wed', value: 1500 },
    { day: 'Thu', value: 2400 },
    { day: 'Fri', value: Math.max(3000, 3000 * (summary.win_rate/100)) }
  ];

  return (
    <div className="space-y-8 animate-in fade-in duration-500">
      
      {/* Top Header & Trigger Action */}
      <div className="flex flex-col gap-6 md:flex-row md:items-center md:justify-between rounded-3xl bg-white p-8 shadow-sm border border-slate-200">
        <div className="space-y-2">
          <h2 className="text-3xl font-extrabold text-slate-800 tracking-tight flex items-center gap-2">
            Intelligence Overview <Zap size={28} className="text-indigo-500" />
          </h2>
          <p className="text-slate-500 font-medium">Your automated trading agent performance & daily signals.</p>
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
            ? `Deep Analysing stocks... High compute resources allocated.`
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
          <div className="text-slate-400 font-semibold mb-1 text-sm uppercase tracking-wider">Today's Recs</div>
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
                    contentStyle={{ borderRadius: '12px', border: 'none', boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)' }} 
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
            <Target size={20} className="text-emerald-500" /> Simulated Performance Trajectory
          </h3>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={performanceData}>
                <defs>
                  <linearGradient id="colorValue" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#6366f1" stopOpacity={0.3}/>
                    <stop offset="95%" stopColor="#6366f1" stopOpacity={0}/>
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f1f5f9" />
                <XAxis dataKey="day" axisLine={false} tickLine={false} tick={{fill: '#94a3b8'}} />
                <YAxis axisLine={false} tickLine={false} tick={{fill: '#94a3b8'}} />
                <RechartsTooltip 
                  contentStyle={{ borderRadius: '12px', border: 'none', boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)' }}
                />
                <Area type="monotone" dataKey="value" stroke="#4f46e5" strokeWidth={3} fillOpacity={1} fill="url(#colorValue)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* Recs Listing */}
      <div className="bg-slate-100/50 -mx-4 px-4 py-8 rounded-t-[3rem]">
        <div className="max-w-7xl mx-auto">
          <h3 className="text-2xl font-extrabold text-slate-800 mb-6 px-2">Actionable Signals</h3>
          {loading ? (
            <div className="rounded-3xl border border-white bg-white/50 backdrop-blur p-12 flex justify-center text-indigo-500">
               <Activity className="animate-spin" size={32} />
            </div>
          ) : recs.length === 0 && !running && !error ? (
            <div className="rounded-3xl border border-dashed border-slate-300 bg-white/50 p-12 text-center text-slate-500 font-medium">
              No recommendations generated today. The agent requires fresh scanning or the market may not present viable setups.
            </div>
          ) : recs.length > 0 ? (
            <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-2">
              {recs.map((rec) => (
                <RecommendationCard key={rec.id || `${rec.stock}-${rec.created_at}`} rec={rec} />
              ))}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
