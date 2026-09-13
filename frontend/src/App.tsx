import { Route, Routes } from 'react-router-dom';
import { PageShell } from '@/components/layout/PageShell';
import { HomePage } from '@/features/home/HomePage';
import { StockBriefingPage } from '@/features/stock/StockBriefingPage';

export function App() {
  return (
    <PageShell>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/stock/:code" element={<StockBriefingPage />} />
      </Routes>
    </PageShell>
  );
}
