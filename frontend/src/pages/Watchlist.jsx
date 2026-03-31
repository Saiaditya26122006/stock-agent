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

export default function Watchlist() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [form, setForm] = useState({ symbol: "", exchange: "NSE" });
  const [toast, setToast] = useState(null);

  const fetchWatchlist = async () => {
    setLoading(true);
    try {
      const { data } = await client.get("/watchlist");
      setRows(data.symbols || []);
    } catch (error) {
      setToast({ type: "error", message: error?.response?.data?.detail || "Failed to fetch watchlist." });
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

  return (
    <section className="space-y-6">
      <Toast toast={toast} onClose={() => setToast(null)} />

      <form onSubmit={addStock} className="grid gap-3 rounded-xl border border-slate-700 bg-slate-800 p-4 sm:grid-cols-4">
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
        <button
          disabled={submitting}
          className="rounded-md bg-cyan-500 px-4 py-2 font-medium text-slate-900 transition hover:bg-cyan-400 disabled:opacity-50"
        >
          {submitting ? "Working..." : "Add"}
        </button>
      </form>

      <div className="overflow-x-auto rounded-xl border border-slate-700 bg-slate-800">
        {loading ? (
          <div className="p-6">
            <LoadingSpinner label="Fetching watchlist..." />
          </div>
        ) : (
          <table className="min-w-full text-left text-sm">
            <thead className="bg-slate-900 text-slate-300">
              <tr>
                <th className="px-4 py-3">Symbol</th>
                <th className="px-4 py-3">Exchange</th>
                <th className="px-4 py-3">Added Date</th>
                <th className="px-4 py-3">Action</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={`${row.symbol}-${row.exchange}`} className="border-t border-slate-700 text-slate-200">
                  <td className="px-4 py-3 font-medium">{row.symbol}</td>
                  <td className="px-4 py-3">{row.exchange || "-"}</td>
                  <td className="px-4 py-3">{row.created_at ? new Date(row.created_at).toLocaleString() : "-"}</td>
                  <td className="px-4 py-3">
                    <button
                      disabled={submitting}
                      onClick={() => removeStock(row.symbol)}
                      className="rounded bg-rose-500/20 px-3 py-1 text-rose-300 hover:bg-rose-500/30 disabled:opacity-50"
                    >
                      Remove
                    </button>
                  </td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={4} className="px-4 py-6 text-center text-slate-400">
                    No active watchlist stocks yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
}
