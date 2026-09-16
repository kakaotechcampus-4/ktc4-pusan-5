import { useState } from 'react';
import { Route, Routes } from 'react-router-dom';
import { PageShell } from '@/components/layout/PageShell';
import { HomePage } from '@/features/home/HomePage';
import { StockBriefingPage } from '@/features/stock/StockBriefingPage';
import { ConceptPage } from '@/features/concepts/ConceptPage';
import { LoginModal } from '@/features/auth/LoginModal';

export function App() {
  const [loginOpen, setLoginOpen] = useState(false);
  const [loggedIn, setLoggedIn] = useState(false);

  return (
    <>
      <PageShell
        loggedIn={loggedIn}
        onLoginClick={() => setLoginOpen(true)}
        onLogoutClick={() => setLoggedIn(false)}
      >
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/stock/:code" element={<StockBriefingPage />} />
          <Route path="/concepts/:slug" element={<ConceptPage />} />
        </Routes>
      </PageShell>
      <LoginModal
        key={String(loginOpen)}
        open={loginOpen}
        onClose={() => setLoginOpen(false)}
        onSuccess={() => setLoggedIn(true)}
      />
    </>
  );
}
