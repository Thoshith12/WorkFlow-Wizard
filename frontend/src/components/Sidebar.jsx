import React from 'react';
import { NavLink, useNavigate } from 'react-router-dom';

export default function Sidebar() {
  const navigate = useNavigate();

  return (
    <nav class="bg-surface-container-lowest text-primary font-body-md text-body-md border-r border-outline-variant flex flex-col fixed left-0 top-0 h-full z-40 w-72">
      <div class="p-6">
        <h1 class="font-headline-md text-headline-md font-bold text-on-surface">Workflow Wizard</h1>
      </div>
      <div class="px-4 mb-6">
        <button
          onClick={() => navigate('/rag/create')}
          class="w-full bg-primary-container text-on-primary-container hover:bg-primary-fixed transition-colors py-2 px-4 rounded-lg flex items-center justify-center gap-2 font-bold text-body-md"
        >
          <span class="material-symbols-outlined text-[18px]">add</span>
          Start New RAG Base
        </button>
      </div>
      <ul class="flex-1 px-3 space-y-1 overflow-y-auto">
        <li>
          <NavLink
            to="/canvas"
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2 rounded-lg transition-all active:scale-95 duration-150 ${
                isActive
                  ? 'bg-secondary-container text-on-secondary-container font-bold shadow-[0_0_15px_rgba(4,180,162,0.1)]'
                  : 'text-on-surface-variant hover:text-on-surface hover:bg-surface-variant'
              }`
            }
          >
            <span class="material-symbols-outlined text-[20px]">account_tree</span>
            Canvas
          </NavLink>
        </li>
        <li>
          <NavLink
            to="/rag"
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2 rounded-lg transition-all active:scale-95 duration-150 ${
                isActive
                  ? 'bg-secondary-container text-on-secondary-container font-bold shadow-[0_0_15px_rgba(4,180,162,0.1)]'
                  : 'text-on-surface-variant hover:text-on-surface hover:bg-surface-variant'
              }`
            }
          >
            <span className="material-symbols-outlined text-[20px]">database</span>
            RAG Engine
          </NavLink>
        </li>
        <li>
          <NavLink
            to="/llm-config"
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2 rounded-lg transition-all active:scale-95 duration-150 ${
                isActive
                  ? 'bg-secondary-container text-on-secondary-container font-bold shadow-[0_0_15px_rgba(4,180,162,0.1)]'
                  : 'text-on-surface-variant hover:text-on-surface hover:bg-surface-variant'
              }`
            }
          >
            <span class="material-symbols-outlined text-[20px]">psychology</span>
            LLM Config
          </NavLink>
        </li>
        <li>
          <NavLink
            to="/health"
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2 rounded-lg transition-all active:scale-95 duration-150 ${
                isActive
                  ? 'bg-secondary-container text-on-secondary-container font-bold shadow-[0_0_15px_rgba(4,180,162,0.1)]'
                  : 'text-on-surface-variant hover:text-on-surface hover:bg-surface-variant'
              }`
            }
          >
            <span class="material-symbols-outlined text-[20px]">insights</span>
            Health
          </NavLink>
        </li>
      </ul>
      <div class="p-3 border-t border-outline-variant">
        <ul class="space-y-1">
          <li>
            <NavLink
              to="/logs"
              className="flex items-center gap-3 px-3 py-2 rounded-lg text-on-surface-variant hover:text-on-surface hover:bg-surface-variant transition-all"
            >
              <span class="material-symbols-outlined text-[18px]">terminal</span>
              <span class="font-code-sm text-code-sm">Logs</span>
            </NavLink>
          </li>
          <li>
            <NavLink
              to="/terminal"
              className="flex items-center gap-3 px-3 py-2 rounded-lg text-on-surface-variant hover:text-on-surface hover:bg-surface-variant transition-all"
            >
              <span class="material-symbols-outlined text-[18px]">code</span>
              <span class="font-code-sm text-code-sm">Terminal</span>
            </NavLink>
          </li>
        </ul>
      </div>
    </nav>
  );
}
