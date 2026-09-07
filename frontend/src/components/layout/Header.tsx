import { NavLink, Link } from 'react-router-dom';
import { cn } from '@/lib/cn';

const NAV = [
  { to: '/', label: '홈' },
  { to: '/stock/005930', label: '종목 브리핑' },
];

export function Header() {
  return (
    <header className="sticky top-0 z-30 border-b border-divider bg-canvas">
      <nav className="mx-auto flex max-w-page items-center gap-6 px-6 py-3">
        <Link to="/" className="mr-auto no-underline text-ink">
          <div className="text-h3 font-bold leading-none tracking-brand">BASIS</div>
          <div className="text-micro font-semibold tracking-wordmark text-neutral-600">
            MARKET LITERACY
          </div>
        </Link>
        {NAV.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              cn('text-sm no-underline hover:text-brand', isActive ? 'text-brand' : 'text-ink')
            }
          >
            {item.label}
          </NavLink>
        ))}
      </nav>
    </header>
  );
}
