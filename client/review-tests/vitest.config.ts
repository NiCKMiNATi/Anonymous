// REVIEW ONLY: opt-in suite; production config and original tests are unchanged.
import { defineConfig, mergeConfig } from 'vitest/config';
import original from '../vite.config.ts';
export default mergeConfig(original, defineConfig({
  test: { include: ['review-tests/*.review.tsx'] },
}));
