import js from '@eslint/js';
import globals from 'globals';
import tseslint from 'typescript-eslint';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';
import prettier from 'eslint-config-prettier';

export default tseslint.config(
  { ignores: ['dist', 'node_modules'] },
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      ...tseslint.configs.recommended,
      reactHooks.configs.flat['recommended-latest'],
      reactRefresh.configs.vite,
      // prettier 는 마지막. 포맷 관련 규칙을 끈다. 포맷은 prettier 가 한다.
      prettier,
    ],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
    },
    rules: {
      // 미사용 변수는 경고. _ 로 시작하면 통과 (의도적으로 안 쓰는 인자)
      '@typescript-eslint/no-unused-vars': [
        'warn',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
      // any 는 경고까지만. 마감 앞두고 에러로 막으면 우회 코드가 늘어난다
      '@typescript-eslint/no-explicit-any': 'warn',
      // 훅 규칙은 에러. 무한 렌더링·stale state 의 원인이라 넘어가면 안 된다
      'react-hooks/exhaustive-deps': 'error',
      'react-hooks/rules-of-hooks': 'error',
      // console.log 는 커밋에 들어가면 안 된다. console.warn/error 는 허용
      'no-console': ['warn', { allow: ['warn', 'error'] }],
      eqeqeq: ['error', 'always'],
    },
  },
);

// 타입 기반 규칙(floating promise 등)이 필요해지면 tseslint.configs.recommended 를
// recommendedTypeChecked 로 바꾸고 languageOptions.parserOptions.project 를 지정한다.
// 지금은 속도와 노이즈 때문에 빼뒀다.
