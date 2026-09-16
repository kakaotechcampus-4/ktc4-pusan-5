import { useState } from 'react';
import { Route, Routes } from 'react-router-dom';
import { PageShell } from '@/components/layout/PageShell';
import { HomePage } from '@/features/home/HomePage';
import { StockBriefingPage } from '@/features/stock/StockBriefingPage';
import { ConceptPage } from '@/features/concepts/ConceptPage';
import { LoginModal } from '@/features/auth/LoginModal';
import { KakaoCallbackPage } from '@/features/auth/KakaoCallbackPage';
import { AuthProvider } from '@/features/auth/AuthProvider';
import { useAuth } from '@/features/auth/useAuth';

function AppShell() {
  const [loginOpen, setLoginOpen] = useState(false);
  const { status, logout } = useAuth();

  return (
    <>
      <PageShell
        loggedIn={status === 'authenticated'}
        onLoginClick={() => setLoginOpen(true)}
        onLogoutClick={() => {
          void logout();
        }}
      >
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/stock/:code" element={<StockBriefingPage />} />
          <Route path="/concepts/:slug" element={<ConceptPage />} />
          <Route path="/oauth/kakao/callback" element={<KakaoCallbackPage />} />
        </Routes>
      </PageShell>
      <LoginModal open={loginOpen} onClose={() => setLoginOpen(false)} />
    </>
  );
}

export function App() {
  return (
    <AuthProvider>
      <AppShell />
    </AuthProvider>
  );
}
