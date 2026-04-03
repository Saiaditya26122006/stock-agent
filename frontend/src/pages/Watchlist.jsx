import { useEffect, useState } from "react";
import client from "../api/client";
import LoadingSpinner from "../components/LoadingSpinner";

function Toast({ toast, onClose }) {
  if (!toast) return null;
  const tone = toast.type === "success" ? "bg-emerald-600/90" : "bg-rose-600/90";
  return (
    <div className={`fixed right-4 top-4 z-50 rounded-lg px-4 py-3 text-sm text-white shadow-lg ${tone}`}>
      <div className="flex items-center gap-3">
        <span>{toast.message}</span>
        <button className="rounded px-2 py-1 text-xs hover:bg-black/20" onClick={onClose}>
          Close
        </button>
      </div>
    </div>
  );
}

const SECTOR_COLORS = {
  "IT / Technology": "bg-blue-500",
  "Banking & Finance": "bg-green-500",
  "Crude Oil & Energy": "bg-orange-500",
  "Pharma & Healthcare": "bg-purple-500",
  "Auto & EV": "bg-yellow-500",
  "FMCG & Consumer": "bg-pink-500",
  "Metals & Mining": "bg-gray-500",
  "Infrastructure & Real Estate": "bg-teal-500",
  "Uncategorised": "bg-slate-500",
};

