'use client';

import { Copy, Download } from 'lucide-react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import type { CallTimeline } from '@/lib/api/calls';
import {
  formatTimelineAsText,
  timelineFilename,
} from '@/lib/formatters/call-timeline';

export function TimelineExport({ timeline }: { timeline: CallTimeline }) {
  const handleCopy = async () => {
    const text = formatTimelineAsText(timeline);
    try {
      await navigator.clipboard.writeText(text);
      toast.success('Timeline copied to clipboard');
    } catch (err) {
      console.error('Clipboard write failed', err);
      toast.error("Couldn't copy — clipboard permission denied?");
    }
  };

  const handleDownload = () => {
    const text = formatTimelineAsText(timeline);
    const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = timelineFilename(timeline);
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  return (
    <div className="flex items-center gap-2">
      <Button
        variant="outline"
        size="sm"
        onClick={handleCopy}
        aria-label="Copy timeline as text"
      >
        <Copy aria-hidden /> Copy
      </Button>
      <Button
        variant="outline"
        size="sm"
        onClick={handleDownload}
        aria-label="Download timeline as text file"
      >
        <Download aria-hidden /> Download
      </Button>
    </div>
  );
}
