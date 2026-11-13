import { useText } from "../../i18n/useText";
import { Link } from "react-router-dom";
export function Welcome() {
  const { t } = useText();
  return (
    <>
      <section className="hero">
        <div className="hero-copy">
          <p className="eyebrow">
            <span className="status-dot" />
            {t("home.forThePersonBehindTheProfile")}
          </p>
          <h1>
            {t("home.yourNext")}
            <br />
            <em>{t("home.chapter")}</em>
            <br />
            {t("home.inGoodCompany")}
          </h1>
          <p className="hero-description">
            {t("home.youBringTheSparkWeMakeTheIntroduction")}
            <br />
            {t("home.findWorkMeetYourPeopleAndLetTheReal")}
          </p>
          <div className="hero-actions">
            <Link className="button light" to="/jobs">
              {t("home.findYourNextChapter")}
              <span aria-hidden="true">↗</span>
            </Link>
            <Link className="text-link" to="/register">
              {t("home.introduceYourself")}
              <span aria-hidden="true">→</span>
            </Link>
          </div>
          <div className="hero-note">
            <span>{t("home.01Discover")}</span>
            <span>{t("home.02Connect")}</span>
            <span>{t("home.03Belong")}</span>
          </div>
        </div>
        <div className="identity-poster" aria-hidden="true">
          <div className="poster-heading">
            <span>
              {t("home.theHuman")}
              <br />
              {t("home.sideOfWork")}
            </span>
            <span>
              WOZU ✳
              <br />
              {t("home.est2026")}
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
          <span className="poster-word">{t("home.you")}</span>
          <div className="poster-footer">
            <span>
              {t("home.moreThanACv")}
              <br />
              {t("home.aWholeWorldOfPossibility")}
            </span>
            <span className="poster-arrow">↗</span>
          </div>
          <div className="poster-stamp">
            {t("home.aLittle")}
            <br />
            <em>{t("home.moreHuman")}</em>
          </div>
        </div>
      </section>
      <section className="explore" aria-labelledby="explore-heading">
        <div className="section-heading">
          <div>
            <p className="eyebrow">{t("home.goodThingsStartWithAHello")}</p>
            <h2 id="explore-heading">
              {t("home.aWorldOf")} <em>{t("home.possibility")}</em>
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
              t("home.jobTitle"),
              t("home.jobDescription"),
              t("home.jobLabel"),
              "↗",
            ],
            [
              "02",
              "/videos",
              t("home.videoTitle"),
              t("home.videoDescription"),
              t("home.videoLabel"),
              "▷",
            ],
            [
              "03",
              "/game/rules",
              t("home.gameTitle"),
              t("home.gameDescription"),
              t("home.gameLabel"),
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
                {t("home.explore")}
                <span aria-hidden="true">↗</span>
              </span>
            </Link>
          ))}
        </div>
      </section>
    </>
  );
}
