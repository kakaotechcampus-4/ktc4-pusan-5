import { NavLink, Link } from 'react-router-dom';
import { cn } from '@/lib/cn';

const NAV = [
  { to: '/', label: '홈' },
  { to: '/stock/005930', label: '종목 브리핑' },
];

export function Header({
  loggedIn,
  onLoginClick,
  onLogoutClick,
}: {
  loggedIn?: boolean;
  onLoginClick?: () => void;
  onLogoutClick?: () => void;
}) {
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
          onClick={loggedIn ? onLogoutClick : onLoginClick}
        >
          {loggedIn ? '로그아웃' : '로그인'}
        </button>
      </nav>
    </header>
  );
}
