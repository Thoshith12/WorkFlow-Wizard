import React from 'react';
import { Outlet } from 'react-router-dom';
import Sidebar from './Sidebar';
import Header from './Header';

export default function AppLayout() {
  return (
    <div className="h-screen w-screen flex overflow-hidden fixed inset-0 z-50 bg-background text-on-surface font-body-md text-body-md">
      <Sidebar />
      <main className="ml-72 flex-1 flex flex-col h-full bg-background dot-matrix relative">
        <Header />
        <div className="flex-1 overflow-y-auto p-gutter relative z-0">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
