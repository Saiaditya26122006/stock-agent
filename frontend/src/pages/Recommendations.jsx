import { useEffect, useState } from "react";
import client from "../api/client";
import LoadingSpinner from "../components/LoadingSpinner";
import RecommendationCard from "../components/RecommendationCard";

export default function Recommendations() {
  const [recs, setRecs] = useState([]);
  const [summary, setSummary] = useState({ total: 0, win_rate: 0, wins: 0, losses: 0 });
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [countdown, setCountdown] = useState(0);
  const [error, setError] = useState("");
  const [runError, setRunError] = useState("");

  const loadData = async () => {
    setLoading(true);
    setError("");
    try {
      const [todayResp, winrateResp] = await Promise.all([
        client.get("/recommendations/today"),
        client.get("/recommendations/winrate"),
      ]);
      setRecs(todayResp.data.recommendations || []);
      setSummary({
        total: todayResp.data.count || 0,
        win_rate: winrateResp.data.win_rate || 0,
        wins: winrateResp.data.wins || 0,
        losses: winrateResp.data.losses || 0,
      });
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to fetch recommendations.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const runAnalysisNow = async () => {
    setRunning(true);
    setRunError("");
    setCountdown(120);
    client.post("/scheduler/trigger-morning").catch(() => {});
    let secs = 120;
    const timer = setInterval(() => {
      secs -= 1;
      setCountdown(secs);
      if (secs <= 0) {
        clearInterval(timer);
        setRunning(false);
        setCountdown(0);
        loadData();
      }
    }, 1000);
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
          {running ? `Analysing... (${countdown}s)` : "Run Analysis Now"}
        </button>
      </div>

      {runError && (
        <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 p-3 text-sm text-rose-300">
          {runError}
        </div>
      )}

      {running && (
        <div className="rounded-lg border border-cyan-500/30 bg-cyan-500/10 p-3 text-sm text-cyan-300">
          Analysis running — fetching data for all watchlist stocks. Refreshing in {countdown}s...
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
      ) : recs.length === 0 ? (
        <div className="rounded-xl border border-slate-700 bg-slate-800 p-8 text-center text-slate-300">
          No recommendations today yet. Run analysis to generate fresh ideas.
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {recs.map((rec) => (
            <RecommendationCard key={rec.id || `${rec.stock}-${rec.created_at}`} rec={rec} />
          ))}
        </div>
      )}
    </section>
  );
}