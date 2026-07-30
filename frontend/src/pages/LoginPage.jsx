import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

export default function LoginPage() {
  const [username, setUsername] = useState('admin');
  const [password, setPassword] = useState('admin');
  const [remember, setRemember] = useState(true);
  const [loading, setLoading] = useState(false);
  const [alert, setAlert] = useState({ show: false, message: '', type: 'error' });

  const { login, isAuthenticated } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    if (isAuthenticated) {
      navigate('/rag', { replace: true });
    }
  }, [isAuthenticated, navigate]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setAlert({ show: false, message: '', type: 'error' });

    if (!username.trim() || !password) {
      setAlert({ show: true, message: 'Please enter both system email/username and access key.', type: 'error' });
      return;
    }

    setLoading(true);

    try {
      const response = await fetch('/api/auth/admin-login', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json'
        },
        body: JSON.stringify({
          username: username.trim(),
          password: password
        })
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        const errorMsg = errorData.detail || errorData.message || `Authentication failed (Status ${response.status})`;
        throw new Error(errorMsg);
      }

      const data = await response.json();
      login(data, username.trim());

      setAlert({ show: true, message: 'Authentication successful!', type: 'success' });
      setTimeout(() => {
        navigate('/rag', { replace: true });
      }, 300);

    } catch (err) {
      console.error('Login error:', err);
      setAlert({ show: true, message: err.message || 'Unable to connect to authentication service.', type: 'error' });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center p-4 relative bg-background text-on-surface font-body-md text-body-md">
      <div className="fixed inset-0 z-0 opacity-20 pointer-events-none"></div>

      <main className="relative z-10 w-full max-w-[480px]">
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center mb-4 p-3 rounded-xl bg-surface-container-high border border-outline-variant">
            <span className="material-symbols-outlined text-primary text-4xl">auto_fix</span>
          </div>
          <h1 className="font-headline-lg text-headline-lg text-on-surface brand-glow">Workflow Wizard</h1>
          <p className="font-body-md text-on-surface-variant mt-2 uppercase tracking-widest text-[10px]">Technical Orchestration Suite</p>
        </div>

        <div className="login-card p-8 rounded-xl">
          <div className="mb-6">
            <h2 className="font-headline-sm text-headline-sm text-on-surface mb-1">Welcome back</h2>
            <p className="font-body-md text-on-surface-variant">Access your node-based orchestration environment.</p>
          </div>

          {alert.show && (
            <div className={`mb-4 p-3 rounded-lg border text-sm font-code-md ${
              alert.type === 'error'
                ? 'bg-error-container/40 border-error text-error'
                : 'bg-secondary-container/40 border-secondary text-secondary'
            }`}>
              {alert.message}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-5">
            <div>
              <label className="block font-label-caps text-label-caps text-on-surface-variant mb-2" htmlFor="email">System Email</label>
              <div className="relative">
                <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-outline text-lg">alternate_email</span>
                <input
                  id="email"
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="admin"
                  className="input-inset w-full pl-10 pr-4 py-2.5 rounded-lg border border-outline-variant font-code-md text-on-surface placeholder:text-outline/50"
                />
              </div>
            </div>
            <div>
              <div className="flex justify-between items-center mb-2">
                <label className="block font-label-caps text-label-caps text-on-surface-variant" htmlFor="password">Access Key</label>
                <a className="font-label-caps text-label-caps text-primary hover:text-primary-fixed-dim transition-colors" href="#">Recover Key?</a>
              </div>
              <div className="relative">
                <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-outline text-lg">lock</span>
                <input
                  id="password"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••••••"
                  className="input-inset w-full pl-10 pr-4 py-2.5 rounded-lg border border-outline-variant font-code-md text-on-surface placeholder:text-outline/50"
                />
              </div>
            </div>
            <div className="flex items-center">
              <input
                id="remember"
                type="checkbox"
                checked={remember}
                onChange={(e) => setRemember(e.target.checked)}
                className="w-4 h-4 rounded border-outline-variant bg-surface-container text-primary focus:ring-primary focus:ring-offset-background"
              />
              <label className="ml-2 font-body-md text-on-surface-variant select-none" htmlFor="remember">Maintain session persistence</label>
            </div>
            <button
              type="submit"
              disabled={loading}
              className="primary-button-glow w-full py-3 px-4 bg-primary text-on-primary font-headline-sm text-[16px] rounded-lg font-bold flex items-center justify-center gap-2 group disabled:opacity-80 cursor-pointer"
            >
              {loading ? (
                <>
                  <span className="material-symbols-outlined animate-spin">sync</span> Initializing...
                </>
              ) : (
                <>
                  Sign In
                  <span className="material-symbols-outlined group-hover:translate-x-1 transition-transform">arrow_forward</span>
                </>
              )}
            </button>
          </form>

          <div className="relative my-8">
            <div className="absolute inset-0 flex items-center">
              <div className="w-full border-t border-outline-variant/30"></div>
            </div>
            <div className="relative flex justify-center">
              <span className="bg-[#1e293b] px-4 font-label-caps text-label-caps text-outline">Third-Party Auth</span>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <button type="button" className="flex items-center justify-center gap-2 py-2.5 px-4 rounded-lg bg-surface-container-highest border border-outline-variant hover:bg-surface-bright transition-all active:scale-[0.98]">
              <img className="w-5 h-5" alt="Google icon" src="https://lh3.googleusercontent.com/aida-public/AB6AXuBhkigemZd6EVWk0Omi9NLIhPUYTTjc8OYMln9dsttRGpKWtoSKziuQbgLhnXEbzJJViVzf7cjdWphYN_O_Fc1a1vt6PnuBu_KS-imCN8Lt5i4r1HW1of9Vt9FqYUoADh_eq9Y5SIFV_ieI1-drBk81GfMKO4dGEXpyw1s9478-fgD9H7hv7ST-GP0mQ9R5ED8106u0ubxRKw80jzcWQMvn4t4uEHc2PANdm6Z3YrD4oq0LDJUrIm2B"/>
              <span className="font-body-md font-semibold text-on-surface">Google</span>
            </button>
            <button type="button" className="flex items-center justify-center gap-2 py-2.5 px-4 rounded-lg bg-surface-container-highest border border-outline-variant hover:bg-surface-bright transition-all active:scale-[0.98]">
              <svg className="w-5 h-5 fill-on-surface" viewBox="0 0 24 24"><path d="M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12"></path></svg>
              <span className="font-body-md font-semibold text-on-surface">GitHub</span>
            </button>
          </div>
        </div>

        <div className="mt-8 flex flex-col items-center gap-4">
          <p className="font-body-md text-on-surface-variant">
            No developer account? <a className="text-secondary font-bold hover:underline" href="#">Provision Identity</a>
          </p>
          <div className="flex items-center gap-4 text-outline font-label-caps text-[9px] tracking-widest">
            <a className="hover:text-on-surface transition-colors" href="#">SERVICE STATUS: ONLINE</a>
            <span className="w-1.5 h-1.5 rounded-full bg-secondary-container animate-pulse shadow-[0_0_8px_#04b4a2]"></span>
            <a className="hover:text-on-surface transition-colors" href="#">ENCRYPTION: AES-256</a>
          </div>
        </div>
      </main>

      <div className="hidden xl:flex fixed right-12 top-1/2 -translate-y-1/2 flex-col gap-6 opacity-40">
        <div className="w-64 p-4 rounded-lg bg-surface-container-high border border-outline-variant shadow-lg rotate-3 translate-x-4">
          <div className="flex items-center gap-2 mb-3">
            <span className="material-symbols-outlined text-secondary text-sm">database</span>
            <span className="font-label-caps text-label-caps text-on-surface">Vector DB Source</span>
          </div>
          <div className="h-2 w-full bg-surface-container rounded mb-2"></div>
          <div className="h-2 w-2/3 bg-surface-container rounded"></div>
        </div>
        <div className="w-64 p-4 rounded-lg bg-surface-container-high border border-primary/40 shadow-lg -rotate-2 border-l-4 border-l-primary">
          <div className="flex items-center gap-2 mb-3">
            <span className="material-symbols-outlined text-primary text-sm">psychology</span>
            <span className="font-label-caps text-label-caps text-on-surface">LLM Logic Engine</span>
          </div>
          <div className="h-2 w-full bg-surface-container rounded mb-2"></div>
          <div className="h-2 w-1/2 bg-surface-container rounded"></div>
        </div>
      </div>
    </div>
  );
}
