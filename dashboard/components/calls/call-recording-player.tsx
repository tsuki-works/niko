'use client';

import { forwardRef } from 'react';
import { Radio } from 'lucide-react';

/**
 * Bordered card holding the call recording audio element. Exposes its
 * `<audio>` ref via forwardRef so the timeline can seek programmatically
 * when the user clicks a transcript row.
 */
export const CallRecordingPlayer = forwardRef<
  HTMLAudioElement,
  { src: string }
>(function CallRecordingPlayer({ src }, ref) {
  return (
    <div className="flex flex-col gap-2 rounded-md border border-border-subtle bg-surface-1 p-4">
      <p className="flex items-center gap-1.5 text-eyebrow">
        <Radio className="size-3" aria-hidden />
        Call recording
      </p>
      <audio
        ref={ref}
        controls
        src={src}
        className="w-full"
        aria-label="Call recording audio player"
      />
    </div>
  );
});
