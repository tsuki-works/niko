import { cn } from '@/lib/utils';

/**
 * The Niko smiling-moon icon as an inline SVG.
 *
 * Source: assets/niko/niko_moon_icon_aligned.svg
 * Colors are hardcoded brand values (navy #28456F + cream #DDCCA8)
 * because the mark is a fixed brand asset — it shouldn't adopt
 * arbitrary text/background colors.
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
      viewBox="0 0 1024 1024"
      width={size}
      height={size}
      role="img"
      aria-label="Niko"
      className={cn('shrink-0', className)}
      {...rest}
    >
      <g fill="none" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="420" cy="540" r="305" fill="#28456F" />
        <circle
          cx="585"
          cy="500"
          r="305"
          fill="#DDCCA8"
          stroke="#28456F"
          strokeWidth="8"
        />
        <path
          d="M445 500 C458 470 502 470 515 500"
          stroke="#28456F"
          strokeWidth="24"
        />
        <path
          d="M665 500 C678 470 722 470 735 500"
          stroke="#28456F"
          strokeWidth="24"
        />
        <path
          d="M455 650 C520 720 650 720 715 650"
          stroke="#28456F"
          strokeWidth="28"
        />
      </g>
    </svg>
  );
}