export default function Watchlist() {
  const [rows, setRows] = useState([]);
  const [sectorData, setSectorData] = useState({});
  const [expandedSectors, setExpandedSectors] = useState({});
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [form, setForm] = useState({ symbol: "", exchange: "NSE", sector: "Uncategorised" });
  const [toast, setToast] = useState(null);

  const fetchWatchlist = async () => {
    setLoading(true);
    try {
      const { data } = await client.get("/watchlist/by-sector");
      setSectorData(data); // grouped dict
      // also compute flat list for any operations that need it
      const flat = Object.values(data).flat();
      setRows(flat);
    } catch (error) {
      setToast({ type: "error", message: "Failed to fetch watchlist." });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchWatchlist();
  }, []);

  const addStock = async (e) => {
    e.preventDefault();
    if (!form.symbol.trim()) return;
    setSubmitting(true);
    try {
      await client.post("/watchlist/add", {
        symbol: form.symbol.trim().toUpperCase(),
        exchange: form.exchange,
        sector: form.sector,
      });
      setToast({ type: "success", message: "Stock added to watchlist." });
      setForm({ ...form, symbol: "" });
      await fetchWatchlist();
    } catch (error) {
      setToast({ type: "error", message: error?.response?.data?.detail || "Failed to add stock." });
    } finally {
      setSubmitting(false);
    }
  };

  const removeStock = async (symbol) => {
    setSubmitting(true);
    try {
      await client.post("/watchlist/remove", { symbol });
      setToast({ type: "success", message: `${symbol} removed from watchlist.` });
      await fetchWatchlist();
    } catch (error) {
      setToast({ type: "error", message: error?.response?.data?.detail || "Failed to remove stock." });
    } finally {
      setSubmitting(false);
    }
  };

  const toggleSector = (sectorName) => {
    setExpandedSectors((prev) => ({
      ...prev,
      [sectorName]: prev[sectorName] === false ? true : false,
    }));
  };

  return (
    <section className="space-y-6">
      <Toast toast={toast} onClose={() => setToast(null)} />

      <form onSubmit={addStock} className="grid gap-3 rounded-xl border border-slate-700 bg-slate-800 p-4 sm:grid-cols-5">
        <input
          value={form.symbol}
          onChange={(e) => setForm((prev) => ({ ...prev, symbol: e.target.value }))}
          placeholder="Symbol (e.g. RELIANCE)"
          className="rounded-md border border-slate-600 bg-slate-900 px-3 py-2 text-white outline-none focus:border-cyan-400 sm:col-span-2"
        />
        <select
          value={form.exchange}
          onChange={(e) => setForm((prev) => ({ ...prev, exchange: e.target.value }))}
          className="rounded-md border border-slate-600 bg-slate-900 px-3 py-2 text-white outline-none focus:border-cyan-400"
        >
          <option value="NSE">NSE</option>
          <option value="BSE">BSE</option>
        </select>
        <select
          value={form.sector}
          onChange={(e) => setForm((prev) => ({ ...prev, sector: e.target.value }))}
          className="rounded-md border border-slate-600 bg-slate-900 px-3 py-2 text-white outline-none focus:border-cyan-400"
        >
          <option value="Uncategorised">Uncategorised</option>
          <option value="IT / Technology">IT / Technology</option>
          <option value="Banking & Finance">Banking & Finance</option>
          <option value="Crude Oil & Energy">Crude Oil & Energy</option>
          <option value="Pharma & Healthcare">Pharma & Healthcare</option>
          <option value="Auto & EV">Auto & EV</option>
          <option value="FMCG & Consumer">FMCG & Consumer</option>
          <option value="Metals & Mining">Metals & Mining</option>
          <option value="Infrastructure & Real Estate">Infrastructure & Real Estate</option>
        </select>
        <button
          disabled={submitting}
          className="rounded-md bg-cyan-500 px-4 py-2 font-medium text-slate-900 transition hover:bg-cyan-400 disabled:opacity-50"
        >
          {submitting ? "Working..." : "Add"}
        </button>
      </form>

      <div className="space-y-4">
        {loading ? (
          <div className="rounded-xl border border-slate-700 bg-slate-800 p-6">
            <LoadingSpinner label="Fetching watchlist..." />
          </div>
        ) : Object.keys(sectorData).length === 0 || rows.length === 0 ? (
          <div className="rounded-xl border border-slate-700 bg-slate-800 p-8 text-center text-slate-400">
            No active watchlist stocks yet.
          </div>
        ) : (
          Object.entries(sectorData).map(([sectorName, stocks]) => {
            if (!stocks || stocks.length === 0) return null;
            const isExpanded = expandedSectors[sectorName] !== false;
            const badgeColor = SECTOR_COLORS[sectorName] || "bg-slate-500";
            
            return (
              <div key={sectorName} className="overflow-hidden rounded-xl border border-slate-700 bg-slate-800">
                <button
                  type="button"
                  onClick={() => toggleSector(sectorName)}
                  className="flex w-full items-center justify-between bg-slate-900/50 p-4 transition hover:bg-slate-700/50"
                >
                  <div className="flex items-center gap-3">
                    <span className={`h-3 w-3 rounded-full ${badgeColor}`} />
                    <h3 className="font-semibold text-slate-200">
                      {sectorName} <span className="ml-1 text-sm font-normal text-slate-400">({stocks.length})</span>
                    </h3>
                  </div>
                  <span className="text-slate-400">{isExpanded ? "▼" : "▶"}</span>
                </button>
                
                {isExpanded && (
                  <div className="overflow-x-auto">
                    <table className="min-w-full text-left text-sm">
                      <thead className="bg-slate-900/80 text-slate-400">
                        <tr>
                          <th className="px-4 py-3">Symbol</th>
                          <th className="px-4 py-3">Exchange</th>
                          <th className="px-4 py-3">Added Date</th>
                          <th className="px-4 py-3">Action</th>
                        </tr>
                      </thead>
                      <tbody>
                        {stocks.map((row) => (
                          <tr key={`${row.symbol}-${row.exchange}`} className="border-t border-slate-700/50 text-slate-200">
                            <td className="px-4 py-3 font-medium">
                              <div className="flex items-center gap-2">
                                {row.symbol}
                                <span className={`h-2 w-2 rounded-full ${badgeColor}`} title={sectorName} />
                              </div>
                            </td>
                            <td className="px-4 py-3">
                              <span className="rounded bg-slate-700 px-2 py-0.5 text-xs text-slate-300">
                                {row.exchange || "-"}
                              </span>
                            </td>
                            <td className="px-4 py-3 text-slate-400">
                              {row.created_at ? new Date(row.created_at).toLocaleString() : "-"}
                            </td>
                            <td className="px-4 py-3">
                              <button
                                disabled={submitting}
                                onClick={() => removeStock(row.symbol)}
                                className="rounded bg-rose-500/20 px-3 py-1 text-rose-300 transition hover:bg-rose-500/40 disabled:opacity-50"
                              >
                                Remove
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>
    </section>
  );
}
