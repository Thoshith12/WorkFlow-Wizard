import React, { useState, useEffect } from 'react';
import { getToken } from '../utils/auth';

export default function ToolsPage() {
  const [tools, setTools] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [activeTab, setActiveTab] = useState('All Tools');

  useEffect(() => {
    document.title = 'Tools Registry - Workflow Wizard';
    fetchTools();
  }, []);

  const fetchTools = async () => {
    setLoading(true);
    setError(null);
    try {
      const token = getToken();
      const headers = { 'Accept': 'application/json' };
      if (token) headers['Authorization'] = `Bearer ${token}`;

      const response = await fetch('http://localhost:8002/api/tools', { headers });
      if (response.ok) {
        const data = await response.json();
        setTools(data);
      } else {
        throw new Error('Failed to fetch tools');
      }
    } catch (err) {
      console.error('Fetch tools error:', err);
      setError('Could not load tools from the registry.');
    } finally {
      setLoading(false);
    }
  };

  const filteredTools = tools.filter(tool => {
    // Tab Filtering
    if (activeTab === 'System' && tool.tool_type !== 'system') return false;
    if (activeTab === 'Custom' && tool.tool_type !== 'custom') return false;
    if (activeTab === 'MCP' && tool.tool_type !== 'mcp') return false;

    // Search Filtering
    if (searchTerm) {
      const term = searchTerm.toLowerCase();
      const nameMatch = (tool.display_name || tool.name || '').toLowerCase().includes(term);
      const descMatch = (tool.description || '').toLowerCase().includes(term);
      if (!nameMatch && !descMatch) return false;
    }
    return true;
  });

  const getCardStyles = (toolType, status) => {
    const isError = status && status.toLowerCase().includes('error');
    const isSyncing = status && status.toLowerCase().includes('sync');
    
    if (isError) {
      return {
        accent: 'error',
        border: 'border-outline-variant hover:border-outline',
        gradient: 'from-error to-error-container',
        iconBg: 'bg-surface',
        iconColor: 'text-primary group-hover:text-error',
        dot: 'bg-error shadow-[0_0_8px_rgba(255,180,171,0.6)]',
        statusColor: 'text-error',
        badgeBg: 'bg-error/10 border-error/30',
        badgeText: 'text-error',
        icon: 'terminal'
      };
    }

    if (toolType === 'system') {
      return {
        accent: 'secondary',
        border: 'border-outline-variant hover:border-outline',
        gradient: 'from-secondary to-primary',
        iconBg: 'bg-surface',
        iconColor: 'text-primary group-hover:text-secondary',
        dot: 'bg-secondary shadow-[0_0_8px_rgba(79,219,200,0.6)]',
        statusColor: 'text-on-surface-variant',
        badgeBg: 'bg-secondary/10 border-secondary/30',
        badgeText: 'text-secondary',
        icon: 'build'
      };
    }

    // Custom tools
    return {
      accent: 'primary',
      border: isSyncing ? 'border-primary/50 hover:border-primary shadow-[0_0_15px_rgba(192,193,255,0.05)]' : 'border-outline-variant hover:border-outline',
      gradient: isSyncing ? 'from-primary to-primary' : 'from-primary to-secondary',
      iconBg: isSyncing ? 'bg-primary-container/20 border-primary/30' : 'bg-surface',
      iconColor: isSyncing ? 'text-primary' : 'text-on-surface-variant group-hover:text-primary',
      dot: isSyncing ? 'bg-tertiary shadow-[0_0_8px_rgba(255,185,95,0.6)] animate-pulse' : 'bg-outline shadow-[0_0_8px_rgba(144,143,160,0.6)]',
      statusColor: 'text-on-surface-variant',
      badgeBg: 'bg-primary/20 border-primary/40',
      badgeText: 'text-primary',
      icon: 'data_object'
    };
  };

  const tabs = ['All Tools', 'System', 'Custom', 'MCP'];

  return (
    <div className="flex flex-col h-full -m-gutter">
      {/* Toolbar / Header Area */}
      <div className="bg-surface/80 backdrop-blur-md border-b border-outline-variant p-6 shrink-0 z-10">
        <div className="max-w-7xl mx-auto flex flex-row justify-between gap-6 items-start">
          <div>
            <h2 className="font-headline-lg text-headline-lg text-on-surface mb-2">Tools Registry</h2>
            <p className="font-body-lg text-body-lg text-on-surface-variant">Manage and inspect available capabilities for your agentic workflows.</p>
          </div>
          <button className="px-6 py-2.5 bg-primary text-on-primary rounded hover:bg-primary-fixed transition-all flex items-center gap-2 font-body-md font-medium shadow-[0_0_15px_rgba(192,193,255,0.1)] active:scale-95 shrink-0 mt-1 cursor-pointer">
            <span className="material-symbols-outlined text-[20px]">add</span>
            <span>Create New Custom Tool</span>
          </button>
        </div>

        {/* Filtering Tabs */}
        <div className="max-w-7xl mx-auto mt-6 relative">
          <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-on-surface-variant text-[18px]">search</span>
          <input 
            className="bg-surface-container-highest border border-outline-variant rounded h-10 pl-10 pr-4 text-body-md font-code-md text-on-surface placeholder:text-on-surface-variant focus:border-primary focus:ring-1 focus:ring-primary outline-none w-full transition-all" 
            placeholder="Search tools..." 
            type="text" 
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
          />
        </div>
        <div className="max-w-7xl mx-auto mt-8 flex items-center gap-1 border-b border-outline-variant">
          {tabs.map(tab => (
            <button 
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-4 py-2 border-b-2 font-body-md transition-colors cursor-pointer ${activeTab === tab ? 'border-primary text-primary font-medium' : 'border-transparent text-on-surface-variant hover:text-on-surface'}`}
            >
              {tab}
            </button>
          ))}
        </div>
      </div>

      {/* Grid Area */}
      <div className="flex-1 overflow-y-auto p-6 z-0">
        <div className="max-w-7xl mx-auto">
          {error && (
            <div className="bg-error-container/30 border border-error/40 text-on-surface rounded-xl p-4 flex items-center justify-between shadow-lg mb-6">
              <div className="flex items-center gap-3">
                <span className="material-symbols-outlined text-error">warning</span>
                <span className="text-body-md text-error font-medium">{error}</span>
              </div>
              <button onClick={() => setError(null)} className="text-outline hover:text-on-surface p-1 rounded cursor-pointer">
                <span className="material-symbols-outlined text-sm">close</span>
              </button>
            </div>
          )}

          {loading ? (
            <div className="flex flex-col items-center justify-center p-12 gap-4">
              <span className="material-symbols-outlined animate-spin text-primary text-4xl">sync</span>
              <p className="text-on-surface-variant font-code-md">Loading tools from registry...</p>
            </div>
          ) : filteredTools.length === 0 ? (
            <div className="flex flex-col items-center justify-center p-12 gap-4">
              <span className="material-symbols-outlined text-outline text-5xl">construction</span>
              <p className="text-on-surface font-semibold text-headline-sm">No tools found</p>
              <p className="text-on-surface-variant text-body-md">Try adjusting your filters or search query.</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {filteredTools.map(tool => {
                const style = getCardStyles(tool.tool_type, tool.status);
                
                return (
                  <div key={tool.name} className={`bg-surface-container-highest border rounded-lg p-5 flex flex-col gap-4 transition-colors group relative overflow-hidden ${style.border}`}>
                    <div className={`absolute top-0 left-0 w-full h-1 bg-gradient-to-r opacity-0 group-hover:opacity-100 transition-opacity ${style.gradient}`}></div>
                    
                    <div className="flex items-start justify-between">
                      <div className="flex items-center gap-3">
                        <div className={`w-10 h-10 rounded border flex items-center justify-center transition-colors ${style.iconBg} ${style.iconColor} border-${style.accent}/30`}>
                          <span className="material-symbols-outlined">
                            {tool.name.includes('search') ? 'search' : tool.name.includes('wiki') ? 'menu_book' : style.icon}
                          </span>
                        </div>
                        <div>
                          <h3 className="font-headline-sm text-headline-sm text-on-surface line-clamp-1" title={tool.display_name || tool.name}>
                            {tool.display_name || tool.name}
                          </h3>
                          <div className="flex items-center gap-2 mt-1">
                            <span className="font-label-caps text-label-caps bg-surface-container px-1.5 py-0.5 rounded text-on-surface-variant border border-outline-variant">
                              v{tool.version || '1.0.0'}
                            </span>
                            <span className={`font-label-caps text-label-caps px-1.5 py-0.5 rounded border uppercase ${style.badgeBg} ${style.badgeText}`}>
                              {tool.tool_type}
                            </span>
                          </div>
                        </div>
                      </div>
                      
                      <div className="flex items-center gap-1.5 shrink-0 ml-2">
                        <span className={`w-2 h-2 rounded-full ${style.dot}`}></span>
                        <span className={`font-code-sm text-code-sm uppercase ${style.statusColor}`}>
                          {tool.status || 'Active'}
                        </span>
                      </div>
                    </div>
                    
                    <p className="font-body-md text-body-md text-on-surface-variant flex-1 line-clamp-3">
                      {tool.description || 'No description provided.'}
                    </p>
                    
                    <div className="mt-auto pt-4 border-t border-outline-variant/50">
                      <div className="flex flex-wrap gap-2">
                        {tool.capabilities && tool.capabilities.slice(0, 3).map(cap => (
                          <span key={cap} className="font-code-sm text-code-sm bg-surface px-2 py-1 rounded text-on-surface-variant border border-outline-variant">
                            {cap}
                          </span>
                        ))}
                        {tool.capabilities && tool.capabilities.length > 3 && (
                          <span className="font-code-sm text-code-sm bg-surface px-2 py-1 rounded text-on-surface-variant border border-outline-variant">
                            +{tool.capabilities.length - 3}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
