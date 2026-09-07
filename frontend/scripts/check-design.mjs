#!/usr/bin/env node
/**
 * 디자인 규칙 위반을 잡는다. Windows·macOS 동일하게 동작한다.
 *   node scripts/check-design.mjs
 *
 * DESIGN.md 에 적어두는 건 부탁이라 사람도 에이전트도 잊는다. 여기서 막으면 잊어도 통과가 안 된다.
 */
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative, sep } from 'node:path';

const ROOT = join(import.meta.dirname, '..', 'src');

/** src 아래 .ts/.tsx 전부 수집 */
function collect(dir) {
  return readdirSync(dir).flatMap((name) => {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) return collect(full);
    return /\.tsx?$/.test(name) ? [full] : [];
  });
}

const CHECKS = [
  {
    label: 'hex 색상 하드코딩',
    pattern: /#[0-9a-fA-F]{3,8}\b/,
    hint: 'src/styles/theme.css 의 토큰 유틸리티를 쓴다. (bg-surface, text-brand 등)',
  },
  {
    label: 'Tailwind 임의값',
    pattern:
      /\b(p|px|py|pt|pb|pl|pr|m|mx|my|mt|mb|ml|mr|gap|w|h|min-w|max-w|text|bg|border|rounded|tracking)-\[/,
    hint: '임의값 대신 토큰 단계를 쓴다. (p-3, text-h2 등) var(--토큰) 참조는 예외.',
    allow: /var\(--/,
  },
  {
    label: '등락 색 직접 사용',
    pattern: /\b(text-up|text-down|text-flat|bg-up-|bg-down-)/,
    hint: '등락 색은 <Change /> 안에서만 쓴다.',
    exceptFiles: [
      'components/ui/Change.tsx',
      'components/ui/Tag.tsx',
      'components/ui/State.tsx',
    ],
  },
  {
    label: '포맷 함수 우회',
    pattern: /\.(toFixed|toLocaleString)\(/,
    hint: '숫자 포맷은 lib/format.ts 의 함수만 쓴다.',
    exceptFiles: ['lib/format.ts'],
  },
];

let failed = 0;

for (const file of collect(ROOT)) {
  const rel = relative(join(ROOT, '..'), file).split(sep).join('/');
  const lines = readFileSync(file, 'utf8').split('\n');

  for (const check of CHECKS) {
    if (check.exceptFiles?.some((f) => rel.endsWith(f))) continue;

    lines.forEach((line, i) => {
      if (!check.pattern.test(line)) return;
      if (check.allow?.test(line)) return;
      console.error(`✗ ${check.label}`);
      console.error(`  ${rel}:${i + 1}  ${line.trim()}`);
      console.error(`  → ${check.hint}\n`);
      failed += 1;
    });
  }
}

if (failed > 0) {
  console.error(`디자인 규칙 위반 ${failed}건. DESIGN.md 를 확인하세요.`);
  process.exit(1);
}

console.log('✓ 디자인 규칙 통과');
