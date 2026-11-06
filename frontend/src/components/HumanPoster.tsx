import { useId } from "react";

/** Original typographic artwork; decorative and independent of account data. */
export function HumanPoster() {
  const gradient = `bloom-${useId().replaceAll(":", "")}`;
  return (
    <div className="signal-art human-poster-wrap" aria-hidden="true">
      <div className="human-poster">
        <div className="human-poster-top">
          <span>
            THE HUMAN
            <br />
            SIDE OF WORK.
          </span>
          <span>
            WOZU ✳<br />
            EST. 2026
          </span>
        </div>
        <svg className="human-bloom" viewBox="0 0 400 400" fill="none">
          <defs>
            <linearGradient
              id={gradient}
              x1="200"
              y1="35"
              x2="275"
              y2="220"
              gradientUnits="userSpaceOnUse"
            >
              <stop stopColor="#f2ffb6" />
              <stop offset=".5" stopColor="#c1d969" />
              <stop offset="1" stopColor="#536444" />
            </linearGradient>
          </defs>
          {Array.from({ length: 12 }, (_, i) => (
            <ellipse
              key={i}
              cx="200"
              cy="130"
              rx="36"
              ry="104"
              fill={`url(#${gradient})`}
              stroke="#ddeaa0"
              strokeWidth=".6"
              transform={`rotate(${i * 30} 200 200)`}
            />
          ))}
          <circle cx="200" cy="200" r="29" fill="#323b2c" />
          <circle cx="200" cy="200" r="18" fill="#e9eecc" />
        </svg>
        <strong className="human-poster-word">YOU.</strong>
        <div className="human-poster-bottom">
          <span>
            MORE THAN A CV.
            <br />A WORLD OF POSSIBILITY.
          </span>
          <span>↗</span>
        </div>
        <div className="human-poster-stamp">
          A little
          <br />
          <em>more human.</em>
        </div>
      </div>
    </div>
  );
}
