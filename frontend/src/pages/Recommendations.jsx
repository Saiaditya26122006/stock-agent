import { useEffect, useState, useRef } from "react";
import axios from "axios";
import client from "../api/client";
import LoadingSpinner from "../components/LoadingSpinner";
import RecommendationCard from "../components/RecommendationCard";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

export default function Recommendations() {
  const [recs, setRecs] = useState([]);
  const [summary, setSummary] = useState({ total: 0, win_rate: 0, wins: 0, losses: 0 });
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
      const [todayResp, winrateResp] = await Promise.all([
        axios.get(`${API_URL}/recommendations/today`),
        axios.get(`${API_URL}/recommendations/winrate`),
      ]);
      setRecs(todayResp.data.recommendations || []);
      setSummary({
        total: todayResp.data.count || 0,
        win_rate: winrateResp.data.win_rate || 0,
        wins: winrateResp.data.wins || 0,
        losses: winrateResp.data.losses || 0,
      });
    } catch {
      // silently ignore refresh failures — data already loaded
    }
  };

  useEffect(() => {
    let isMounted = true;
    const controller = new AbortController();

    const fetchInitial = async () => {
      setLoading(true);
      setError("");
      try {
        const [todayResp, winrateResp] = await Promise.all([
          client.get("/recommendations/today", { signal: controller.signal }),
          client.get("/recommendations/winrate", { signal: controller.signal }),
        ]);
        if (isMounted) {
          setRecs(todayResp.data.recommendations || []);
          setSummary({
            total: todayResp.data.count || 0,
            win_rate: winrateResp.data.win_rate || 0,
            wins: winrateResp.data.wins || 0,
            losses: winrateResp.data.losses || 0,
          });
        }
      } catch (err) {
        if (axios.isCancel(err)) return; // silently ignore canceled requests
        if (isMounted) {
          if (err?.response?.status === 404) {
            setRecs([]);
          } else {
            setError(err?.response?.data?.detail || "Failed to fetch recommendations.");
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

    // Start countdown immediately with fallback estimate (40 stocks × 7s)
    const FALLBACK_COUNT = 40;
    setStockCount(FALLBACK_COUNT);
    let secs = FALLBACK_COUNT * 7;
    setCountdown(secs);

    // Start the countdown timer right away — no more 0m 0s freeze
    countdownTimerRef.current = setInterval(() => {
      secs -= 1;
      setCountdown(secs);
      if (secs <= 0) {
        clearInterval(countdownTimerRef.current);
      }
    }, 1000);

    // Fire trigger immediately — don't await, let backend run independently
    client.post("/scheduler/trigger-morning").catch(() => {});

    // Fetch real watchlist count in background and adjust estimate
    client.get("/watchlist").then((wlRes) => {
      const wlData = wlRes.data;
      let count = FALLBACK_COUNT;
      if (wlData && typeof wlData.count === "number" && wlData.count > 0) {
        count = wlData.count;
      } else if (wlData && Array.isArray(wlData.symbols) && wlData.symbols.length > 0) {
        count = wlData.symbols.length;
      } else if (Array.isArray(wlData) && wlData.length > 0) {
        count = wlData.length;
      }
      if (count !== FALLBACK_COUNT) {
        setStockCount(count);
        // Only reset timer if we haven't already counted down too far
        const newSecs = count * 7;
        if (secs > 0 && newSecs > secs) {
          secs = newSecs;
          setCountdown(secs);
        }
      }
    }).catch(() => {
      // keep using fallback — timer already running
    });

    // Poll every 20s — show results the moment backend finishes
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
        // silently ignore poll failures
      }
    }, 20000);
  };

  return (
    <section className="space-y-6">
      <div className="flex flex-col gap-3 rounded-xl border border-slate-700 bg-slate-800 p-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="grid gap-1 text-sm text-slate-200 sm:grid-cols-2 sm:gap-x-8">
          <p>Total recommendations today: <span className="font-semibold text-white">{summary.total}</span></p>
          <p>Win rate: <span className="font-semibold text-cyan-300">{summary.win_rate}%</span></p>
          <p>Wins: <span className="font-semibold text-emerald-300">{summary.wins}</span></p>
          <p>Losses: <span className="font-semibold text-rose-300">{summary.losses}</span></p>
        </div>
        <button
          onClick={runAnalysisNow}
          disabled={running}
          className="rounded-md bg-cyan-500 px-4 py-2 text-sm font-medium text-slate-900 transition hover:bg-cyan-400 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {running
            ? `Analysing... (${Math.floor(countdown / 60)}m ${countdown % 60}s)`
            : "Run Analysis Now"}
        </button>
      </div>

      {runError && (
        <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 p-3 text-sm text-rose-300">
          {runError}
        </div>
      )}

      {running && (
        <div className="rounded-lg border border-cyan-500/30 bg-cyan-500/10 p-3 text-sm text-cyan-300">
          {countdown > 0
            ? `⏳ Analysing ${stockCount} stocks — est. ${Math.floor(countdown / 60)}m ${countdown % 60}s remaining`
            : "⏳ Pipeline still running — waiting for results..."}
        </div>
      )}

      {error && (
        <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 p-3 text-sm text-rose-300">
          {error}
        </div>
      )}

      {loading ? (
        <div className="rounded-xl border border-slate-700 bg-slate-800 p-6">
          <LoadingSpinner label="Loading recommendations..." />
        </div>
      ) : recs.length === 0 && !running && !error ? (
        <div className="rounded-xl border border-slate-700 bg-slate-800 p-8 text-center text-slate-300">
          No recommendations today yet. Run analysis to generate fresh ideas.
        </div>
      ) : recs.length > 0 ? (
        <div className="grid gap-4 md:grid-cols-2">
          {recs.map((rec) => (
            <RecommendationCard key={rec.id || `${rec.stock}-${rec.created_at}`} rec={rec} />
          ))}
        </div>
      ) : null}
    </section>
  );
}