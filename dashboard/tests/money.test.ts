import { describe, expect, it } from 'vitest';

import { formatCAD } from '@/lib/formatters/money';

describe('formatCAD', () => {
  it('formats whole dollars', () => {
    expect(formatCAD(18)).toBe('$18.00');
  });

  it('formats cents', () => {
    expect(formatCAD(18.99)).toBe('$18.99');
  });

  it('handles zero', () => {
    expect(formatCAD(0)).toBe('$0.00');
  });

  it('adds thousands separator', () => {
    expect(formatCAD(1234.5)).toBe('$1,234.50');
  });
});
