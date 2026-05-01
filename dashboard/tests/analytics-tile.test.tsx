// @vitest-environment jsdom
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { Tile } from '@/components/analytics/tile';

describe('analytics Tile', () => {
  it('renders label, value, and unit', () => {
    render(<Tile label="Calls today" value="3" unit="calls" />);
    expect(screen.getByText('Calls today')).toBeInTheDocument();
    expect(screen.getByText('3')).toBeInTheDocument();
    expect(screen.getByText('calls')).toBeInTheDocument();
  });

  it('omits unit when not provided', () => {
    render(<Tile label="x" value="5" />);
    expect(screen.queryByText(/calls/)).not.toBeInTheDocument();
  });
});
