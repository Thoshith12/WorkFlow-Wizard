import React, { useState, useRef, useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { getToken } from '../utils/auth';

const ALLOWED_EXTENSIONS = ['.pdf', '.doc', '.docx', '.txt'];
const MAX_FILES = 10;
const MAX_FILE_SIZE_MB = 20;
const MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024;

const KNOWN_EMBEDDING_MODELS = [
  'sentence-transformers/all-MiniLM-L6-v2',
  'sentence-transformers/all-mpnet-base-v2',
  'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2',
  'microsoft/harrier-oss-v1-0.6b',
  'BAAI/bge-m3'
];

function formatFileSize(bytes) {
  if (!bytes || bytes === 0) return '0 Bytes';
  const k = 1024;
  const sizes = ['Bytes', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

function getFileIcon(filename) {
  const ext = filename.split('.').pop().toLowerCase();
  if (ext === 'pdf') return 'picture_as_pdf';
  if (ext === 'txt') return 'description';
  if (ext === 'doc' || ext === 'docx') return 'article';
  return 'draft';
}

function validateFile(file) {
  const ext = '.' + file.name.split('.').pop().toLowerCase();
  if (!ALLOWED_EXTENSIONS.includes(ext)) {
    return `Unsupported format '${ext}'. Allowed: PDF, DOC, DOCX, TXT.`;
  }
  if (file.size > MAX_FILE_SIZE_BYTES) {
    return `File '${file.name}' exceeds maximum limit of ${MAX_FILE_SIZE_MB} MB.`;
  }
  return null;
}

function formatStatus(statusStr) {
  if (!statusStr) return { text: 'Processing', isProcessing: true, color: 'text-amber-400' };
  const s = String(statusStr).toLowerCase();

  if (s.includes('fail') || s.includes('error')) {
    return { text: 'Processing Failed', isProcessing: false, isError: true, color: 'text-error' };
  }
  if (s === 'preprocessing completed') {
    return { text: 'Preprocessing Completed', isProcessing: false, isPreprocessed: true, color: 'text-secondary' };
  }
  if (s === 'extraction initiated' || s === 'extraction processing' || s.includes('extract')) {
    return { text: 'Extraction Processing', isProcessing: true, color: 'text-amber-400' };
  }
  if (s === 'preprocessing initiated' || s.includes('preprocess')) {
    return { text: 'Preprocessing Processing', isProcessing: true, color: 'text-amber-400' };
  }
  if (s === 'chunking initiated' || s === 'chunking' || s === 'embedding') {
    return { text: 'Vector Store & Chunking In Progress', isProcessing: true, color: 'text-amber-400' };
  }
  if (s === 'vector_store_successful' || s === 'completed' || s === 'active') {
    return { text: 'Vector Store Active & Complete', isProcessing: false, isVectorized: true, color: 'text-secondary' };
  }
  const formatted = s.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
  return { text: formatted, isProcessing: true, color: 'text-amber-400' };
}

export default function RagCreatePage() {
  // Step 1: Base Metadata & Files State
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [files, setFiles] = useState([]);
  const [dragActive, setDragActive] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [warning, setWarning] = useState('');

  // Step 2 & 3 Workflow State
  const [createdBaseId, setCreatedBaseId] = useState(null);
  const [currentStatus, setCurrentStatus] = useState('');
  const [chunkingInitiated, setChunkingInitiated] = useState(false);

  // Step 3 Configuration Form State
  const [chunkingStrategy, setChunkingStrategy] = useState('recursive');
  const [chunkSize, setChunkSize] = useState(512);
  const [chunkOverlap, setChunkOverlap] = useState(50);
  const [separatorsText, setSeparatorsText] = useState('["\\n\\n", "\\n", ".", " ", ""]');

  // Strategy Specific Configs
  const [breakpointThreshold, setBreakpointThreshold] = useState(0.3);
  const [parentChunkSize, setParentChunkSize] = useState(2048);
  const [childChunkSize, setChildChunkSize] = useState(512);

  // Embedding & Performance Configs
  const [embeddingMode, setEmbeddingMode] = useState('dense');
  const [activeModels, setActiveModels] = useState(['sentence-transformers/all-MiniLM-L6-v2']);
  const [showModelDropdown, setShowModelDropdown] = useState(false);
  const [chunksPerBatch, setChunksPerBatch] = useState(50);
  const [pagesPerBatch, setPagesPerBatch] = useState(10);

  // Agentic Accordion State
  const [showAgentic, setShowAgentic] = useState(false);

  // Retrieval Testing State
  const [searchQuery, setSearchQuery] = useState('APNT Business Solutions Pvt. Ltd');
  const [searchTopK, setSearchTopK] = useState(5);
  const [searchThreshold, setSearchThreshold] = useState(0.0);
  const [searchResults, setSearchResults] = useState(null);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState('');

  const fileInputRef = useRef(null);
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const urlId = searchParams.get('id');

  const handleExecuteSearch = async (e) => {
    if (e) e.preventDefault();
    if (!createdBaseId) return;

    setSearchError('');
    setSearching(true);
    const token = getToken();

    try {
      const headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        ...(token ? { 'Authorization': `Bearer ${token}` } : {})
      };

      const payload = {
        data_connector_id: createdBaseId,
        query: searchQuery.trim(),
        threshold: Number(searchThreshold),
        top_k: Number(searchTopK)
      };

      const res = await fetch('/api/data-sources/search', {
        method: 'POST',
        headers,
        body: JSON.stringify(payload)
      });

      if (!res.ok) {
        const errBody = await res.json().catch(() => ({}));
        throw new Error(errBody.detail || 'Search request failed');
      }

      const data = await res.json();
      setSearchResults(data);
    } catch (err) {
      console.error('Vector Search Error:', err);
      setSearchError(err.message || 'An error occurred while querying Qdrant vector database.');
    } finally {
      setSearching(false);
    }
  };

  useEffect(() => {
    if (urlId) {
      setCreatedBaseId(urlId);
    }
  }, [urlId]);

  // 4-Second Status Polling
  useEffect(() => {
    if (!createdBaseId) return;

    let isMounted = true;
    const pollStatus = async () => {
      const token = getToken();
      try {
        const headers = { 'Accept': 'application/json' };
        if (token) headers['Authorization'] = `Bearer ${token}`;

        const res = await fetch(`/api/data-sources/${createdBaseId}`, { headers });
        if (res.ok && isMounted) {
          const data = await res.json();
          if (data.name) setName(data.name);
          if (data.description) setDescription(data.description);
          setCurrentStatus(data.status || 'preprocessing initiated');
          if (data.status === 'chunking initiated' || data.status === 'vector_store_successful') {
            setChunkingInitiated(true);
          }
          if (data.documents && Array.isArray(data.documents) && files.length === 0) {
            setFiles(data.documents.map(d => ({
              name: d.file_name || 'Document',
              size: d.file_size_bytes || 0
            })));
          }
        }
      } catch (err) {
        console.warn('Status polling error:', err);
      }
    };

    pollStatus();
    const interval = setInterval(pollStatus, 4000);

    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, [createdBaseId]);

  const handleContainerClick = () => {
    if (createdBaseId || loading) return;
    if (fileInputRef.current) {
      fileInputRef.current.click();
    }
  };

  const processIncomingFiles = (incomingList) => {
    if (createdBaseId || loading) return;
    setError('');
    setWarning('');

    const validNewFiles = [];
    const rejectionMessages = [];

    for (const file of incomingList) {
      const err = validateFile(file);
      if (err) {
        rejectionMessages.push(err);
      } else {
        validNewFiles.push(file);
      }
    }

    if (rejectionMessages.length > 0) {
      setWarning(rejectionMessages.join(' '));
    }

    setFiles((prev) => {
      const existingNames = new Set(prev.map((f) => f.name));
      const deduplicated = validNewFiles.filter((f) => !existingNames.has(f.name));
      const combined = [...prev, ...deduplicated];

      if (combined.length > MAX_FILES) {
        setWarning(`Maximum limit of ${MAX_FILES} files reached. First ${MAX_FILES} files retained.`);
        return combined.slice(0, MAX_FILES);
      }
      return combined;
    });
  };

  const handleFileChange = (e) => {
    if (e.target.files && e.target.files.length > 0) {
      processIncomingFiles(Array.from(e.target.files));
    }
    if (e.target) {
      e.target.value = '';
    }
  };

  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    if (createdBaseId || loading) return;
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      processIncomingFiles(Array.from(e.dataTransfer.files));
    }
  };

  const handleDragOver = (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (createdBaseId || loading) return;
    setDragActive(true);
  };

  const handleDragLeave = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
  };

  const removeFile = (indexToRemove) => {
    if (createdBaseId || loading) return;
    setFiles((prev) => prev.filter((_, idx) => idx !== indexToRemove));
    setWarning('');
  };

  // Step 1 Submission -> Ingest Files
  const handleInitialSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setWarning('');

    if (!name.trim()) {
      setError('RAG Base Name is required.');
      return;
    }

    if (files.length === 0) {
      setError('Please select at least one valid document to upload.');
      return;
    }

    setLoading(true);
    const token = getToken();

    try {
      const formData = new FormData();
      formData.append('name', name.trim());
      formData.append('description', description.trim() || 'Technical documentation for the project');
      files.forEach((file) => {
        formData.append('files', file);
      });

      const response = await fetch('/api/data-sources/ingest-files', {
        method: 'POST',
        headers: {
          ...(token ? { 'Authorization': `Bearer ${token}` } : {})
        },
        body: formData
      });

      if (!response.ok) {
        const errBody = await response.json().catch(() => ({}));
        let detailMsg = 'Failed to ingest RAG base';
        if (typeof errBody.detail === 'string') {
          detailMsg = errBody.detail;
        } else if (Array.isArray(errBody.detail)) {
          detailMsg = errBody.detail.map(d => `${d.loc ? d.loc.slice(-1)[0] : 'field'}: ${d.msg}`).join(', ');
        } else if (errBody.detail) {
          detailMsg = JSON.stringify(errBody.detail);
        }
        throw new Error(detailMsg);
      }

      const data = await response.json();
      setCreatedBaseId(data.data_source_id);
      setCurrentStatus('extraction initiated');
    } catch (err) {
      console.error('Create RAG base error:', err);
      setError(err.message || 'An error occurred during ingestion.');
    } finally {
      setLoading(false);
    }
  };

  // Step 3 Submission -> POST /api/data-sources/{id}/chunk
  const handleInitiateChunkingPipeline = async () => {
    if (!createdBaseId) return;
    setError('');
    setLoading(true);
    const token = getToken();

    let parsedSeparators = ["\n\n", "\n", ".", " ", ""];
    try {
      if (separatorsText.trim()) {
        parsedSeparators = JSON.parse(separatorsText);
      }
    } catch (e) {
      console.warn('Failed to parse separators JSON, using default.');
    }

    try {
      const headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        ...(token ? { 'Authorization': `Bearer ${token}` } : {})
      };

      const payload = {
        chunking_strategy: chunkingStrategy,
        embedding_mode: embeddingMode,
        embedding_models: activeModels,
        chunks_per_batch: Number(chunksPerBatch),
        pages_per_batch: Number(pagesPerBatch),
        fixed_config: { chunk_size: Number(chunkSize), chunk_overlap: Number(chunkOverlap) },
        recursive_config: { chunk_size: Number(chunkSize), chunk_overlap: Number(chunkOverlap), separators: parsedSeparators },
        semantic_config: { breakpoint_threshold: Number(breakpointThreshold), min_chunk_size: 100 },
        parent_child_config: { parent_chunk_size: Number(parentChunkSize), child_chunk_size: Number(childChunkSize), overlap: Number(chunkOverlap) },
        agentic_config: { max_chunk_size: 800, min_chunk_size: 100 }
      };

      const response = await fetch(`/api/data-sources/${createdBaseId}/chunk`, {
        method: 'POST',
        headers,
        body: JSON.stringify(payload)
      });

      if (!response.ok) {
        const errBody = await response.json().catch(() => ({}));
        throw new Error(errBody.detail || 'Failed to initiate chunking pipeline.');
      }

      setChunkingInitiated(true);
      setCurrentStatus('chunking initiated');
    } catch (err) {
      console.error('Initiate chunking error:', err);
      setError(err.message || 'Failed to initiate chunking pipeline.');
    } finally {
      setLoading(false);
    }
  };

  const addModelTag = (modelName) => {
    if (!activeModels.includes(modelName)) {
      setActiveModels([...activeModels, modelName]);
    }
    setShowModelDropdown(false);
  };

  const removeModelTag = (modelName) => {
    if (activeModels.length > 1) {
      setActiveModels(activeModels.filter(m => m !== modelName));
    }
  };

  const statusInfo = formatStatus(currentStatus);

  return (
    <div className="max-w-5xl mx-auto space-y-6 pb-12">
      {/* Top Header & Navigation */}
      <div className="flex items-center justify-between">
        <button
          onClick={() => navigate('/rag')}
          className="text-outline hover:text-on-surface transition-colors flex items-center gap-1 font-code-sm cursor-pointer"
        >
          <span className="material-symbols-outlined text-lg">arrow_back</span>
          Back to bases
        </button>

        {createdBaseId && (
          <div className="flex items-center gap-2">
            <span className="px-2.5 py-1 bg-secondary-container/20 border border-secondary/40 text-secondary text-label-caps font-label-caps rounded-lg">
              {statusInfo.isVectorized ? 'STEP 04: READY' : statusInfo.isPreprocessed ? 'STEP 03: CONFIGURE PIPELINE' : 'STEP 02: PREPROCESSING'}
            </span>
          </div>
        )}
      </div>

      {/* Main Title Banner */}
      <div>
        <h2 className="font-headline-lg text-headline-lg text-on-surface mb-1">
          {createdBaseId ? 'Configure Processing Pipeline' : 'Start New RAG Base'}
        </h2>
        <p className="text-on-surface-variant text-body-md">
          {createdBaseId
            ? 'Define how your data is segmented and represented in vector space for optimal RAG retrieval.'
            : 'Provide metadata and upload documents to create vector embeddings for RAG.'}
        </p>
      </div>

      {error && (
        <div className="p-3.5 rounded-xl border text-sm font-code-md bg-error-container/40 border-error text-error flex items-center gap-2">
          <span className="material-symbols-outlined text-lg">error</span>
          <span>{error}</span>
        </div>
      )}

      {warning && (
        <div className="p-3.5 rounded-xl border text-sm font-code-md bg-tertiary-container/30 border-tertiary text-tertiary flex items-center gap-2">
          <span className="material-symbols-outlined text-lg font-bold">warning</span>
          <span>{warning}</span>
        </div>
      )}

      {/* Live Processing Card when createdBaseId is set */}
      {createdBaseId && (
        <div className="bg-surface-container-high/60 border border-outline-variant/80 rounded-xl p-5 space-y-4 animate-fade-in shadow-xl">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              {statusInfo.isProcessing ? (
                <span className="material-symbols-outlined animate-spin text-amber-400 text-xl">sync</span>
              ) : statusInfo.isVectorized ? (
                <span className="material-symbols-outlined text-secondary text-xl">check_circle</span>
              ) : statusInfo.isPreprocessed ? (
                <span className="material-symbols-outlined text-secondary text-xl">task_alt</span>
              ) : (
                <span className="material-symbols-outlined text-error text-xl">error</span>
              )}
              <div>
                <h4 className="font-semibold text-on-surface text-body-md">{name}</h4>
                <p className={`text-xs font-code-sm ${statusInfo.color}`}>{statusInfo.text}</p>
              </div>
            </div>
          </div>

          {/* Stepper Progress Bar */}
          {(() => {
            const sLower = (currentStatus || '').toLowerCase();
            const isStep2Done = sLower.includes('preprocess') || statusInfo.isPreprocessed || chunkingInitiated || sLower.includes('chunk') || statusInfo.isVectorized;
            const isStep2Active = sLower.includes('extract');

            const isStep3Done = statusInfo.isPreprocessed || chunkingInitiated || sLower.includes('chunk') || statusInfo.isVectorized;
            const isStep3Active = sLower.includes('preprocess') && !statusInfo.isPreprocessed;

            const isStep4Done = statusInfo.isVectorized;
            const isStep4Active = chunkingInitiated || sLower.includes('chunk');

            return (
              <div className="grid grid-cols-4 gap-2 text-center text-xs font-code-sm pt-2">
                <div className="bg-secondary/20 border border-secondary/40 text-secondary p-2 rounded-lg font-bold">
                  1. Ingestion
                </div>
                <div className={`p-2 rounded-lg border font-bold ${
                  isStep2Done
                    ? 'bg-secondary/20 border-secondary/40 text-secondary'
                    : isStep2Active
                    ? 'bg-amber-400/20 border-amber-400/50 text-amber-400'
                    : 'bg-surface-variant/30 border-outline-variant/30 text-outline'
                }`}>
                  2. Extraction
                </div>
                <div className={`p-2 rounded-lg border font-bold ${
                  isStep3Done
                    ? 'bg-secondary/20 border-secondary/40 text-secondary'
                    : isStep3Active
                    ? 'bg-amber-400/20 border-amber-400/50 text-amber-400'
                    : 'bg-surface-variant/30 border-outline-variant/30 text-outline'
                }`}>
                  3. Preprocessing
                </div>
                <div className={`p-2 rounded-lg border font-bold ${
                  isStep4Done
                    ? 'bg-secondary/20 border-secondary/40 text-secondary'
                    : isStep4Active
                    ? 'bg-amber-400/20 border-amber-400/50 text-amber-400'
                    : 'bg-surface-variant/30 border-outline-variant/30 text-outline'
                }`}>
                  4. Vector Store
                </div>
              </div>
            );
          })()}
        </div>
      )}

      {/* ── STEP 03: CONFIGURE PROCESSING PIPELINE (Shown when preprocessing completes) ── */}
      {createdBaseId && (statusInfo.isPreprocessed || statusInfo.isVectorized || chunkingInitiated) ? (
        <div className="space-y-6 animate-fade-in">
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
            {/* Left Column: Primary Config */}
            <div className="lg:col-span-7 space-y-6">
              {/* Chunking Strategy Card */}
              <div className="bg-surface-container p-6 rounded-xl border border-outline-variant shadow-xl">
                <div className="flex items-center gap-2 mb-6">
                  <span className="material-symbols-outlined text-primary">data_array</span>
                  <h3 className="font-headline-sm text-headline-sm text-on-surface">Chunking Strategy</h3>
                </div>

                <div className="space-y-4">
                  <label className="block text-label-caps text-on-surface-variant mb-1">STRATEGY MODEL</label>
                  <select
                    disabled={chunkingInitiated || statusInfo.isVectorized}
                    value={chunkingStrategy}
                    onChange={(e) => setChunkingStrategy(e.target.value)}
                    className="w-full bg-surface-container-highest border border-outline-variant text-on-surface rounded-lg p-3 font-body-md focus:ring-1 focus:ring-primary outline-none appearance-none cursor-pointer disabled:opacity-50"
                  >
                    <option value="recursive">Recursive</option>
                    <option value="fixed">Fixed</option>
                    <option value="semantic">Semantic</option>
                    <option value="parent_child">Parent-Child</option>
                    <option value="agentic">Agentic</option>
                  </select>

                  {/* Strategy Customization Panel */}
                  <div className="mt-6 bg-[#060e20]/60 p-5 rounded-lg border border-outline-variant space-y-5">
                    {chunkingStrategy === 'recursive' || chunkingStrategy === 'fixed' ? (
                      <>
                        <div className="grid grid-cols-2 gap-4">
                          <div>
                            <label className="block text-label-caps text-on-surface-variant mb-2">CHUNK SIZE (TOKENS)</label>
                            <input
                              type="number"
                              disabled={chunkingInitiated || statusInfo.isVectorized}
                              value={chunkSize}
                              onChange={(e) => setChunkSize(e.target.value)}
                              className="w-full bg-[#060e20] border border-outline-variant text-slate-100 rounded-lg p-3 font-code-md focus:border-primary transition-colors disabled:opacity-50"
                            />
                          </div>
                          <div>
                            <label className="block text-label-caps text-on-surface-variant mb-2">CHUNK OVERLAP</label>
                            <input
                              type="number"
                              disabled={chunkingInitiated || statusInfo.isVectorized}
                              value={chunkOverlap}
                              onChange={(e) => setChunkOverlap(e.target.value)}
                              className="w-full bg-[#060e20] border border-outline-variant text-slate-100 rounded-lg p-3 font-code-md focus:border-primary transition-colors disabled:opacity-50"
                            />
                          </div>
                        </div>
                        {chunkingStrategy === 'recursive' && (
                          <div>
                            <label className="block text-label-caps text-on-surface-variant mb-2">SEPARATORS (ARRAY)</label>
                            <textarea
                              rows="3"
                              disabled={chunkingInitiated || statusInfo.isVectorized}
                              value={separatorsText}
                              onChange={(e) => setSeparatorsText(e.target.value)}
                              className="w-full bg-[#060e20] border border-outline-variant text-slate-100 rounded-lg p-3 font-code-md focus:border-primary transition-colors disabled:opacity-50"
                              spellCheck="false"
                            ></textarea>
                            <p className="text-xs text-on-surface-variant mt-2">Ordered by priority for splitting hierarchy.</p>
                          </div>
                        )}
                      </>
                    ) : chunkingStrategy === 'semantic' ? (
                      <div className="grid grid-cols-2 gap-4">
                        <div>
                          <label className="block text-label-caps text-on-surface-variant mb-2">BREAKPOINT THRESHOLD</label>
                          <input
                            type="number"
                            step="0.05"
                            disabled={chunkingInitiated || statusInfo.isVectorized}
                            value={breakpointThreshold}
                            onChange={(e) => setBreakpointThreshold(e.target.value)}
                            className="w-full bg-[#060e20] border border-outline-variant text-slate-100 rounded-lg p-3 font-code-md focus:border-primary transition-colors disabled:opacity-50"
                          />
                        </div>
                      </div>
                    ) : chunkingStrategy === 'parent_child' ? (
                      <div className="grid grid-cols-2 gap-4">
                        <div>
                          <label className="block text-label-caps text-on-surface-variant mb-2">PARENT CHUNK SIZE</label>
                          <input
                            type="number"
                            disabled={chunkingInitiated || statusInfo.isVectorized}
                            value={parentChunkSize}
                            onChange={(e) => setParentChunkSize(e.target.value)}
                            className="w-full bg-[#060e20] border border-outline-variant text-slate-100 rounded-lg p-3 font-code-md focus:border-primary transition-colors disabled:opacity-50"
                          />
                        </div>
                        <div>
                          <label className="block text-label-caps text-on-surface-variant mb-2">CHILD CHUNK SIZE</label>
                          <input
                            type="number"
                            disabled={chunkingInitiated || statusInfo.isVectorized}
                            value={childChunkSize}
                            onChange={(e) => setChildChunkSize(e.target.value)}
                            className="w-full bg-[#060e20] border border-outline-variant text-slate-100 rounded-lg p-3 font-code-md focus:border-primary transition-colors disabled:opacity-50"
                          />
                        </div>
                      </div>
                    ) : chunkingStrategy === 'agentic' ? (
                      <div className="space-y-3">
                        <label className="block text-label-caps text-on-surface-variant">AGENTIC SYSTEM PROMPT</label>
                        <div className="bg-[#060e20] p-4 rounded border border-outline-variant font-code-sm text-xs text-secondary overflow-x-auto whitespace-pre leading-relaxed">
{`# Agentic Chunking System Prompt
You are a context-aware segmenter. 
Review the text block and split only at 
logical semantic boundaries. Preserve technical terms, 
code blocks, and list integrity.`}
                        </div>
                        <p className="text-xs text-on-surface-variant">System prompt passed to LLM segmenter for logical boundary decisions.</p>
                      </div>
                    ) : null}
                  </div>
                </div>
              </div>

              {/* Embedding Mode Card */}
              <div className="bg-surface-container p-6 rounded-xl border border-outline-variant shadow-xl space-y-6">
                <div className="flex items-center gap-2 mb-2">
                  <span className="material-symbols-outlined text-secondary">scatter_plot</span>
                  <h3 className="font-headline-sm text-headline-sm text-on-surface">Embedding Configuration</h3>
                </div>

                <div className="space-y-6">
                  <div>
                    <label className="block text-label-caps text-on-surface-variant mb-2">EMBEDDING MODE</label>
                    <div className="flex gap-2">
                      {['dense', 'sparse', 'hybrid'].map((mode) => (
                        <button
                          key={mode}
                          type="button"
                          disabled={chunkingInitiated || statusInfo.isVectorized}
                          onClick={() => setEmbeddingMode(mode)}
                          className={`flex-1 py-2.5 px-4 rounded-lg font-bold text-xs uppercase tracking-wider transition-all cursor-pointer ${
                            embeddingMode === mode
                              ? 'border-2 border-primary bg-primary/10 text-primary'
                              : 'border border-outline-variant text-on-surface-variant hover:bg-surface-variant'
                          }`}
                        >
                          {mode}
                        </button>
                      ))}
                    </div>
                  </div>

                  <div>
                    <label className="block text-label-caps text-on-surface-variant mb-2">ACTIVE MODELS</label>
                    <div className="bg-surface-container-highest border border-outline-variant rounded-lg p-3 min-h-[48px] flex flex-wrap items-center gap-2 relative">
                      {activeModels.map((model) => (
                        <div
                          key={model}
                          className="flex items-center gap-2 px-2.5 py-1 bg-secondary-container/20 border border-secondary text-secondary rounded text-xs font-label-caps"
                        >
                          <span>{model}</span>
                          {!chunkingInitiated && !statusInfo.isVectorized && activeModels.length > 1 && (
                            <span
                              onClick={() => removeModelTag(model)}
                              className="material-symbols-outlined text-xs cursor-pointer hover:text-error"
                            >
                              close
                            </span>
                          )}
                        </div>
                      ))}

                      {!chunkingInitiated && !statusInfo.isVectorized && (
                        <div className="ml-auto relative">
                          <button
                            type="button"
                            onClick={() => setShowModelDropdown(!showModelDropdown)}
                            className="text-primary text-xs font-bold hover:underline flex items-center gap-1 cursor-pointer"
                          >
                            <span className="material-symbols-outlined text-xs">add_circle</span>
                            Add Model
                          </button>

                          {showModelDropdown && (
                            <div className="absolute right-0 top-8 z-30 w-72 bg-surface-container-high border border-outline-variant rounded-xl shadow-2xl p-2 space-y-1">
                              {KNOWN_EMBEDDING_MODELS.map((m) => (
                                <button
                                  key={m}
                                  type="button"
                                  onClick={() => addModelTag(m)}
                                  className="w-full text-left px-3 py-2 text-xs font-code-sm text-on-surface hover:bg-surface-variant rounded-lg truncate"
                                >
                                  {m}
                                </button>
                              ))}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {/* Right Column: Batching & Advanced */}
            <div className="lg:col-span-5 space-y-6">
              {/* Batch Performance Section */}
              <div className="bg-surface-container p-6 rounded-xl border border-outline-variant shadow-xl">
                <div className="flex items-center justify-between mb-6">
                  <div className="flex items-center gap-2">
                    <span className="material-symbols-outlined text-tertiary">speed</span>
                    <h3 className="font-headline-sm text-headline-sm text-on-surface">Batch Performance</h3>
                  </div>
                  <span className="flex h-2.5 w-2.5 rounded-full bg-secondary shadow-[0_0_8px_#4fdbc8]"></span>
                </div>

                <div className="space-y-4 text-xs font-code-sm">
                  <div className="flex items-center justify-between gap-4 p-4 rounded-lg bg-[#060e20] border border-outline-variant">
                    <span className="text-on-surface-variant">Chunks per Batch</span>
                    <input
                      type="number"
                      disabled={chunkingInitiated || statusInfo.isVectorized}
                      value={chunksPerBatch}
                      onChange={(e) => setChunksPerBatch(e.target.value)}
                      className="w-20 bg-surface-container-highest border-none text-right font-code-md rounded p-1 text-primary focus:ring-1 focus:ring-primary"
                    />
                  </div>
                  <div className="flex items-center justify-between gap-4 p-4 rounded-lg bg-[#060e20] border border-outline-variant">
                    <span className="text-on-surface-variant">Pages per Batch</span>
                    <input
                      type="number"
                      disabled={chunkingInitiated || statusInfo.isVectorized}
                      value={pagesPerBatch}
                      onChange={(e) => setPagesPerBatch(e.target.value)}
                      className="w-20 bg-surface-container-highest border-none text-right font-code-md rounded p-1 text-primary focus:ring-1 focus:ring-primary"
                    />
                  </div>

                  <div className="mt-4 p-4 rounded-lg bg-tertiary-container/10 border border-tertiary/20 text-xs">
                    <p className="text-tertiary flex items-center gap-2 mb-1 font-bold">
                      <span className="material-symbols-outlined text-xs">info</span>
                      ESTIMATED THROUGHPUT
                    </p>
                    <p className="text-on-surface-variant leading-relaxed">
                      Estimated processing speed: <span className="text-on-surface font-bold">14.2 MB/sec</span> based on current CPU hardware.
                    </p>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Retrieval Testing Section for Active Vectorized Base */}
          {statusInfo.isVectorized && (
            <div className="bg-surface-container-low border border-secondary/40 rounded-xl p-6 shadow-2xl space-y-6 animate-fade-in">
              <div className="flex items-center justify-between border-b border-outline-variant/40 pb-4">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-full bg-secondary-container/40 flex items-center justify-center border border-secondary/30">
                    <span className="material-symbols-outlined text-secondary text-xl">search_check</span>
                  </div>
                  <div>
                    <h3 className="font-headline-sm text-headline-sm text-on-surface">Retrieval Testing</h3>
                    <p className="text-xs text-outline font-code-sm">Test live vector retrieval queries directly against Qdrant collection</p>
                  </div>
                </div>
                <span className="px-3 py-1 bg-secondary-container/20 text-secondary text-xs font-code-md rounded-lg border border-secondary/30 font-bold flex items-center gap-1.5">
                  <span className="w-2 h-2 rounded-full bg-secondary animate-pulse"></span>
                  Qdrant Vector Store Active
                </span>
              </div>

              {searchError && (
                <div className="p-3.5 rounded-xl border text-sm font-code-md bg-error-container/40 border-error text-error flex items-center gap-2">
                  <span className="material-symbols-outlined text-lg">error</span>
                  <span>{searchError}</span>
                </div>
              )}

              <form onSubmit={handleExecuteSearch} className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-end">
                <div className="lg:col-span-12 space-y-2">
                  <label className="block font-label-caps text-label-caps text-primary uppercase">
                    Search Query
                  </label>
                  <input
                    type="text"
                    required
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder="Enter query to test vector similarity..."
                    className="w-full bg-[#060e20] border border-outline-variant text-slate-100 rounded-lg px-4 py-3 font-body-md focus:border-primary transition-all outline-none"
                  />
                </div>

                <div className="lg:col-span-9 grid grid-cols-2 gap-6 bg-[#060e20]/60 p-4 rounded-xl border border-outline-variant/60">
                  <div className="space-y-2">
                    <div className="flex justify-between text-xs font-label-caps text-on-surface-variant uppercase">
                      <span>Top K Results</span>
                      <span className="text-primary font-bold">{searchTopK}</span>
                    </div>
                    <input
                      type="range"
                      min="1"
                      max="50"
                      value={searchTopK}
                      onChange={(e) => setSearchTopK(e.target.value)}
                      className="w-full h-1.5 bg-surface-variant rounded-lg appearance-none cursor-pointer accent-primary"
                    />
                  </div>

                  <div className="space-y-2">
                    <div className="flex justify-between text-xs font-label-caps text-on-surface-variant uppercase">
                      <span>Score Threshold</span>
                      <span className="text-primary font-bold">{Number(searchThreshold).toFixed(2)}</span>
                    </div>
                    <input
                      type="range"
                      min="0"
                      max="1"
                      step="0.05"
                      value={searchThreshold}
                      onChange={(e) => setSearchThreshold(e.target.value)}
                      className="w-full h-1.5 bg-surface-variant rounded-lg appearance-none cursor-pointer accent-primary"
                    />
                  </div>
                </div>

                <div className="lg:col-span-3">
                  <button
                    type="submit"
                    disabled={searching}
                    className="w-full bg-primary text-on-primary font-bold py-3.5 px-4 rounded-lg flex items-center justify-center gap-2 hover:bg-primary-fixed active:scale-95 transition-all shadow-lg shadow-primary/20 cursor-pointer disabled:opacity-50"
                  >
                    {searching ? (
                      <>
                        <span className="material-symbols-outlined animate-spin text-lg">sync</span>
                        <span>Searching...</span>
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

              {searchResults && (
                <div className="space-y-4 pt-4 border-t border-outline-variant/40">
                  <div className="flex items-center gap-2 font-headline-sm text-headline-sm text-on-surface">
                    <span>Search Matches</span>
                    <span className="px-2.5 py-0.5 bg-secondary-container/20 text-secondary text-xs font-code-md rounded-lg border border-secondary/30 font-bold">
                      Found {searchResults.results_count || (searchResults.results ? searchResults.results.length : 0)} Chunks
                    </span>
                  </div>

                  {(!searchResults.results || searchResults.results.length === 0) ? (
                    <div className="bg-[#060e20] p-6 rounded-xl border border-outline-variant/40 text-center space-y-1">
                      <p className="text-on-surface font-semibold">No relevant vector chunks found.</p>
                      <p className="text-xs text-outline font-code-sm">Try lowering the Score Threshold or adjusting the query text.</p>
                    </div>
                  ) : (
                    searchResults.results.map((res, idx) => {
                      const scorePct = Math.min(100, Math.max(0, (res.score || 0) * 100)).toFixed(1);
                      return (
                        <div key={res.chunk_id || idx} className="bg-surface-container border border-outline-variant/60 rounded-xl overflow-hidden shadow-lg">
                          <div className="flex flex-col sm:flex-row">
                            <div className="sm:w-28 bg-surface-container-high flex flex-col items-center justify-center border-b sm:border-b-0 sm:border-r border-outline-variant/40 p-4">
                              <span className="font-label-caps text-label-caps text-on-surface-variant uppercase mb-1">Score</span>
                              <div className="font-code-md text-headline-sm font-bold text-primary">
                                {(res.score !== undefined ? res.score : 0).toFixed(3)}
                              </div>
                              <div className="w-16 h-1.5 bg-primary/20 mt-2 rounded-full overflow-hidden">
                                <div className="h-full bg-primary" style={{ width: `${scorePct}%` }}></div>
                              </div>
                            </div>
                            <div className="flex-1 p-5 space-y-4">
                              <div className="font-code-md text-xs text-on-surface leading-relaxed bg-[#060e20] p-4 rounded-lg border border-outline-variant/40 whitespace-pre-wrap select-text">
                                {res.chunk_text}
                              </div>
                              <div className="flex flex-wrap gap-2 text-xs font-code-sm">
                                <div className="flex items-center gap-1.5 px-3 py-1 bg-surface-variant/40 rounded border border-outline-variant/30 text-on-surface-variant">
                                  <span className="material-symbols-outlined text-[14px]">id_card</span>
                                  <span className="opacity-60 uppercase">Chunk:</span> {(res.chunk_id || '').substring(0, 8)}...
                                </div>
                                <div className="flex items-center gap-1.5 px-3 py-1 bg-surface-variant/40 rounded border border-outline-variant/30 text-on-surface-variant">
                                  <span className="material-symbols-outlined text-[14px]">model_training</span>
                                  <span className="opacity-60 uppercase">Model:</span> {res.embedding_model || 'MiniLM-L12'}
                                </div>
                                {res.chunk_index !== undefined && (
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
          )}

          {/* Sticky Footer Navigation for Step 03 */}
          <div className="bg-surface-container border border-outline-variant rounded-xl p-5 flex items-center justify-between shadow-2xl">
            <button
              onClick={() => navigate('/rag')}
              className="flex items-center gap-2 text-on-surface-variant hover:text-on-surface font-bold transition-colors cursor-pointer text-body-md"
            >
              <span className="material-symbols-outlined">arrow_back</span>
              Back to Bases
            </button>

            <div className="flex items-center gap-4">
              {!statusInfo.isVectorized && (
                <button
                  type="button"
                  disabled={loading || chunkingInitiated}
                  onClick={handleInitiateChunkingPipeline}
                  className="bg-primary text-on-primary px-8 py-3 rounded-lg font-bold hover:bg-primary-fixed active:scale-95 transition-all shadow-lg shadow-primary/20 flex items-center gap-2 text-body-md cursor-pointer disabled:opacity-50"
                >
                  {loading || chunkingInitiated ? (
                    <>
                      <span className="material-symbols-outlined animate-spin text-sm">sync</span>
                      Processing Chunking & Embeddings...
                    </>
                  ) : (
                    'Initiate Chunking & Finalize Base'
                  )}
                </button>
              )}
            </div>
          </div>
        </div>
      ) : (
        /* ── STEP 01/02 FORM: METADATA & FILES (Disabled after submission) ── */
        <div className="bg-surface-container-low border border-outline-variant rounded-xl p-6 shadow-2xl space-y-6">
          <form onSubmit={handleInitialSubmit} className="space-y-5">
            <div>
              <label className="block font-label-caps text-label-caps text-on-surface-variant mb-1">RAG Base Name</label>
              <input
                type="text"
                required
                disabled={!!createdBaseId || loading}
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g., project-docs"
                className="input-inset w-full px-4 py-2.5 rounded-lg border border-outline-variant font-code-md text-slate-100 placeholder:text-slate-500 bg-[#060e20] disabled:opacity-50 disabled:cursor-not-allowed"
              />
            </div>

            <div>
              <label className="block font-label-caps text-label-caps text-on-surface-variant mb-1">Description</label>
              <textarea
                rows="3"
                disabled={!!createdBaseId || loading}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Technical documentation for the project..."
                className="input-inset w-full px-4 py-2.5 rounded-lg border border-outline-variant font-code-md text-slate-100 placeholder:text-slate-500 bg-[#060e20] disabled:opacity-50 disabled:cursor-not-allowed"
              ></textarea>
            </div>

            <div>
              <div className="flex justify-between items-center mb-2">
                <label className="block font-label-caps text-label-caps text-on-surface-variant">
                  Upload Documents (PDF, DOC, DOCX, TXT)
                </label>
                <span className="text-[11px] text-outline font-code-sm">
                  Max 10 files • Up to 20 MB each
                </span>
              </div>

              {/* Clickable Drag & Drop Zone */}
              <div
                onClick={handleContainerClick}
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
                className={`border-2 border-dashed rounded-xl p-6 text-center transition-all cursor-pointer relative flex flex-col items-center justify-center gap-3 select-none ${
                  createdBaseId || loading
                    ? 'opacity-40 cursor-not-allowed border-outline-variant bg-surface-container-high/20'
                    : dragActive
                    ? 'border-primary bg-primary-container/20 scale-[1.01]'
                    : 'border-outline-variant bg-surface-container-high/40 hover:bg-surface-container-high/70 hover:border-primary/50'
                }`}
              >
                <input
                  ref={fileInputRef}
                  type="file"
                  multiple
                  disabled={!!createdBaseId || loading}
                  accept=".pdf,.doc,.docx,.txt"
                  onChange={handleFileChange}
                  className="hidden"
                />

                <div className="w-12 h-12 rounded-full bg-surface-variant/80 flex items-center justify-center text-primary pointer-events-none">
                  <span className="material-symbols-outlined text-2xl">upload_file</span>
                </div>
                <div className="pointer-events-none">
                  <p className="text-body-md font-semibold text-on-surface">
                    {createdBaseId ? 'Upload locked while processing' : <>Drag and drop files here, or <span className="text-primary font-bold underline">browse</span></>}
                  </p>
                  <p className="text-xs text-outline font-code-sm mt-1">
                    Supported formats: .pdf, .doc, .docx, .txt (max 10 files, ≤ 20 MB each)
                  </p>
                </div>
              </div>

              {/* Selected File Badges / List */}
              {files.length > 0 && (
                <div className="mt-4 space-y-2">
                  <div className="flex items-center justify-between text-xs text-outline font-code-sm">
                    <span>Selected Documents ({files.length} / {MAX_FILES})</span>
                    {!createdBaseId && !loading && (
                      <button
                        type="button"
                        onClick={() => {
                          setFiles([]);
                          setWarning('');
                        }}
                        className="text-error hover:underline cursor-pointer"
                      >
                        Clear all
                      </button>
                    )}
                  </div>

                  <div className="max-h-48 overflow-y-auto space-y-2 pr-1">
                    {files.map((file, index) => (
                      <div
                        key={`${file.name}-${index}`}
                        className="flex items-center justify-between p-3 rounded-lg bg-surface-container-high border border-outline-variant/60 text-xs font-code-sm text-on-surface"
                      >
                        <div className="flex items-center gap-3 truncate pr-2">
                          <span className="material-symbols-outlined text-secondary text-base">
                            {getFileIcon(file.name)}
                          </span>
                          <div className="truncate">
                            <p className="truncate font-medium text-on-surface">{file.name}</p>
                            <p className="text-[10px] text-outline">{formatFileSize(file.size)}</p>
                          </div>
                        </div>
                        {!createdBaseId && !loading && (
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              removeFile(index);
                            }}
                            className="text-outline hover:text-error transition-colors p-1 rounded cursor-pointer"
                            title="Remove file"
                          >
                            <span className="material-symbols-outlined text-sm">close</span>
                          </button>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            <div className="flex justify-end gap-3 pt-4 border-t border-outline-variant">
              <button
                type="button"
                onClick={() => navigate('/rag')}
                className="px-4 py-2.5 rounded-lg border border-outline-variant text-on-surface-variant hover:bg-surface-variant transition-colors text-body-md font-medium cursor-pointer"
              >
                Cancel
              </button>
              {!createdBaseId && (
                <button
                  type="submit"
                  disabled={loading || files.length === 0}
                  className="px-6 py-2.5 rounded-lg bg-primary text-on-primary font-bold hover:bg-primary-fixed transition-colors text-body-md flex items-center gap-2 disabled:opacity-50 cursor-pointer"
                >
                  {loading ? (
                    <>
                      <span className="material-symbols-outlined animate-spin text-sm">sync</span>
                      Ingesting {files.length} {files.length === 1 ? 'File' : 'Files'}...
                    </>
                  ) : (
                    `Create Base (${files.length} ${files.length === 1 ? 'file' : 'files'})`
                  )}
                </button>
              )}
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
