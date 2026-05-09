import { describe, expect, it } from 'vitest';

import type { CallTimeline } from '@/lib/api/calls';
import {
  formatFirstAudioBreakdown,
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

describe('formatFirstAudioBreakdown — #175 new fields', () => {
  it('renders net+pre and decode when present, placed after ttft', () => {
    const detail = {
      latency_seconds: 1.1,
      ttft_seconds: 0.5,
      network_prefill_seconds: 0.35,
      decode_seconds: 0.15,
      tool_prefix_seconds: 0.0,
      cache_read_tokens: 0,
      cache_creation_tokens: 900,
    };
    const timeline: CallTimeline = {
      call_sid: 'CAnew',
      events: [
        {
          timestamp: '2026-05-01T12:00:00.000Z',
          kind: 'first_audio',
          text: '',
          detail,
        },
      ],
    };
    const text = formatTimelineAsText(timeline);
    expect(text).toContain('ttft=500ms');
    expect(text).toContain('net+pre=350ms');
    expect(text).toContain('decode=150ms');
    expect(text).toContain('cache=miss');
    // net+pre must come after ttft in the rendered string.
    const ttftIdx = text.indexOf('ttft=');
    const netPreIdx = text.indexOf('net+pre=');
    const decodeIdx = text.indexOf('decode=');
    expect(netPreIdx).toBeGreaterThan(ttftIdx);
    expect(decodeIdx).toBeGreaterThan(netPreIdx);
  });

  it('old-shape detail without new fields renders identically to before', () => {
    // This is the same detail shape as the existing "renders the latency breakdown"
    // test — verifying the new fields' absence does not change existing output.
    const detail = {
      latency_seconds: 1.236,
      first_text_seconds: 1.1,
      ttft_seconds: 0.42,
      tool_prefix_seconds: 0.38,
      cache_read_tokens: 0,
      cache_creation_tokens: 1850,
    };
    const timeline: CallTimeline = {
      call_sid: 'CAold',
      events: [
        {
          timestamp: '2026-05-01T12:00:00.000Z',
          kind: 'first_audio',
          text: '',
          detail,
        },
      ],
    };
    const text = formatTimelineAsText(timeline);
    expect(text).toContain('ttft=420ms');
    expect(text).toContain('tool=380ms');
    expect(text).toContain('text=1100ms');
    expect(text).toContain('cache=miss');
    // New fields must not appear.
    expect(text).not.toContain('net+pre=');
    expect(text).not.toContain('decode=');
  });
});

describe('formatFirstAudioBreakdown — #183 raw cache token counts', () => {
  it('renders r=N w=M after cache=hit/miss when both token fields are present', () => {
    const result = formatFirstAudioBreakdown({
      ttft_seconds: 0.539,
      network_prefill_seconds: 0.539,
      decode_seconds: 0.0,
      tool_prefix_seconds: 0.0,
      first_text_seconds: 0.541,
      cache_read_tokens: 4096,
      cache_creation_tokens: 0,
    });
    expect(result).toContain('cache=hit r=4096 w=0');
    // Verify the entire bracketed format for the issue's suggested example.
    expect(result).toBe(
      '[ttft=539ms net+pre=539ms decode=0ms tool=0ms text=541ms cache=hit r=4096 w=0]',
    );
  });

  it('omits r= and w= entirely when both token fields are absent', () => {
    // Legacy event — only timing fields, no cache token counts.
    const result = formatFirstAudioBreakdown({
      ttft_seconds: 0.42,
      tool_prefix_seconds: 0.38,
      first_text_seconds: 1.1,
    });
    expect(result).not.toContain('r=');
    expect(result).not.toContain('w=');
    expect(result).not.toContain('cache=');
    expect(result).toBe('[ttft=420ms tool=380ms text=1100ms]');
  });

  it('renders cache=miss r=0 w=4096 for a cold cache write (read=0, creation>0)', () => {
    // cache_read=0 + cache_creation>0 means a fresh write — no prior cache hit.
    const result = formatFirstAudioBreakdown({
      ttft_seconds: 0.6,
      cache_read_tokens: 0,
      cache_creation_tokens: 4096,
    });
    expect(result).toContain('cache=miss r=0 w=4096');
  });

  it('marks cache=hit+ext when read tokens hit AND creation tokens extend the cache', () => {
    // r>0 + w>0 means the cached prefix matched (cache hit) and a small
    // new tail was added on top of the existing cache (incremental
    // extension on a multi-turn call). Previously this was labelled
    // "miss", which was misleading: most of the prompt hit the cache.
    const result = formatFirstAudioBreakdown({
      ttft_seconds: 0.5,
      cache_read_tokens: 5085,
      cache_creation_tokens: 329,
    });
    expect(result).toContain('cache=hit+ext r=5085 w=329');
    expect(result).not.toContain('cache=miss');
  });
});
