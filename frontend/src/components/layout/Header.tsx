import { useState } from 'react';
import { NavLink, Link } from 'react-router-dom';
import { cn } from '@/lib/cn';
import { useAuth } from '@/features/auth/useAuth';
import { LoginModal } from '@/features/auth/LoginModal';

const NAV = [
  { to: '/', label: '홈' },
  { to: '/stock/005930', label: '종목 브리핑' },
];

export function Header() {
  const { status, logout } = useAuth();
  const [loginOpen, setLoginOpen] = useState(false);
  const loggedIn = status === 'authenticated';

  return (
    <header className="border-divider bg-canvas sticky top-0 z-30 border-b">
      <nav className="max-w-page mx-auto flex items-center gap-6 px-6 py-3">
        <Link to="/" className="text-ink mr-auto no-underline">
          <div className="text-h3 tracking-brand leading-none font-bold">BASIS</div>
          <div className="text-micro tracking-wordmark font-semibold text-neutral-600">
            MARKET LITERACY
          </div>
        </Link>
        {NAV.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              cn('hover:text-brand text-sm no-underline', isActive ? 'text-brand' : 'text-ink')
            }
          >
            {item.label}
          </NavLink>
        ))}
        <button
          type="button"
          className="text-ink hover:text-brand text-sm"
          onClick={loggedIn ? () => void logout() : () => setLoginOpen(true)}
        >
          {loggedIn ? '로그아웃' : '로그인'}
        </button>
      </nav>
      <LoginModal open={loginOpen} onClose={() => setLoginOpen(false)} />
    </header>
  );
}
