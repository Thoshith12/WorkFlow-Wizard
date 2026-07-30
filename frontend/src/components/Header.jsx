import React, { useState, useEffect, useRef } from 'react';
import { useAuth } from '../context/AuthContext';

export default function Header() {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef(null);
  const { user, logout } = useAuth();

  useEffect(() => {
    function handleClickOutside(event) {
      if (menuRef.current && !menuRef.current.contains(event.target)) {
        setMenuOpen(false);
      }
    }
    document.addEventListener('click', handleClickOutside);
    return () => document.removeEventListener('click', handleClickOutside);
  }, []);

  const handleLogout = (e) => {
    if (e) {
      e.stopPropagation();
      e.preventDefault();
    }
    setMenuOpen(false);
    logout();
  };

  return (
    <header className="h-16 border-b border-outline-variant bg-surface-container-low/80 backdrop-blur flex items-center justify-between px-6 shrink-0 relative z-30">
      <div></div>
      <div className="flex items-center gap-4">
        <button className="text-on-surface-variant hover:text-primary transition-colors">
          <span className="material-symbols-outlined">notifications</span>
        </button>
        <div className="relative" ref={menuRef}>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              setMenuOpen(!menuOpen);
            }}
            className="w-8 h-8 rounded-full bg-surface-bright border border-outline flex items-center justify-center hover:border-primary transition-colors cursor-pointer"
          >
            <span className="material-symbols-outlined text-sm">person</span>
          </button>

          {menuOpen && (
            <div className="absolute right-0 mt-2 w-64 bg-surface-container-high border border-outline-variant rounded-lg shadow-xl py-1 z-50">
              <div className="px-4 py-2 border-b border-outline-variant">
                <p className="font-semibold text-on-surface text-sm break-all">{user || 'Admin'}</p>
                <p className="text-[10px] text-outline font-code-sm mt-0.5">System Authenticated</p>
              </div>
              <button
                type="button"
                onClick={handleLogout}
                className="w-full text-left px-4 py-2.5 text-error hover:bg-surface-variant transition-colors flex items-center gap-2 text-sm font-semibold cursor-pointer"
              >
                <span className="material-symbols-outlined text-sm">logout</span>
                Sign Out
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
