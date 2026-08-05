import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider } from './context/AuthContext';
import LoginPage from './pages/LoginPage';
import RagListPage from './pages/RagListPage';
import RagCreatePage from './pages/RagCreatePage';
import RagSearchPage from './pages/RagSearchPage';
import ToolsPage from './pages/ToolsPage';
import AppLayout from './components/AppLayout';
import ProtectedRoute from './components/ProtectedRoute';

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />

          <Route
            element={
              <ProtectedRoute>
                <AppLayout />
              </ProtectedRoute>
            }
          >
            <Route path="/" element={<Navigate to="/rag" replace />} />
            <Route path="/rag" element={<RagListPage />} />
            <Route path="/rag/create" element={<RagCreatePage />} />
            <Route path="/rag/search" element={<RagSearchPage />} />
            <Route path="/tools" element={<ToolsPage />} />
            <Route path="*" element={<Navigate to="/rag" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
