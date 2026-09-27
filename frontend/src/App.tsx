import { Route, Routes } from 'react-router-dom';
import { PageShell } from '@/components/layout/PageShell';
import { HomePage } from '@/features/home/HomePage';
import { StockBriefingPage } from '@/features/stock/StockBriefingPage';
import { ConceptListPage } from '@/features/concepts/ConceptListPage';
import { ConceptPage } from '@/features/concepts/ConceptPage';
import { KakaoCallbackPage } from '@/features/auth/KakaoCallbackPage';
import { AuthProvider } from '@/features/auth/AuthProvider';

export function App() {
  return (
    <AuthProvider>
      <PageShell>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/stock/:code" element={<StockBriefingPage />} />
          <Route path="/concepts" element={<ConceptListPage />} />
          <Route path="/concepts/:slug" element={<ConceptPage />} />
          <Route path="/oauth/kakao/callback" element={<KakaoCallbackPage />} />
        </Routes>
      </PageShell>
    </AuthProvider>
  );
}
