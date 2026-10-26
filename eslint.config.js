/**
 * @file eslint.config.js
 * @description Minimal ESLint 9 configuration for the Vite React frontend.
 */
import eslint from '@eslint/js';

export default [
  eslint.configs.recommended,
  {
    files: ['frontend/src/**/*.{js,jsx}'],
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      parserOptions: { ecmaFeatures: { jsx: true } },
      globals: { window: 'readonly', document: 'readonly', localStorage: 'readonly', fetch: 'readonly' },
    },
    rules: {
      // JSX references are handled by Vite's React transform; this project does not use react-eslint.
      'no-unused-vars': 'off',
    },
  },
  { ignores: ['dist/**', 'node_modules/**'] },
];
