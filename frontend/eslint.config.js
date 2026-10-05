import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      globals: globals.browser,
    },
    rules: {
      '@typescript-eslint/no-explicit-any': 'off',
      // `const { id: _id, ...rest } = x` is how we drop a field before sending it.
      '@typescript-eslint/no-unused-vars': ['error', { ignoreRestSiblings: true }],
      // Flags the load-on-mount pattern (`useEffect(() => { load() }, [])`)
      // used across the app. It is a performance hint, not a bug, so keep
      // it visible as a warning without failing CI.
      'react-hooks/set-state-in-effect': 'warn',
    },
  },
])