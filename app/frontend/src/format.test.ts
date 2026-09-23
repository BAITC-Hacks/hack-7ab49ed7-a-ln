import { expect, it } from 'vitest';
import { score, share } from './format';

it('distinguishes scores from proportions', () => {
  expect(score(0.694)).toBe('0,69');
  expect(score(0.8)).toBe('0,80');
  expect(score(1)).toBe('1,00');
  expect(share(0.8)).toBe('80 %');
});
