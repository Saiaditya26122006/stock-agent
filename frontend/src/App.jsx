import { Navigate, Route, Routes } from "react-router-dom";
import Navbar from "./components/Navbar";
import Portfolio from "./pages/Portfolio";
import Dashboard from "./pages/Dashboard";
import Watchlist from "./pages/Watchlist";
import Discovery from "./pages/Discovery";
import AutoDiscover from "./pages/AutoDiscover";

export default function App() {
  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 font-sans selection:bg-indigo-100 selection:text-indigo-900">
      <Navbar />
      <main className="mx-auto max-w-7xl px-4 py-8">
        <Routes>
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/recommendations" element={<Navigate to="/dashboard" replace />} />
          <Route path="/watchlist" element={<Watchlist />} />
          <Route path="/discovery" element={<Discovery />} />
          <Route path="/auto-discover" element={<AutoDiscover />} />
          <Route path="/portfolio" element={<Portfolio />} />
        </Routes>
      </main>
    </div>
  );
}
