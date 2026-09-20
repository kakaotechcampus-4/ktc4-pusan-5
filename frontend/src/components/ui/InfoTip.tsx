import { useState } from 'react';

/**
 * 개념 옆에 붙는 "?" 배지. 클릭하거나 포커스하면 한줄 개념 보여줌
 */
export function InfoTip({ description }: { description: string }) {
  const [open, setOpen] = useState(false);

  return (
    <span className="relative inline-flex">
      <button
        type="button"
        aria-label={`개념 설명: ${description}`}
        onClick={() => setOpen(true)}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        className="flex size-4 flex-none items-center justify-center rounded-full bg-neutral-200 text-xs leading-none font-semibold text-neutral-700 hover:bg-neutral-300"
      >
        ?
      </button>
      {open && (
        <span
          role="tooltip"
          className="border-divider bg-canvas absolute bottom-full left-1/2 z-10 mb-1 w-48 -translate-x-1/2 rounded-md border p-2 text-xs leading-relaxed text-neutral-700 shadow-md"
        >
          {description}
        </span>
      )}
    </span>
  );
}
