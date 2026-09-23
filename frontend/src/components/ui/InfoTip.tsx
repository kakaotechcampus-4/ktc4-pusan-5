import { useId, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

/** 스크롤 컨테이너에 잘리지 않는 개념 도움말. 호버·포커스·터치로 열 수 있다. */
export function InfoTip({ description }: { description: string }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const buttonRef = useRef<HTMLButtonElement>(null);
  const tooltipRef = useRef<HTMLSpanElement>(null);
  const closeTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  function show() {
    clearTimeout(closeTimer.current);
    setOpen(true);
  }

  function hide() {
    clearTimeout(closeTimer.current);
    closeTimer.current = setTimeout(() => {
      if (document.activeElement !== buttonRef.current) setOpen(false);
    }, 100);
  }

  useLayoutEffect(() => {
    if (!open) return;
    const position = () => {
      const button = buttonRef.current;
      const tooltip = tooltipRef.current;
      if (!button || !tooltip) return;
      const anchor = button.getBoundingClientRect();
      const box = tooltip.getBoundingClientRect();
      const gap = 8;
      const left = Math.max(
        gap,
        Math.min(anchor.left + (anchor.width - box.width) / 2, window.innerWidth - box.width - gap),
      );
      const above = anchor.top - box.height - gap;
      const top =
        above >= gap
          ? above
          : Math.max(gap, Math.min(anchor.bottom + gap, window.innerHeight - box.height - gap));
      tooltip.style.left = `${left}px`;
      tooltip.style.top = `${top}px`;
    };
    const dismiss = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    position();
    window.addEventListener('resize', position);
    window.addEventListener('scroll', position, true);
    document.addEventListener('keydown', dismiss);
    return () => {
      clearTimeout(closeTimer.current);
      window.removeEventListener('resize', position);
      window.removeEventListener('scroll', position, true);
      document.removeEventListener('keydown', dismiss);
    };
  }, [open, description]);

  return (
    <span className="inline-flex">
      <button
        ref={buttonRef}
        type="button"
        aria-label="개념 설명"
        aria-describedby={open ? id : undefined}
        onClick={show}
        onMouseEnter={show}
        onMouseLeave={hide}
        onFocus={show}
        onBlur={() => setOpen(false)}
        className="flex size-4 flex-none items-center justify-center rounded-full bg-neutral-200 text-xs leading-none font-semibold text-neutral-700 hover:bg-neutral-300"
      >
        ?
      </button>
      {open &&
        createPortal(
          <span
            ref={tooltipRef}
            id={id}
            role="tooltip"
            onMouseEnter={show}
            onMouseLeave={hide}
            className="border-divider bg-canvas fixed z-50 w-48 rounded-md border p-2 text-left text-xs leading-relaxed font-normal whitespace-normal text-neutral-700 shadow-md"
          >
            {description}
          </span>,
          document.body,
        )}
    </span>
  );
}
