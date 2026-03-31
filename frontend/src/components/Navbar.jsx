import { NavLink } from "react-router-dom";

const linkClass = ({ isActive }) =>
  `rounded-md px-3 py-2 text-sm font-medium transition ${
    isActive ? "bg-cyan-500 text-slate-900" : "text-slate-300 hover:bg-slate-700 hover:text-white"
  }`;

export default function Navbar() {
  return (
    <header className="border-b border-slate-700 bg-slate-900/90 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-4">
        <h1 className="text-lg font-semibold text-white">NSE/BSE Agent</h1>
        <nav className="flex items-center gap-2">
          <NavLink to="/watchlist" className={linkClass}>
            Watchlist
          </NavLink>
          <NavLink to="/recommendations" className={linkClass}>
            Recommendations
          </NavLink>
          <NavLink to="/portfolio" className={linkClass}>
            Portfolio
          </NavLink>
        </nav>
      </div>
    </header>
  );
}
