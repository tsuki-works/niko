import { type NextRequest, NextResponse } from 'next/server';

import { apiFetch } from '@/lib/api/http';

/**
 * Proxy the Twilio call recording MP3 through Next.js so the browser can
 * play it without needing the FastAPI base URL exposed client-side or any
 * CORS headers on the backend.
 *
 * The session cookie is forwarded automatically by `apiFetch`, which means
 * the FastAPI `current_tenant` dep enforces tenant isolation — you can only
 * play recordings that belong to your restaurant.
 */
export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ call_sid: string }> },
) {
  const { call_sid } = await params;
  const upstream = await apiFetch(
    `/calls/${encodeURIComponent(call_sid)}/recording`,
  );

  if (!upstream.ok) {
    return new NextResponse(null, { status: upstream.status });
  }

  return new NextResponse(upstream.body, {
    status: 200,
    headers: {
      'Content-Type': 'audio/mpeg',
      'Content-Disposition': `inline; filename="${call_sid}.mp3"`,
      // Allow range requests so the browser can seek within the audio.
      'Accept-Ranges': 'bytes',
    },
  });
}
