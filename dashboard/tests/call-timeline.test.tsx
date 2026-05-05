// @vitest-environment jsdom
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { CallTimelineView } from '@/components/calls/call-timeline';
import type { CallTimeline } from '@/lib/api/calls';

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const TIMELINE_BASE: CallTimeline = {
  call_sid: 'CAtest',
  recording_available: true,
  events: [
    {
      timestamp: '2026-05-01T18:00:00Z',
      kind: 'start',
      text: '',
      detail: {},
    },
    {
      timestamp: '2026-05-01T18:00:05Z',
      kind: 'transcript_final',
      text: '',
      detail: { text: 'Hi I want a pizza' },
    },
    {
      timestamp: '2026-05-01T18:00:08Z',
      kind: 'agent_reply',
      text: '',
      detail: { text: 'Sure, what kind?' },
    },
  ],
};

describe('CallTimelineView', () => {
  it('renders a copy button on transcript_final and agent_reply rows', () => {
    render(<CallTimelineView timeline={TIMELINE_BASE} />);
    expect(screen.getByRole('button', { name: /Copy caller text/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Copy agent text/i })).toBeInTheDocument();
  });

  it('does not render a copy button on non-transcript rows', () => {
    render(<CallTimelineView timeline={TIMELINE_BASE} />);
    expect(screen.queryByRole('button', { name: /Copy call started/i })).not.toBeInTheDocument();
  });

  it('copies turn text to the clipboard when the copy button is clicked', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });

    render(<CallTimelineView timeline={TIMELINE_BASE} />);
    fireEvent.click(screen.getByRole('button', { name: /Copy caller text/i }));
    expect(writeText).toHaveBeenCalledWith('Hi I want a pizza');
  });

  it('makes transcript rows seekable buttons and non-transcript rows plain divs', () => {
    render(<CallTimelineView timeline={TIMELINE_BASE} />);
    // Transcript rows render as <button> with seek aria-label
    expect(screen.getByRole('button', { name: /Seek to caller/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Seek to agent/i })).toBeInTheDocument();
  });

  it('seeks the audio when a transcript row is clicked', () => {
    render(<CallTimelineView timeline={TIMELINE_BASE} />);
    const audio = screen.getByLabelText('Call recording audio player') as HTMLAudioElement;
    // jsdom doesn't implement HTMLMediaElement.play by default — stub it
    audio.play = vi.fn().mockResolvedValue(undefined);

    fireEvent.click(screen.getByRole('button', { name: /Seek to caller/i }));
    // First event is at 18:00:00, transcript_final is at 18:00:05 → 5s offset
    expect(audio.currentTime).toBe(5);
  });

  it('does not render seek affordance when no recording is available', () => {
    const noRecording = { ...TIMELINE_BASE, recording_available: false };
    render(<CallTimelineView timeline={noRecording} />);
    // Without a recording, the rows should not be buttons.
    expect(screen.queryByRole('button', { name: /Seek to caller/i })).not.toBeInTheDocument();
  });
});

describe('CallTimelineView voicemail + transfer events', () => {
  // Transfer + voicemail are Tier 2 (telemetry) events, hidden by
  // default. Each test flips the "Show technical events" switch on
  // before asserting on the row content.
  function showTelemetry() {
    fireEvent.click(
      screen.getByRole('switch', { name: /Show technical events/i }),
    );
  }

  it('renders a transfer_attempted event with the resolved status', () => {
    render(
      <CallTimelineView
        timeline={{
          call_sid: 'CAtest',
          recording_available: false,
          events: [
            {
              timestamp: '2026-05-01T18:00:00Z',
              kind: 'transfer_attempted',
              text: '',
              detail: { status: 'answered', fallback_phone: '+15551234567' },
            },
          ],
        }}
      />,
    );
    showTelemetry();
    expect(screen.getByText(/Transfer connected/i)).toBeInTheDocument();
    expect(screen.getByText(/\+15551234567/)).toBeInTheDocument();
  });

  it('renders a voicemail_left event with duration + transcript', () => {
    render(
      <CallTimelineView
        timeline={{
          call_sid: 'CAtest',
          recording_available: false,
          events: [
            {
              timestamp: '2026-05-01T18:00:00Z',
              kind: 'voicemail_left',
              text: 'Hi please call me back',
              detail: { duration_seconds: 18, recording_sid: 'REabc' },
            },
          ],
        }}
      />,
    );
    showTelemetry();
    expect(screen.getByText(/18s/)).toBeInTheDocument();
    expect(screen.getByText(/Hi please call me back/)).toBeInTheDocument();
  });

  it('renders "Transcript pending" when voicemail has no transcript yet', () => {
    render(
      <CallTimelineView
        timeline={{
          call_sid: 'CAtest',
          recording_available: false,
          events: [
            {
              timestamp: '2026-05-01T18:00:00Z',
              kind: 'voicemail_left',
              text: '',
              detail: { duration_seconds: 12 },
            },
          ],
        }}
      />,
    );
    showTelemetry();
    expect(screen.getByText(/Transcript pending/i)).toBeInTheDocument();
  });
});

describe('CallTimelineView Show technical events toggle', () => {
  const MIXED_TIMELINE: CallTimeline = {
    call_sid: 'CAtest',
    recording_available: false,
    events: [
      {
        timestamp: '2026-05-01T18:00:00Z',
        kind: 'start',
        text: '',
        detail: {},
      },
      {
        timestamp: '2026-05-01T18:00:05Z',
        kind: 'transcript_final',
        text: '',
        detail: { text: 'Hello there' },
      },
      {
        timestamp: '2026-05-01T18:00:08Z',
        kind: 'agent_reply',
        text: '',
        detail: { text: 'How can I help?' },
      },
      {
        timestamp: '2026-05-01T18:00:10Z',
        kind: 'first_audio',
        text: '',
        detail: { latency_seconds: 0.6 },
      },
    ],
  };

  it('hides telemetry rows by default and shows the hidden count', () => {
    render(<CallTimelineView timeline={MIXED_TIMELINE} />);
    // Conversation rows are visible.
    expect(screen.getByText(/Hello there/)).toBeInTheDocument();
    expect(screen.getByText(/How can I help/)).toBeInTheDocument();
    // Telemetry rows are not.
    expect(
      screen.queryByText(/Twilio media stream opened/i),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/600ms/)).not.toBeInTheDocument();
    // Hidden-count parenthetical reflects telemetry events only
    // (start + first_audio = 2).
    expect(
      screen.getByRole('switch', { name: /Show technical events \(2 hidden\)/i }),
    ).toBeInTheDocument();
  });

  it('renders telemetry rows inline when the switch is toggled on', () => {
    render(<CallTimelineView timeline={MIXED_TIMELINE} />);
    fireEvent.click(
      screen.getByRole('switch', { name: /Show technical events/i }),
    );
    expect(screen.getByText(/Twilio media stream opened/i)).toBeInTheDocument();
    expect(screen.getByText(/600ms/)).toBeInTheDocument();
    // Hidden-count parenthetical disappears once the toggle is on.
    expect(screen.queryByText(/\(2 hidden\)/)).not.toBeInTheDocument();
  });
});
