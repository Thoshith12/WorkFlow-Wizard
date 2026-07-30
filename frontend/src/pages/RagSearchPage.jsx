import React, { useState, useEffect } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { getToken } from '../utils/auth';

export default function RagSearchPage() {
  const [searchParams] = useSearchParams();
  const urlConnectorId = searchParams.get('id');

  const [activeConnectors, setActiveConnectors] = useState([]);
  const [selectedConnectorId, setSelectedConnectorId] = useState('');
  const [query, setQuery] = useState('APNT Business Solutions Pvt. Ltd');
  const [topK, setTopK] = useState(5);
  const [threshold, setThreshold] = useState(0.0);

  const [loadingConnectors, setLoadingConnectors] = useState(true);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState('');
  const [searchResults, setSearchResults] = useState(null);

  const navigate = useNavigate();

  useEffect(() => {
    document.title = 'Retrieval Testing - Workflow Wizard';
    fetchActiveConnectors();
  }, []);

  const fetchActiveConnectors = async () => {
    setLoadingConnectors(true);
    const token = getToken();
    try {
      const headers = { 'Accept': 'application/json' };
      if (token) headers['Authorization'] = `Bearer ${token}`;

      const res = await fetch('/api/data-sources', { headers });
      if (res.ok) {
        const data = await res.json();
        if (Array.isArray(data)) {
          // Filter ONLY active / vector_store_successful data connectors
          const active = data.filter(
            (item) => item.status === 'vector_store_successful' || item.status === 'active'
          );
          setActiveConnectors(active);

          if (urlConnectorId && active.some(c => c.data_source_id === urlConnectorId || c.id === urlConnectorId)) {
            setSelectedConnectorId(urlConnectorId);
          } else if (active.length > 0) {
            setSelectedConnectorId(active[0].data_source_id || active[0].id);
          }
        }
      }
    } catch (err) {
      console.warn('Failed to load data connectors:', err);
      setError('Failed to fetch data connectors.');
    } finally {
      setLoadingConnectors(false);
    }
  };

  const handleExecuteSearch = async (e) => {
    if (e) e.preventDefault();
    if (!selectedConnectorId) {
      setError('Please select an active Data Connector.');
      return;
    }
    if (!query.trim()) {
      setError('Please enter a search query.');
      return;
    }

    setError('');
    setSearching(true);
    const token = getToken();

    try {
      const headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        ...(token ? { 'Authorization': `Bearer ${token}` } : {})
      };

      const payload = {
        data_connector_id: selectedConnectorId,
        query: query.trim(),
        threshold: Number(threshold),
        top_k: Number(topK)
      };

      const res = await fetch('/api/data-sources/search', {
        method: 'POST',
        headers,
        body: JSON.stringify(payload)
      });

      if (!responseOk(res)) {
        const errBody = await res.json().catch(() => ({}));
        throw new Error(errBody.detail || 'Search request failed');
      }

      const data = await res.json();
      setSearchResults(data);
    } catch (err) {
      console.error('Vector Search Error:', err);
      setError(err.message || 'An error occurred while querying Qdrant vector database.');
    } finally {
      setSearching(false);
    }
  };

  const responseOk = (res) => res.ok;

  const truncateId = (str) => {
    if (!str) return 'N/A';
    return str.length > 12 ? `${str.substring(0, 8)}...` : str;
  };

  return (
    <div className="max-w-6xl mx-auto space-y-6 pb-12">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-headline-lg text-headline-lg text-on-surface mb-1">Retrieval Testing</h1>
          <p className="font-body-lg text-body-lg text-on-surface-variant">
            Test and verify your RAG retrieval quality with live queries against Qdrant vector store.
          </p>
        </div>

        <button
          onClick={() => navigate('/rag')}
          className="text-outline hover:text-on-surface transition-colors flex items-center gap-1 font-code-sm cursor-pointer"
        >
          <span className="material-symbols-outlined text-lg">arrow_back</span>
          Back to RAG Bases
        </button>
      </div>

      {error && (
        <div className="p-3.5 rounded-xl border text-sm font-code-md bg-error-container/40 border-error text-error flex items-center gap-2">
          <span className="material-symbols-outlined text-lg">error</span>
          <span>{error}</span>
        </div>
      )}

      {/* Testing Controls Section */}
      <section className="bg-surface-container-low border border-outline-variant rounded-xl p-6 shadow-2xl space-y-6">
        <form onSubmit={handleExecuteSearch} className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-end">
          {/* Data Connector Selector */}
          <div className="lg:col-span-4 space-y-2">
            <label className="block font-label-caps text-label-caps text-primary uppercase">
              Select Active Data Connector
            </label>
            {loadingConnectors ? (
              <div className="p-3 rounded-lg border border-outline-variant bg-[#060e20] text-xs font-code-sm text-outline flex items-center gap-2">
                <span className="material-symbols-outlined animate-spin text-sm text-primary">sync</span>
                Loading Active Connectors...
              </div>
            ) : activeConnectors.length === 0 ? (
              <div className="p-3 rounded-lg border border-amber-400/40 bg-amber-400/10 text-xs font-code-sm text-amber-400">
                No active vectorized connectors found. Finalize chunking on a base first.
              </div>
            ) : (
              <select
                value={selectedConnectorId}
                onChange={(e) => setSelectedConnectorId(e.target.value)}
                className="w-full bg-[#060e20] border border-outline-variant text-slate-100 rounded-lg p-3 font-code-md focus:border-primary transition-colors cursor-pointer outline-none"
              >
                {activeConnectors.map((c) => (
                  <option key={c.data_source_id || c.id} value={c.data_source_id || c.id}>
                    {c.name} ({c.document_count || 1} docs)
                  </option>
                ))}
              </select>
            )}
          </div>

          {/* Query Input */}
          <div className="lg:col-span-8 space-y-2">
            <label className="block font-label-caps text-label-caps text-primary uppercase">
              Search Query
            </label>
            <div className="relative">
              <input
                type="text"
                required
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Enter query to test vector similarity..."
                className="w-full bg-[#060e20] border border-outline-variant text-slate-100 rounded-lg px-4 py-3 font-body-md focus:border-primary transition-all outline-none"
              />
            </div>
          </div>

          {/* Parameters Sliders */}
          <div className="lg:col-span-9 grid grid-cols-2 gap-6 bg-[#060e20]/60 p-4 rounded-xl border border-outline-variant/60">
            <div className="space-y-2">
              <div className="flex justify-between text-xs font-label-caps text-on-surface-variant uppercase">
                <span>Top K Results</span>
                <span className="text-primary font-bold">{topK}</span>
              </div>
              <input
                type="range"
                min="1"
                max="50"
                value={topK}
                onChange={(e) => setTopK(e.target.value)}
                className="w-full h-1.5 bg-surface-variant rounded-lg appearance-none cursor-pointer accent-primary"
              />
            </div>

            <div className="space-y-2">
              <div className="flex justify-between text-xs font-label-caps text-on-surface-variant uppercase">
                <span>Score Threshold</span>
                <span className="text-primary font-bold">{Number(threshold).toFixed(2)}</span>
              </div>
              <input
                type="range"
                min="0"
                max="1"
                step="0.05"
                value={threshold}
                onChange={(e) => setThreshold(e.target.value)}
                className="w-full h-1.5 bg-surface-variant rounded-lg appearance-none cursor-pointer accent-primary"
              />
            </div>
          </div>

          {/* Execute Button */}
          <div className="lg:col-span-3">
            <button
              type="submit"
              disabled={searching || activeConnectors.length === 0}
              className="w-full bg-primary text-on-primary font-bold py-3.5 px-4 rounded-lg flex items-center justify-center gap-2 hover:bg-primary-fixed active:scale-95 transition-all shadow-lg shadow-primary/20 cursor-pointer disabled:opacity-50"
            >
              {searching ? (
                <>
                  <span className="material-symbols-outlined animate-spin text-lg">sync</span>
                  <span>Searching Qdrant...</span>
                </>
              ) : (
                <>
                  <span className="material-symbols-outlined text-lg">search_check</span>
                  <span>Execute Search</span>
                </>
              )}
            </button>
          </div>
        </form>
      </section>

      {/* Results Header */}
      <div className="flex items-center justify-between px-2 pt-2">
        <div className="flex items-center gap-2">
          <span className="material-symbols-outlined text-secondary text-xl">analytics</span>
          <span className="font-headline-sm text-headline-sm text-on-surface">Search Results</span>
          {searchResults && (
            <span className="ml-2 px-2.5 py-1 bg-secondary-container/20 text-secondary text-xs font-code-md rounded-lg border border-secondary/30 font-bold">
              Found {searchResults.results_count || (searchResults.results ? searchResults.results.length : 0)} Matches
            </span>
          )}
        </div>
      </div>

      {/* Results List */}
      {searchResults && (
        <div className="space-y-4 animate-fade-in">
          {(!searchResults.results || searchResults.results.length === 0) ? (
            <div className="bg-surface-container p-8 rounded-xl border border-outline-variant text-center space-y-2">
              <span className="material-symbols-outlined text-outline text-4xl">find_in_page</span>
              <p className="text-on-surface font-semibold">No relevant vector chunks found.</p>
              <p className="text-xs text-outline font-code-sm">Try reducing the Score Threshold or adjusting the search query.</p>
            </div>
          ) : (
            searchResults.results.map((res, idx) => {
              const scorePct = Math.min(100, Math.max(0, (res.score || 0) * 100)).toFixed(1);
              return (
                <div
                  key={res.chunk_id || idx}
                  className="bg-surface-container border border-outline-variant/60 rounded-xl overflow-hidden hover:border-primary/50 transition-all shadow-lg group"
                >
                  <div className="flex flex-col sm:flex-row">
                    {/* Score Sidebar */}
                    <div className="sm:w-28 bg-surface-container-high flex flex-col items-center justify-center border-b sm:border-b-0 sm:border-r border-outline-variant/40 p-4">
                      <span className="font-label-caps text-label-caps text-on-surface-variant uppercase mb-1">Score</span>
                      <div className="font-code-md text-headline-sm font-bold text-primary">
                        {(res.score !== undefined ? res.score : 0).toFixed(3)}
                      </div>
                      <div className="w-16 h-1.5 bg-primary/20 mt-2 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-primary transition-all duration-500"
                          style={{ width: `${scorePct}%` }}
                        ></div>
                      </div>
                    </div>

                    {/* Main Content */}
                    <div className="flex-1 p-5 space-y-4">
                      <div className="font-code-md text-xs text-on-surface leading-relaxed bg-[#060e20] p-4 rounded-lg border border-outline-variant/40 whitespace-pre-wrap select-text">
                        {res.chunk_text}
                      </div>

                      {/* Metadata Badges */}
                      <div className="flex flex-wrap gap-2 text-xs font-code-sm">
                        <div className="flex items-center gap-1.5 px-3 py-1 bg-surface-variant/40 rounded border border-outline-variant/30 text-on-surface-variant">
                          <span className="material-symbols-outlined text-[14px]">id_card</span>
                          <span className="opacity-60 uppercase">Chunk:</span> {truncateId(res.chunk_id)}
                        </div>
                        <div className="flex items-center gap-1.5 px-3 py-1 bg-surface-variant/40 rounded border border-outline-variant/30 text-on-surface-variant">
                          <span className="material-symbols-outlined text-[14px]">description</span>
                          <span className="opacity-60 uppercase">Doc:</span> {truncateId(res.document_id)}
                        </div>
                        <div className="flex items-center gap-1.5 px-3 py-1 bg-surface-variant/40 rounded border border-outline-variant/30 text-on-surface-variant">
                          <span className="material-symbols-outlined text-[14px]">model_training</span>
                          <span className="opacity-60 uppercase">Model:</span> {res.embedding_model || 'MiniLM-L12'}
                        </div>
                        {res.embedding_mode && (
                          <div className="flex items-center gap-1.5 px-3 py-1 bg-surface-variant/40 rounded border border-outline-variant/30 text-on-surface-variant uppercase">
                            <span className="material-symbols-outlined text-[14px]">tune</span>
                            <span className="opacity-60 uppercase">Mode:</span> {res.embedding_mode}
                          </div>
                        )}
                        {res.chunk_index !== undefined && res.chunk_index !== null && (
                          <div className="flex items-center gap-1.5 px-3 py-1 bg-surface-variant/40 rounded border border-outline-variant/30 text-on-surface-variant">
                            <span className="material-symbols-outlined text-[14px]">grid_view</span>
                            <span className="opacity-60 uppercase">Index:</span> {res.chunk_index}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              );
            })
          )}
        </div>
      )}
    </div>
  );
}
