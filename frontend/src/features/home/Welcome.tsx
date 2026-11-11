import { Link } from "react-router-dom";
export function Welcome() {
  return (
    <>
      <section className="hero">
        <div className="hero-copy">
          <p className="eyebrow">
            <span className="status-dot" /> FOR THE PERSON BEHIND THE PROFILE
          </p>
          <h1>
            Your next
            <br />
            <em>chapter,</em>
            <br />
            in good company.
          </h1>
          <p className="hero-description">
            You bring the spark. We make the introduction. <br />
            Find work, meet your people, and let the real you through.
          </p>
          <div className="hero-actions">
            <Link className="button light" to="/jobs">
              Find your next chapter <span aria-hidden="true">↗</span>
            </Link>
            <Link className="text-link" to="/register">
              Introduce yourself <span aria-hidden="true">→</span>
            </Link>
          </div>
          <div className="hero-note">
            <span>01 — DISCOVER</span>
            <span>02 — CONNECT</span>
            <span>03 — BELONG</span>
          </div>
        </div>
        <div className="identity-poster" aria-hidden="true">
          <div className="poster-heading">
            <span>
              THE HUMAN
              <br />
              SIDE OF WORK.
            </span>
            <span>
              WOZU ✳
              <br />
              EST. 2026
            </span>
          </div>
          <div className="poster-art">
            <svg viewBox="0 0 400 400" fill="none">
              <defs>
                <linearGradient
                  id="petal"
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
                  fill="url(#petal)"
                  stroke="#ddeaa0"
                  strokeWidth=".6"
                  transform={`rotate(${i * 30} 200 200)`}
                />
              ))}
              <circle cx="200" cy="200" r="29" fill="#323b2c" />
              <circle cx="200" cy="200" r="18" fill="#e9eecc" />
            </svg>
          </div>
          <span className="poster-word">YOU.</span>
          <div className="poster-footer">
            <span>
              MORE THAN A CV.
              <br />A WHOLE WORLD OF POSSIBILITY.
            </span>
            <span className="poster-arrow">↗</span>
          </div>
          <div className="poster-stamp">
            A little
            <br />
            <em>more human.</em>
          </div>
        </div>
      </section>
      <section className="explore" aria-labelledby="explore-heading">
        <div className="section-heading">
          <div>
            <p className="eyebrow">GOOD THINGS START WITH A HELLO</p>
            <h2 id="explore-heading">
              A world of <em>possibility.</em>
            </h2>
          </div>
          <span className="section-number" aria-hidden="true">
            [ 01 — 03 ]
          </span>
        </div>
        <div className="explore-grid">
          {[
            [
              "01",
              "/jobs",
              "Find your place.",
              "Discover work that fits who you are, and who you’re becoming.",
              "OPPORTUNITIES",
              "↗",
            ],
            [
              "02",
              "/videos",
              "Let them meet you.",
              "Turn a first impression into a real connection. Your voice belongs here.",
              "YOUR INTRODUCTION",
              "▷",
            ],
            [
              "03",
              "/game/rules",
              "A little human instinct.",
              "A conversation. A hidden identity. Can you tell who’s really human?",
              "TURING DUEL",
              "✳",
            ],
          ].map(([number, to, title, description, label, symbol]) => (
            <Link className={`explore-card card-${number}`} key={to} to={to}>
              <div className="card-top">
                <span>{label}</span>
                <span>{number}</span>
              </div>
              <span className="card-symbol" aria-hidden="true">
                {symbol}
              </span>
              <h3>{title}</h3>
              <p>{description}</p>
              <span className="card-bottom">
                Explore <span aria-hidden="true">↗</span>
              </span>
            </Link>
          ))}
        </div>
      </section>
    </>
  );
}
