import { useEffect, useState } from "react";
import client from "../api/client";
import LoadingSpinner from "../components/LoadingSpinner";

export default function Portfolio() {
  const [status, setStatus] = useState({ running: false, jobs: [] });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    const fetchStatus = async () => {
      setLoading(true);
      try {
        const { data } = await client.get("/scheduler/status");
        setStatus(data);
      } catch (err) {
        setError(err?.response?.data?.detail || "Failed to fetch scheduler status.");
      } finally {
        setLoading(false);
      }
    };
    fetchStatus();
  }, []);

  return (
    <section className="space-y-6">
      <div className="rounded-xl border border-slate-700 bg-slate-800 p-6">
        <h2 className="text-lg font-semibold text-white">Portfolio Tracker</h2>
        <p className="mt-2 text-slate-300">Open Positions tracking coming in Phase 4</p>
      </div>

      <div className="rounded-xl border border-slate-700 bg-slate-800 p-6">
        <h3 className="text-base font-semibold text-white">Scheduler Status</h3>
        <p className="mt-2 text-sm text-slate-300">
          Running: <span className={status.running ? "text-emerald-300" : "text-rose-300"}>{String(status.running)}</span>
        </p>
        {error && <p className="mt-3 text-sm text-rose-300">{error}</p>}
        {loading ? (
          <div className="mt-4">
            <LoadingSpinner label="Loading scheduler jobs..." />
          </div>
        ) : (
          <div className="mt-4 overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <thead className="bg-slate-900 text-slate-300">
                <tr>
                  <th className="px-4 py-3">Job</th>
                  <th className="px-4 py-3">Trigger</th>
                  <th className="px-4 py-3">Next Run</th>
                </tr>
              </thead>
              <tbody>
                {(status.jobs || []).map((job) => (
                  <tr key={job.id} className="border-t border-slate-700 text-slate-200">
                    <td className="px-4 py-3">{job.id}</td>
                    <td className="px-4 py-3">{job.trigger}</td>
                    <td className="px-4 py-3">{job.next_run_time || "-"}</td>
                  </tr>
                ))}
                {(status.jobs || []).length === 0 && (
                  <tr>
                    <td colSpan={3} className="px-4 py-4 text-center text-slate-400">
                      No jobs found.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
}
