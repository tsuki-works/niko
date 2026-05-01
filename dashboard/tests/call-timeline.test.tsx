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
