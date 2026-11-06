import { useId } from "react";

/** Original vector sculpture; gradients stay isolated when several appear on a page. */
export function SignalArtwork({
  variant = "coral",
}: {
  variant?: "coral" | "duel";
}) {
  const id = useId().replaceAll(":", "");
  const duel = variant === "duel";
  return (
    <div className={`signal-art signal-${variant}`} aria-hidden="true">
      <svg viewBox="0 0 480 440" fill="none">
        <defs>
          <linearGradient
            id={`${id}-metal`}
            x1="80"
            y1="60"
            x2="360"
            y2="360"
            gradientUnits="userSpaceOnUse"
          >
            <stop stopColor="#fff8ed" />
            <stop offset=".2" stopColor="#bdb9b1" />
            <stop offset=".38" stopColor="#faf8f3" />
            <stop offset=".53" stopColor="#777571" />
            <stop offset=".7" stopColor="#242423" />
            <stop offset=".83" stopColor="#d8d4cb" />
            <stop offset="1" stopColor="#fffdf7" />
          </linearGradient>
          <radialGradient id={`${id}-orb`} cx=".3" cy=".22" r=".8">
            <stop stopColor={duel ? "#eeffc0" : "#ffbd9a"} />
            <stop offset=".42" stopColor={duel ? "#d4f478" : "#ff7959"} />
            <stop offset=".78" stopColor={duel ? "#718c36" : "#d93624"} />
            <stop offset="1" stopColor={duel ? "#283322" : "#7c221b"} />
          </radialGradient>
          <filter
            id={`${id}-shadow`}
            x="-80%"
            y="-80%"
            width="260%"
            height="260%"
          >
            <feGaussianBlur stdDeviation="14" />
          </filter>
        </defs>
        <g opacity=".22" stroke="currentColor" strokeWidth=".7">
          <circle cx="240" cy="220" r="193" />
          <circle cx="240" cy="220" r="161" strokeDasharray="2 7" />
          <path d="M13 220h454M240 10v420" />
          <path d="M90 70l300 300M390 70L90 370" opacity=".4" />
        </g>
        <ellipse
          cx="252"
          cy="373"
          rx="120"
          ry="17"
          fill="#0a0a0a"
          opacity=".3"
          filter={`url(#${id}-shadow)`}
        />
        <g className="sculpture-float">
          <ellipse
            cx="239"
            cy="218"
            rx="111"
            ry="158"
            transform="rotate(38 239 218)"
            stroke={`url(#${id}-metal)`}
            strokeWidth="49"
          />
          <ellipse
            cx="239"
            cy="218"
            rx="111"
            ry="158"
            transform="rotate(38 239 218)"
            stroke="#fff"
            strokeWidth="1"
            opacity=".5"
          />
          <circle cx="268" cy="206" r="81" fill={`url(#${id}-orb)`} />
          <ellipse
            cx="247"
            cy="216"
            rx="177"
            ry="62"
            transform="rotate(-25 247 216)"
            stroke={`url(#${id}-metal)`}
            strokeWidth="15"
          />
          <path
            d="M86 267c12 18 77 14 146-9"
            stroke="#fffcf0"
            strokeWidth="2"
            strokeLinecap="round"
            opacity=".75"
          />
        </g>
        <g fill="currentColor">
          <circle cx="389" cy="100" r="4" />
          <path
            d="M90 116v20m-10-10h20M390 310v16m-8-8h16"
            stroke="currentColor"
          />
        </g>
      </svg>
      <div className="signal-caption">
        <span>{duel ? "HUMAN INSTINCT" : "A LITTLE MORE HUMAN"}</span>
        <span>↗</span>
      </div>
    </div>
  );
}
