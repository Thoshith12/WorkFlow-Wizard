import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { getToken } from '../utils/auth';

function formatRelativeTime(dateStr) {
  if (!dateStr) return 'Just now';
  const date = new Date(dateStr);
  if (isNaN(date.getTime())) return 'Recently';
  const now = new Date();
  const diffSec = Math.floor((now - date) / 1000);

  if (diffSec < 60) return 'Just now';
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin} min${diffMin > 1 ? 's' : ''} ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr} hour${diffHr > 1 ? 's' : ''} ago`;
  const diffDays = Math.floor(diffHr / 24);
  if (diffDays < 30) return `${diffDays} day${diffDays > 1 ? 's' : ''} ago`;
  return date.toLocaleDateString();
}

function formatStatus(status) {
  if (!status) return { text: 'Active', dotColor: 'bg-secondary', textColor: 'text-secondary', isProcessing: false };
  const s = String(status).toLowerCase();

  if (s.includes('fail') || s.includes('error')) {
    return { text: 'Failed', dotColor: 'bg-error', textColor: 'text-error', isProcessing: false };
  }
  if (s === 'preprocessing completed') {
    return { text: 'Preprocessing Completed', dotColor: 'bg-secondary', textColor: 'text-secondary', isProcessing: false };
  }
  if (s === 'chunking initiated' || s === 'chunking' || s.includes('chunk')) {
    return { text: 'Chunking Initiated', dotColor: 'bg-amber-400', textColor: 'text-amber-400', isProcessing: true };
  }
  if (s === 'extraction initiated' || s === 'extraction processing' || s.includes('extract')) {
    return { text: 'Extraction Initiated', dotColor: 'bg-amber-400', textColor: 'text-amber-400', isProcessing: true };
  }
  if (s === 'preprocessing initiated' || s.includes('preprocess')) {
    return { text: 'Preprocessing Initiated', dotColor: 'bg-amber-400', textColor: 'text-amber-400', isProcessing: true };
  }
  if (s.includes('process') || s.includes('pending') || s.includes('ingest') || s.includes('init')) {
    return { text: 'Processing Initiated', dotColor: 'bg-amber-400', textColor: 'text-amber-400', isProcessing: true };
  }
  if (s === 'vector_store_successful' || s === 'active' || s === 'synced' || s === 'completed' || s === 'success') {
    const text = (s === 'vector_store_successful' || s === 'active') ? 'Active' : (s.charAt(0).toUpperCase() + s.slice(1));
    return { text, dotColor: 'bg-secondary', textColor: 'text-secondary', isProcessing: false };
  }
  const formatted = s.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
  return { text: formatted, dotColor: 'bg-secondary', textColor: 'text-secondary', isProcessing: false };
}

export default function RagListPage() {
  const [dataSources, setDataSources] = useState([]);
  const [loading, setLoading] = useState(true);
  const [deletingId, setDeletingId] = useState(null);
  const [errorMessage, setErrorMessage] = useState(null);
  const [deleteModal, setDeleteModal] = useState({ open: false, id: null, name: '' });
  const navigate = useNavigate();

  useEffect(() => {
    document.title = 'Data Sources - ORCHESTRA_RAG';
    fetchDataSources(false);

    // 4-second polling loop to get real-time status updates of extraction/preprocessing
    const interval = setInterval(() => {
      fetchDataSources(true);
    }, 4000);

    return () => clearInterval(interval);
  }, []);

  const fetchDataSources = async (isSilent = false) => {
    if (!isSilent) setLoading(true);
    const token = getToken();
    try {
      const headers = { 'Accept': 'application/json' };
      if (token) headers['Authorization'] = `Bearer ${token}`;

      const response = await fetch('/api/data-sources', { headers });
      if (response.ok) {
        const data = await response.json();
        if (Array.isArray(data)) {
          const mapped = data.map(item => {
            const statusObj = formatStatus(item.status);
            const recordsCount = (item.document_count !== undefined && item.document_count !== null)
              ? item.document_count
              : (item.total_chunks || 0);

            return {
              id: item.data_source_id || item.id,
              name: item.name || 'Unnamed Base',
              rawStatus: item.status,
              status: statusObj.text,
              dotColor: statusObj.dotColor,
              textColor: statusObj.textColor,
              isProcessing: statusObj.isProcessing,
              totalRecords: Number(recordsCount).toLocaleString(),
              lastUpdated: formatRelativeTime(item.updated_at || item.created_at)
            };
          });
          setDataSources(mapped);
        }
      }
    } catch (err) {
      if (!isSilent) console.warn('Failed to fetch data sources from API:', err);
    } finally {
      if (!isSilent) setLoading(false);
    }
  };

  const openDeleteModal = (id, name) => {
    setDeleteModal({ open: true, id, name });
  };

  const closeDeleteModal = () => {
    if (!deletingId) {
      setDeleteModal({ open: false, id: null, name: '' });
    }
  };

  const confirmDelete = async () => {
    if (!deleteModal.id) return;
    const { id } = deleteModal;

    setDeletingId(id);
    setErrorMessage(null);
    const token = getToken();
    try {
      const headers = { 'Accept': 'application/json' };
      if (token) headers['Authorization'] = `Bearer ${token}`;

      const response = await fetch(`/api/data-sources/${id}`, {
        method: 'DELETE',
        headers
      });

      if (response.ok) {
        setDeleteModal({ open: false, id: null, name: '' });
        fetchDataSources(true);
      } else {
        const err = await response.json().catch(() => ({}));
        setErrorMessage(err.detail || 'Failed to delete data source.');
      }
    } catch (err) {
      console.error('Delete data source error:', err);
      setErrorMessage('Failed to connect to service to delete data source.');
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <div className="max-w-6xl mx-auto space-y-stack-lg">
      <div>
        <h2 className="font-headline-lg text-headline-lg text-on-surface mb-2">RAG Engine</h2>
        <p className="text-on-surface-variant text-body-lg max-w-2xl">
          Upload documents to be vectorized and stored for Retrieval-Augmented Generation workflows. Supported formats: PDF, TXT, CSV, MD.
        </p>
      </div>

      {/* Top Error / Warning Banner */}
      {errorMessage && (
        <div className="bg-error-container/30 border border-error/40 text-on-surface rounded-xl p-4 flex items-center justify-between shadow-lg">
          <div className="flex items-center gap-3">
            <span className="material-symbols-outlined text-error">warning</span>
            <span className="text-body-md text-error font-medium">{errorMessage}</span>
          </div>
          <button 
            onClick={() => setErrorMessage(null)}
            className="text-outline hover:text-on-surface p-1 rounded cursor-pointer"
          >
            <span className="material-symbols-outlined text-sm">close</span>
          </button>
        </div>
      )}

      <div className="space-y-6">
        <div className="flex justify-between items-center">
          <h3 className="font-headline-sm text-headline-sm text-on-surface">Available RAG Bases</h3>
          <button
            onClick={() => navigate('/rag/create')}
            className="bg-primary text-on-primary hover:bg-primary-fixed transition-colors py-2 px-6 rounded-lg flex items-center gap-2 font-bold text-body-md cursor-pointer"
          >
            <span className="material-symbols-outlined text-[18px]">add</span>
            Start New RAG Base
          </button>
        </div>

        <div className="bg-surface-container-low rounded-xl border border-outline-variant overflow-hidden">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-surface-container-high/50 border-b border-outline-variant">
                <th className="p-4 font-label-caps text-label-caps text-outline">Name</th>
                <th className="p-4 font-label-caps text-label-caps text-outline">Status</th>
                <th className="p-4 font-label-caps text-label-caps text-outline">Total Records</th>
                <th className="p-4 font-label-caps text-label-caps text-outline">Last Updated</th>
                <th className="p-4 font-label-caps text-label-caps text-outline text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-outline-variant">
              {loading ? (
                <tr>
                  <td colSpan="5" className="p-8 text-center text-on-surface-variant font-code-md">
                    <div className="flex items-center justify-center gap-2">
                      <span className="material-symbols-outlined animate-spin text-primary">sync</span>
                      Loading RAG bases...
                    </div>
                  </td>
                </tr>
              ) : dataSources.length === 0 ? (
                <tr>
                  <td colSpan="5" className="p-8 text-center text-on-surface-variant font-code-md">
                    <div className="flex flex-col items-center justify-center gap-2">
                      <span className="material-symbols-outlined text-outline text-3xl">database_off</span>
                      <p className="text-body-md font-semibold text-on-surface">No RAG bases available</p>
                      <p className="text-xs text-outline font-code-sm">Click 'Start New RAG Base' to ingest your first document store.</p>
                    </div>
                  </td>
                </tr>
              ) : (
                dataSources.map((ds) => {
                  const isVectorized = ds.rawStatus === 'vector_store_successful' || ds.rawStatus === 'active';
                  const targetUrl = isVectorized ? `/rag/search?id=${ds.id}` : `/rag/create?id=${ds.id}`;

                  return (
                    <tr key={ds.id || ds.name} className="hover:bg-surface-variant/30 transition-colors group">
                      <td
                        onClick={() => navigate(targetUrl)}
                        className="p-4 cursor-pointer"
                      >
                        <div className="flex items-center gap-3">
                          <span className="material-symbols-outlined text-secondary group-hover:text-primary transition-colors">folder_special</span>
                          <span className="font-code-md text-on-surface group-hover:text-primary font-semibold transition-colors">{ds.name}</span>
                        </div>
                      </td>
                      <td
                        onClick={() => navigate(targetUrl)}
                        className="p-4 cursor-pointer"
                      >
                        <div className="flex items-center gap-2">
                          {ds.isProcessing ? (
                            <span className="material-symbols-outlined animate-spin text-amber-400 text-sm">sync</span>
                          ) : (
                            <div className={`w-2 h-2 rounded-full ${ds.dotColor || 'bg-secondary'}`}></div>
                          )}
                          <span className={`${ds.textColor || 'text-secondary'} text-sm font-medium`}>{ds.status}</span>
                        </div>
                      </td>
                      <td
                        onClick={() => navigate(targetUrl)}
                        className="p-4 text-on-surface-variant cursor-pointer"
                      >
                        {ds.totalRecords}
                      </td>
                      <td
                        onClick={() => navigate(targetUrl)}
                        className="p-4 text-on-surface-variant cursor-pointer"
                      >
                        {ds.lastUpdated}
                      </td>
                    <td className="p-4 text-right">
                      <div className="flex items-center justify-end gap-2">
                        {!ds.isProcessing && (ds.rawStatus === 'vector_store_successful' || ds.rawStatus === 'active') && (
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              navigate(`/rag/search?id=${ds.id}`);
                            }}
                            title="Test Retrieval Search"
                            className="text-secondary hover:text-secondary/80 p-1.5 rounded-lg hover:bg-secondary-container/20 transition-colors cursor-pointer"
                          >
                            <span className="material-symbols-outlined text-[18px]">search_check</span>
                          </button>
                        )}
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            openDeleteModal(ds.id, ds.name);
                          }}
                          disabled={deletingId === ds.id || ds.isProcessing}
                          title={ds.isProcessing ? "Delete disabled while processing" : "Delete Data Source"}
                          className="text-error hover:text-error/80 p-1.5 rounded-lg hover:bg-error-container/20 transition-colors disabled:opacity-30 disabled:cursor-not-allowed cursor-pointer"
                        >
                          <span className="material-symbols-outlined text-[18px]">delete</span>
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Styled Confirmation Modal */}
      {deleteModal.open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-fade-in">
          <div className="bg-surface-container-low border border-outline-variant rounded-2xl max-w-md w-full p-6 shadow-2xl space-y-5">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-full bg-error-container/40 flex items-center justify-center border border-error/30">
                <span className="material-symbols-outlined text-error text-xl">warning</span>
              </div>
              <div>
                <h3 className="font-headline-sm text-headline-sm text-on-surface">Delete RAG Base?</h3>
                <p className="text-xs text-outline font-code-sm">Irreversible Storage Cleanup</p>
              </div>
            </div>

            <p className="text-on-surface-variant text-body-md leading-relaxed">
              Are you sure you want to completely delete <strong className="text-on-surface">{deleteModal.name}</strong>?
            </p>

            <div className="bg-surface-container-high/60 border border-outline-variant/60 rounded-xl p-3.5 space-y-2 text-xs text-outline font-code-sm">
              <div className="flex items-center gap-2">
                <span className="material-symbols-outlined text-secondary text-sm">check_circle</span>
                <span>Purges document files from MinIO Storage</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="material-symbols-outlined text-secondary text-sm">check_circle</span>
                <span>Drops vector collections from Qdrant</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="material-symbols-outlined text-secondary text-sm">check_circle</span>
                <span>Removes all registry records from PostgreSQL</span>
              </div>
            </div>

            <div className="flex items-center justify-end gap-3 pt-2">
              <button
                type="button"
                onClick={closeDeleteModal}
                disabled={deletingId === deleteModal.id}
                className="px-4 py-2 rounded-lg border border-outline-variant text-on-surface-variant hover:bg-surface-variant transition-colors text-body-md font-medium disabled:opacity-50 cursor-pointer"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={confirmDelete}
                disabled={deletingId === deleteModal.id}
                className="px-5 py-2 rounded-lg bg-error text-on-error hover:bg-error/90 font-bold transition-colors text-body-md flex items-center gap-2 disabled:opacity-50 cursor-pointer"
              >
                {deletingId === deleteModal.id ? (
                  <>
                    <span className="material-symbols-outlined animate-spin text-sm">sync</span>
                    Deleting...
                  </>
                ) : (
                  <>
                    <span className="material-symbols-outlined text-sm">delete</span>
                    Delete Base
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
