import { NavLink } from "react-router-dom";
import { LayoutDashboard, List, Briefcase, Zap, Compass, Cpu } from "lucide-react";

export default function Navbar() {
  const linkClass = ({ isActive }) =>
    `flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-semibold transition-all duration-200 ${
      isActive 
        ? "bg-indigo-50 text-indigo-700 shadow-sm border border-indigo-100/50" 
        : "text-slate-500 hover:bg-slate-100/80 hover:text-slate-900"
    }`;

  return (
    <header className="sticky top-0 z-50 border-b border-indigo-100/50 bg-white/80 backdrop-blur-xl shadow-sm">
      <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-4">
        
        <div className="flex items-center gap-3">
          <div className="flex items-center justify-center w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-600 via-violet-600 to-purple-700 shadow-md">
            <Zap size={20} className="text-white drop-shadow-sm" fill="currentColor" />
          </div>
          <h1 className="text-xl font-extrabold text-slate-800 tracking-tight leading-none bg-clip-text text-transparent bg-gradient-to-r from-slate-800 to-slate-600">StockAgent</h1>
        </div>

        <nav className="flex items-center gap-1.5 p-1.5 bg-slate-50/80 rounded-2xl border border-slate-100">
          <NavLink to="/dashboard" className={linkClass}>
            <LayoutDashboard size={18} />
            <span className="hidden sm:inline">Dashboard</span>
          </NavLink>
          <NavLink to="/watchlist" className={linkClass}>
            <List size={18} />
            <span className="hidden sm:inline">Watchlist</span>
          </NavLink>
          <NavLink to="/discovery" className={linkClass}>
            <Compass size={18} />
            <span className="hidden sm:inline">Discovery</span>
          </NavLink>
          <NavLink to="/auto-discover" className={linkClass}>
            <Cpu size={18} />
            <span className="hidden sm:inline">Auto-Discover</span>
          </NavLink>
          <NavLink to="/portfolio" className={linkClass}>
            <Briefcase size={18} />
            <span className="hidden sm:inline">Portfolio</span>
          </NavLink>
        </nav>

      </div>
    </header>
  );
}
