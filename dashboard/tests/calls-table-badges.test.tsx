// @vitest-environment jsdom
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { CallsTable } from '@/components/calls/calls-table';

const BASE_CALL = {
  call_sid: 'CAtest',
  started_at: '2026-05-01T18:00:00Z',
  ended_at: '2026-05-01T18:01:00Z',
  transcript_count: 4,
  has_error: false,
  status: 'ended' as const,
};

describe('CallsTable voicemail + transfer badges', () => {
  it('renders a Voicemail badge when voicemail_left is true', () => {
    render(
      <CallsTable
        calls={[{ ...BASE_CALL, voicemail_left: true }]}
        twilioPhone="+15551234567"
      />,
    );
    expect(screen.getByLabelText(/voicemail left/i)).toBeInTheDocument();
  });

  it('renders a "transferred" badge for answered transfers', () => {
    render(
      <CallsTable
        calls={[
          { ...BASE_CALL, transfer_attempted: true, transfer_status: 'answered' },
        ]}
        twilioPhone="+15551234567"
      />,
    );
    expect(screen.getByText(/transferred/i)).toBeInTheDocument();
  });

  it('renders a "no_answer" transfer badge for no-answer transfers', () => {
    render(
      <CallsTable
        calls={[
          { ...BASE_CALL, transfer_attempted: true, transfer_status: 'no_answer' },
        ]}
        twilioPhone="+15551234567"
      />,
    );
    expect(screen.getByText(/no_answer/i)).toBeInTheDocument();
  });

  it('renders no extra badges on a normal call', () => {
    render(
      <CallsTable calls={[BASE_CALL]} twilioPhone="+15551234567" />,
    );
    expect(screen.queryByLabelText(/voicemail/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/transfer/i)).not.toBeInTheDocument();
  });
});
