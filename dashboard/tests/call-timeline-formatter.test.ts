import { describe, expect, it } from 'vitest';

import type { CallTimeline } from '@/lib/api/calls';
import {
  formatTimelineAsText,
  timelineFilename,
} from '@/lib/formatters/call-timeline';

const TIMELINE: CallTimeline = {
  call_sid: 'CA1fa31451294f94252d2bfa99dc455ce1',
  events: [
    {
      timestamp: '2026-04-25T23:11:08.000Z',
      kind: 'start',
      text: '',
      detail: {},
    },
    {
      timestamp: '2026-04-25T23:11:08.700Z',
      kind: 'first_audio',
      text: '',
      detail: { latency_seconds: 0.749 },
    },
    {
      timestamp: '2026-04-25T23:11:17.000Z',
      kind: 'transcript_final',
      text: '',
      detail: { text: 'can i get a barbecue pizza' },
    },
    {
      timestamp: '2026-04-25T23:11:18.246Z',
      kind: 'first_audio',
      text: '',
      detail: { latency_seconds: 1.246 },
    },
    {
      timestamp: '2026-04-25T23:11:34.000Z',
      kind: 'agent_reply',
      text: 'One barbecue pizza coming up. Anything else?',
      detail: { text: 'One barbecue pizza coming up. Anything else?' },
    },
    {
      timestamp: '2026-04-25T23:13:58.000Z',
      kind: 'order_confirmed',
      text: '',
      detail: {},
    },
  ],
};

describe('formatTimelineAsText', () => {
  it('emits a header with call_sid and start time', () => {
    const text = formatTimelineAsText(TIMELINE);
    expect(text).toContain('Call CA1fa31451294f94252d2bfa99dc455ce1');
    expect(text).toContain('Started: 2026-04-25 23:11:08 UTC');
  });

  it('renders caller transcripts with the CALLER label and the spoken text', () => {
    const text = formatTimelineAsText(TIMELINE);
    expect(text).toMatch(/23:11:17\s+CALLER\s+can i get a barbecue pizza/);
  });

  it('annotates first_audio events that breach the 1s budget', () => {
    const text = formatTimelineAsText(TIMELINE);
    expect(text).toContain('FIRST_AUDIO');
    expect(text).toContain('749ms');
    expect(text).toContain('1246ms (over budget)');
  });

  it('renders the latency breakdown when #146 instrumentation fields are present', () => {
    const enriched: CallTimeline = {
      call_sid: 'CAenriched',
      events: [
        {
          timestamp: '2026-05-01T10:37:09.000Z',
          kind: 'first_audio',
          text: '',
          detail: {
            latency_seconds: 1.236,
            first_text_seconds: 1.1,
            ttft_seconds: 0.42,
            tool_prefix_seconds: 0.38,
            cache_read_tokens: 0,
            cache_creation_tokens: 1850,
          },
        },
      ],
    };
    const text = formatTimelineAsText(enriched);
    expect(text).toContain('1236ms (over budget)');
    expect(text).toContain('ttft=420ms');
    expect(text).toContain('tool=380ms');
    expect(text).toContain('text=1100ms');
    expect(text).toContain('cache=miss');
  });

  it('omits the breakdown for legacy first_audio events that lack the new fields', () => {
    const text = formatTimelineAsText(TIMELINE);
    expect(text).not.toContain('ttft=');
    expect(text).not.toContain('cache=');
  });

  it('marks cache=hit when read tokens are present and creation tokens are zero', () => {
    const cached: CallTimeline = {
      call_sid: 'CAcached',
      events: [
        {
          timestamp: '2026-05-01T10:37:27.000Z',
          kind: 'first_audio',
          text: '',
          detail: {
            latency_seconds: 0.574,
            ttft_seconds: 0.4,
            tool_prefix_seconds: 0,
            cache_read_tokens: 1850,
            cache_creation_tokens: 0,
          },
        },
      ],
    };
    const text = formatTimelineAsText(cached);
    expect(text).toContain('cache=hit');
  });

  it('renders agent_reply events with the AGENT label', () => {
    const text = formatTimelineAsText(TIMELINE);
    expect(text).toMatch(
      /23:11:34\s+AGENT\s+One barbecue pizza coming up\. Anything else\?/,
    );
  });

  it('orders rows in arrival order (matches the events array)', () => {
    const text = formatTimelineAsText(TIMELINE);
    const startIdx = text.indexOf('CALL_START');
    const orderConfirmedIdx = text.indexOf('ORDER_CONFIRMED');
    expect(startIdx).toBeGreaterThan(-1);
    expect(orderConfirmedIdx).toBeGreaterThan(startIdx);
  });

  it('falls back to a no-events placeholder when the timeline is empty', () => {
    const text = formatTimelineAsText({ call_sid: 'CAempty', events: [] });
    expect(text).toBe('Call CAempty\n(no events)');
  });
});

describe('timelineFilename', () => {
  it('builds a sortable filename with the short call_sid and the date', () => {
    const filename = timelineFilename(TIMELINE, new Date('2026-04-25T23:50:00Z'));
    expect(filename).toBe('niko-call-CA1fa31451-20260425.txt');
  });
});
