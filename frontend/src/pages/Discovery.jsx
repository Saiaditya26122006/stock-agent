import { useState } from "react";
import client from "../api/client";
import LoadingSpinner from "../components/LoadingSpinner";
import RecommendationCard from "../components/RecommendationCard";

const SIGNAL_COLORS = {
  momentum: "bg-emerald-500/20 text-emerald-300 border-emerald-500/30",
  volume_spike: "bg-amber-500/20 text-amber-300 border-amber-500/30",
  near_52w_high: "bg-purple-500/20 text-purple-300 border-purple-500/30",
  fo_activity: "bg-blue-500/20 text-blue-300 border-blue-500/30",
};

const SIGNAL_LABELS = {
  momentum: "Momentum",
  volume_spike: "Vol Spike",
  near_52w_high: "52W High",
  fo_activity: "F&O Activity",
};

const REGIME_STYLES = {
  DANGER: "bg-red-500/20 text-red-300 border-red-500/40",
  CAUTION: "bg-amber-500/20 text-amber-300 border-amber-500/40",
  NORMAL: "bg-emerald-500/20 text-emerald-300 border-emerald-500/40",
};

export default function Discovery() {
  // --- Scan state ---
  const [scanData, setScanData] = useState(null);
  const [scanning, setScanning] = useState(false);
  const [scanError, setScanError] = useState("");

  // --- Selection state ---
  const [selected, setSelected] = useState(new Set());

  // --- Analysis state ---
  const [analysing, setAnalysing] = useState(false);
  const [analysisError, setAnalysisError] = useState("");
  const [analysisResults, setAnalysisResults] = useState(null);

  // ---- Scan handler ----
  const handleScan = async () => {
    setScanning(true);
    setScanError("");
    setScanData(null);
    setSelected(new Set());
    setAnalysisResults(null);
    setAnalysisError("");

    try {
      const res = await client.get("/discover-stocks", {
        timeout: 300_000, // 5 min — scan is slow
      });
      setScanData(res.data);
    } catch (err) {
      const msg =
        err?.response?.data?.detail ||
        err?.message ||
        "Scan failed. Check backend logs.";
      setScanError(msg);
    } finally {
      setScanning(false);
    }
  };

  // ---- Selection helpers ----
  const toggleSymbol = (symbol) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(symbol)) next.delete(symbol);
      else next.add(symbol);
      return next;
    });
  };

  const selectAll = () => {
    if (!scanData?.candidates) return;
    setSelected(new Set(scanData.candidates.map((c) => c.symbol)));
  };

  const clearAll = () => setSelected(new Set());

  // ---- Analyse handler ----
  const handleAnalyse = async () => {
    if (selected.size === 0 || selected.size > 10) return;

    setAnalysing(true);
    setAnalysisError("");
    setAnalysisResults(null);

    try {
      const res = await client.post(
        "/analyse-selected",
        { symbols: Array.from(selected) },
        { timeout: 300_000 }
      );
      setAnalysisResults(res.data);
    } catch (err) {
      const msg =
        err?.response?.data?.detail ||
        err?.message ||
        "Analysis failed. Check backend logs.";
      setAnalysisError(msg);
    } finally {
      setAnalysing(false);
    }
  };

  const candidates = scanData?.candidates || [];
  const selCount = selected.size;

  // Build recommendation cards from analysis results
  const recCards = [];
  if (analysisResults?.recommendations) {
    for (const [symbol, rec] of Object.entries(analysisResults.recommendations)) {
      recCards.push({ ...rec, stock: symbol, symbol });
    }
  }

  return (
    <section className="space-y-6">
      {/* ─── Title ─── */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-white">Stock Discovery</h2>
          <p className="mt-1 text-sm text-slate-400">
            Scan 100+ NSE stocks for momentum, volume, and F&O signals — then deep-analyse the best picks.
          </p>
        </div>
      </div>

      {/* ═══════════════ Section 1: Scan Summary Bar ═══════════════ */}
      <div className="flex flex-col gap-3 rounded-xl border border-slate-700 bg-slate-800 p-4 sm:flex-row sm:items-center sm:justify-between">
        {scanData ? (
          <div className="flex flex-wrap items-center gap-3 text-sm text-slate-200">
            <span>
              Scanned{" "}
              <span className="font-semibold text-white">{scanData.scanned_count}</span>{" "}
              stocks
            </span>
            <span className="text-slate-500">·</span>
            <span>
              <span className="font-semibold text-cyan-300">{scanData.candidates_count}</span>{" "}
              candidates found
            </span>
            <span className="text-slate-500">·</span>
            <span>
              VIX{" "}
              <span className="font-semibold text-white">{scanData.vix}</span>
            </span>
            <span
              className={`rounded-full border px-2.5 py-0.5 text-xs font-semibold ${
                REGIME_STYLES[scanData.regime] || REGIME_STYLES.NORMAL
              }`}
            >
              {scanData.regime}
            </span>
          </div>
        ) : (
          <p className="text-sm text-slate-400">
            No scan results yet. Click "Scan Now" to discover opportunities.
          </p>
        )}

        <button
          id="scan-now-btn"
          onClick={handleScan}
          disabled={scanning}
          className="flex items-center gap-2 rounded-md bg-cyan-500 px-5 py-2 text-sm font-medium text-slate-900 transition hover:bg-cyan-400 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {scanning && (
            <div className="h-4 w-4 animate-spin rounded-full border-2 border-slate-800 border-t-transparent" />
          )}
          {scanning ? "Scanning..." : "Scan Now"}
        </button>
      </div>

      {/* Scan error */}
      {scanError && (
        <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 p-3 text-sm text-rose-300">
          ⚠️ {scanError}
        </div>
      )}

      {/* Scanning spinner */}
      {scanning && (
        <div className="rounded-xl border border-cyan-500/20 bg-cyan-500/5 p-6">
          <LoadingSpinner label="Scanning 100+ stocks — this takes about 60-90 seconds..." />
        </div>
      )}

      {/* ═══════════════ Section 2: Candidates Table ═══════════════ */}
      {candidates.length > 0 && !scanning && (
        <div className="rounded-xl border border-slate-700 bg-slate-800 overflow-hidden">
          {/* Table toolbar */}
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-700 px-4 py-3">
            <div className="flex items-center gap-3">
              <button
                onClick={selectAll}
                className="rounded border border-slate-600 px-3 py-1.5 text-xs font-medium text-slate-300 transition hover:bg-slate-700"
              >
                Select All
              </button>
              <button
                onClick={clearAll}
                className="rounded border border-slate-600 px-3 py-1.5 text-xs font-medium text-slate-300 transition hover:bg-slate-700"
              >
                Clear All
              </button>
            </div>
            <span className="text-sm text-slate-400">
              <span className="font-semibold text-cyan-300">{selCount}</span> selected
              {selCount > 10 && (
                <span className="ml-2 text-rose-400 font-medium">
                  (max 10 — deselect some)
                </span>
              )}
            </span>
          </div>

          {/* Table */}
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-slate-700 bg-slate-800/60 text-xs uppercase tracking-wider text-slate-400">
                <tr>
                  <th className="px-4 py-3 w-10" />
                  <th className="px-4 py-3">Symbol</th>
                  <th className="px-4 py-3">Sector</th>
                  <th className="px-4 py-3 text-right">Price</th>
                  <th className="px-4 py-3 text-right">Change%</th>
                  <th className="px-4 py-3 text-right">Vol Ratio</th>
                  <th className="px-4 py-3">Signals</th>
                  <th className="px-4 py-3 text-center">Count</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-700/50">
                {candidates.map((c) => {
                  const isChecked = selected.has(c.symbol);
                  return (
                    <tr
                      key={c.symbol}
                      onClick={() => toggleSymbol(c.symbol)}
                      className={`cursor-pointer transition ${
                        isChecked
                          ? "bg-cyan-500/10"
                          : "hover:bg-slate-700/40"
                      }`}
                    >
                      <td className="px-4 py-3">
                        <input
                          type="checkbox"
                          checked={isChecked}
                          onChange={() => toggleSymbol(c.symbol)}
                          className="h-4 w-4 rounded border-slate-600 bg-slate-700 text-cyan-500 focus:ring-cyan-500 focus:ring-offset-0"
                        />
                      </td>
                      <td className="px-4 py-3 font-semibold text-white">
                        {c.symbol}
                      </td>
                      <td className="px-4 py-3 text-slate-300">{c.sector}</td>
                      <td className="px-4 py-3 text-right text-slate-200">
                        ₹{c.current_price?.toLocaleString("en-IN")}
                      </td>
                      <td
                        className={`px-4 py-3 text-right font-medium ${
                          c.price_change_pct > 0
                            ? "text-emerald-400"
                            : c.price_change_pct < 0
                            ? "text-rose-400"
                            : "text-slate-300"
                        }`}
                      >
                        {c.price_change_pct > 0 ? "+" : ""}
                        {c.price_change_pct?.toFixed(2)}%
                      </td>
                      <td className="px-4 py-3 text-right text-slate-200">
                        {c.volume_ratio?.toFixed(2)}x
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex flex-wrap gap-1.5">
                          {c.signals?.map((sig) => (
                            <span
                              key={sig}
                              className={`rounded-full border px-2 py-0.5 text-[11px] font-medium ${
                                SIGNAL_COLORS[sig] || "bg-slate-500/20 text-slate-300 border-slate-500/30"
                              }`}
                            >
                              {SIGNAL_LABELS[sig] || sig}
                            </span>
                          ))}
                        </div>
                      </td>
                      <td className="px-4 py-3 text-center">
                        <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-cyan-500/20 text-xs font-bold text-cyan-300">
                          {c.signal_count}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ═══════════════ Section 3: Analyse Button ═══════════════ */}
      {candidates.length > 0 && !scanning && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-4">
            <button
              id="analyse-selected-btn"
              onClick={handleAnalyse}
              disabled={selCount === 0 || selCount > 10 || analysing}
              className="rounded-md bg-indigo-500 px-6 py-2.5 text-sm font-semibold text-white transition hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {analysing
                ? `Analysing ${selCount} stocks...`
                : `Analyse Selected (${selCount})`}
            </button>

            {selCount > 10 && (
              <span className="text-sm text-rose-400 font-medium">
                ⚠️ Maximum 10 stocks per analysis — please deselect some.
              </span>
            )}
          </div>

          {/* Progress message */}
          {analysing && (
            <div className="rounded-lg border border-indigo-500/30 bg-indigo-500/10 p-4">
              <div className="flex items-center gap-3 text-sm text-indigo-300">
                <div className="h-4 w-4 animate-spin rounded-full border-2 border-indigo-400 border-t-transparent" />
                Running deep analysis on {selCount} stocks — this takes ~{selCount * 7}s
              </div>
            </div>
          )}

          {/* Analysis error */}
          {analysisError && (
            <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 p-3 text-sm text-rose-300">
              ⚠️ {analysisError}
            </div>
          )}

          {/* ─── Analysis results ─── */}
          {recCards.length > 0 && !analysing && (
            <div className="space-y-4">
              <h3 className="text-lg font-semibold text-white">
                Analysis Results
              </h3>
              <div className="grid gap-4 md:grid-cols-2">
                {recCards.map((rec) => (
                  <RecommendationCard
                    key={rec.symbol || rec.stock}
                    rec={rec}
                  />
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
