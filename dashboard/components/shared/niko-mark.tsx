import { cn } from '@/lib/utils';

/**
 * The Niko smiling-moon icon as an inline SVG.
 *
 * Source: assets/niko/niko_moon_icon_aligned.svg
 *
 * Colors flow through CSS vars (`--niko-ink`, `--niko-paper`) defined
 * in globals.css so the mark inverts in dark mode: navy ↔ cream swap.
 * "ink" is the drawing color (crescent + strokes + features), "paper"
 * is the moon face fill.
 */
export function NikoMark({
  size = 40,
  className,
  ...rest
}: {
  size?: number;
  className?: string;
} & React.SVGAttributes<SVGSVGElement>) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      /* Tight square crop around the actual moon content (original paths
         sit inside a 1024×1024 canvas with ~18% padding top/bottom and
         ~12% sides, which made the favicon render visibly smaller than
         peers and the sidebar mark look short next to adjacent text). */
      viewBox="115 128 780 780"
      width={size}
      height={size}
      role="img"
      aria-label="Niko"
      className={cn('shrink-0', className)}
      {...rest}
    >
      <g fill="none" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="420" cy="540" r="305" fill="var(--niko-ink)" />
        <circle
          cx="585"
          cy="500"
          r="305"
          fill="var(--niko-paper)"
          stroke="var(--niko-ink)"
          strokeWidth="8"
        />
        <path
          d="M445 500 C458 470 502 470 515 500"
          stroke="var(--niko-ink)"
          strokeWidth="24"
        />
        <path
          d="M665 500 C678 470 722 470 735 500"
          stroke="var(--niko-ink)"
          strokeWidth="24"
        />
        <path
          d="M455 650 C520 720 650 720 715 650"
          stroke="var(--niko-ink)"
          strokeWidth="28"
        />
      </g>
    </svg>
  );
}
