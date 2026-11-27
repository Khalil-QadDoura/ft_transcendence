import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import {
  Badge,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "../../../components";
import type { BadgeVariant } from "../../../components";
import { activeLanguage, formatNumber } from "../../../i18n";
import {
  DISCUSSION_SECONDS,
  FIRST_LABEL,
  LAST_LABEL,
  MAX_BOTS,
  MAX_PARTICIPANTS,
  MIN_BOTS_WHEN_ANY,
  MIN_HUMANS,
  MIN_PARTICIPANTS_TO_START,
  POINTS_CORRECT,
  POINTS_WRONG,
  RELATIVE_OUTCOME_MIN_HUMANS,
  ROOM_CLOSES_WITH_PARTICIPANTS,
  ROOM_TIMER_MINUTES,
  SINGLE_HUMAN_THRESHOLD,
  START_NOW_MAX_PARTICIPANTS,
  VOTING_SECONDS,
} from "./constants";
import { EXAMPLE_A, EXAMPLE_B } from "./examples";
import {
  decideOutcomes,
  scoreGame,
  type Guess,
  type HumanResult,
  type Outcome,
} from "./scoring";

// Player-facing text of docs/game/turing-duel-rules.md sections 1 to 8. The
// implementer section 9 is deliberately not shown.

const sections = [
  "idea",
  "rooms",
  "waiting",
  "discussion",
  "voting",
  "scoring",
  "outcome",
  "disconnect",
  "results",
  "examples",
] as const;

const outcomeBadge: Record<Outcome, BadgeVariant> = {
  win: "success",
  draw: "info",
  loss: "outline",
};

const listClass = "list-disc ps-5 space-y-2";
const cellClass =
  "border-b border-border-subtle px-3 py-2 text-start align-top";

function useFormat() {
  const { t } = useTranslation("gameRules");
  const number = (value: number) => formatNumber(value);
  const signed = (value: number) =>
    formatNumber(value, { signDisplay: "exceptZero" });
  const percent = (value: number) =>
    formatNumber(value, { style: "percent", maximumFractionDigits: 0 });
  const player = (label: number) => t("player", { number: number(label) });
  const list = (items: string[]) =>
    new Intl.ListFormat(activeLanguage(), { type: "conjunction" }).format(
      items,
    );
  const minutes = (count: number) =>
    t("units.minutes", { count, value: number(count) });
  const seconds = (count: number) =>
    t("units.seconds", { count, value: number(count) });
  return { t, number, signed, percent, player, list, minutes, seconds };
}

function Section({
  id,
  title,
  children,
}: {
  id: (typeof sections)[number];
  title: string;
  children: ReactNode;
}) {
  return (
    <section aria-labelledby={`rules-${id}`} className="space-y-3 scroll-mt-24">
      <h2
        id={`rules-${id}`}
        className="text-xl sm:text-2xl font-semibold tracking-tight text-ink"
      >
        {title}
      </h2>
      {children}
    </section>
  );
}

function MarkCell({ guess }: { guess: Guess }) {
  const { t } = useTranslation("gameRules");
  return (
    <>
      {t(`examples.mark.${guess.mark}`)}{" "}
      <span aria-hidden="true">{guess.correct ? "✓" : "✗"}</span>
      <span className="sr-only">
        {" "}
        ({t(guess.correct ? "examples.correct" : "examples.wrong")})
      </span>
    </>
  );
}

function ScoreCell({ human }: { human: HumanResult }) {
  const { signed } = useFormat();
  return (
    <bdi>
      <span className="text-ink-muted">
        {human.guesses.map(({ points }) => signed(points)).join(" ")} ={" "}
      </span>
      <strong>{signed(human.score)}</strong>
    </bdi>
  );
}

function OutcomeBadge({ outcome }: { outcome: Outcome }) {
  const { t } = useTranslation("gameRules");
  return (
    <Badge variant={outcomeBadge[outcome]} size="sm">
      {t(`examples.outcomes.${outcome}`)}
    </Badge>
  );
}

function ExampleA() {
  const { t, number, signed, percent, player, list } = useFormat();
  const { participants, marks, tie } = EXAMPLE_A;
  const result = scoreGame(participants, marks);
  const labels = (kind: "bot" | "human") =>
    participants
      .filter((participant) => participant.kind === kind)
      .map(({ label }) => player(label));
  const tiedOutcomes = decideOutcomes(result.humans.map(() => tie.score));
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          {t("examples.a.title", {
            humans: number(result.humans.length),
            bots: number(result.bots.length),
          })}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <p>
          {t("examples.a.setup", {
            size: number(participants.length),
            humanLabels: list(labels("human")),
            botLabels: list(labels("bot")),
            others: number(participants.length - 1),
          })}
        </p>
        <div
          className="relative overflow-x-auto"
          role="region"
          aria-labelledby="rules-example-a-caption"
          tabIndex={0}
        >
          <table className="w-full min-w-[36rem] border-collapse text-sm">
            <caption
              id="rules-example-a-caption"
              className="pb-2 text-start text-xs text-ink-muted"
            >
              {t("examples.a.caption")}
            </caption>
            <thead>
              <tr>
                <th scope="col" className={cellClass}>
                  {t("examples.a.markedBy")}
                </th>
                {participants.map(({ label }) => (
                  <th scope="col" className={cellClass} key={label}>
                    {player(label)}
                  </th>
                ))}
                <th scope="col" className={cellClass}>
                  {t("examples.score")}
                </th>
                <th scope="col" className={cellClass}>
                  {t("examples.outcome")}
                </th>
              </tr>
            </thead>
            <tbody>
              {result.humans.map((human) => (
                <tr key={human.label} data-voter={human.label}>
                  <th scope="row" className={cellClass}>
                    {player(human.label)}
                  </th>
                  {participants.map(({ label }) => {
                    const guess = human.guesses.find(
                      ({ target }) => target === label,
                    );
                    return (
                      <td className={cellClass} key={label}>
                        {guess ? (
                          <MarkCell guess={guess} />
                        ) : (
                          <span className="text-ink-muted">
                            {t("examples.self")}
                          </span>
                        )}
                      </td>
                    );
                  })}
                  <td className={cellClass} data-score={human.score}>
                    <ScoreCell human={human} />
                  </td>
                  <td className={cellClass} data-outcome={human.outcome}>
                    <OutcomeBadge outcome={human.outcome} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <h4 className="font-semibold">{t("examples.a.deceptionTitle")}</h4>
        <ul className={listClass}>
          {result.bots.map((bot) => (
            <li key={bot.label} data-bot={bot.label}>
              {t("examples.a.deception", {
                player: player(bot.label),
                fooled: number(bot.fooled),
                humans: number(bot.humans),
                rate: percent(bot.rate),
              })}
            </li>
          ))}
        </ul>
        {tiedOutcomes.every((outcome) => outcome === "draw") && (
          <p>
            {t("examples.a.tie", {
              player: player(tie.label),
              score: signed(tie.score),
              humans: number(result.humans.length),
            })}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function ExampleB() {
  const { t, number, player, list } = useFormat();
  const { participants, scenarios } = EXAMPLE_B;
  const human = participants.find(({ kind }) => kind === "human")!;
  const bots = participants.filter(({ kind }) => kind === "bot");
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          {t("examples.b.title", {
            humans: number(participants.length - bots.length),
            bots: number(bots.length),
          })}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <p>
          {t("examples.b.setup", {
            size: number(participants.length),
            humanLabel: player(human.label),
            botLabels: list(bots.map(({ label }) => player(label))),
          })}
        </p>
        <div
          className="relative overflow-x-auto"
          role="region"
          aria-labelledby="rules-example-b-caption"
          tabIndex={0}
        >
          <table className="w-full border-collapse text-sm">
            <caption
              id="rules-example-b-caption"
              className="pb-2 text-start text-xs text-ink-muted"
            >
              {t("examples.b.caption")}
            </caption>
            <thead>
              <tr>
                <th scope="col" className={cellClass}>
                  {t("examples.b.guesses", { player: player(human.label) })}
                </th>
                <th scope="col" className={cellClass}>
                  {t("examples.score")}
                </th>
                <th scope="col" className={cellClass}>
                  {t("examples.outcome")}
                </th>
              </tr>
            </thead>
            <tbody>
              {scenarios.map((marks, index) => {
                const [result] = scoreGame(participants, marks).humans;
                return (
                  <tr key={index} data-scenario={index}>
                    <th scope="row" className={`${cellClass} font-normal`}>
                      {result.guesses.map((guess, position) => (
                        <span key={guess.target}>
                          {position > 0 && ", "}
                          {player(guess.target)} <MarkCell guess={guess} />
                        </span>
                      ))}
                    </th>
                    <td className={cellClass} data-score={result.score}>
                      <ScoreCell human={result} />
                    </td>
                    <td className={cellClass} data-outcome={result.outcome}>
                      <OutcomeBadge outcome={result.outcome} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}

export function GameRulesPage() {
  const { t, number, signed, minutes, seconds } = useFormat();
  const discussion = seconds(DISCUSSION_SECONDS);
  const voting = seconds(VOTING_SECONDS);
  const titles: Record<(typeof sections)[number], string> = {
    idea: t("idea.title"),
    rooms: t("rooms.title"),
    waiting: t("waiting.title"),
    discussion: t("discussion.title", { duration: discussion }),
    voting: t("voting.title", { duration: voting }),
    scoring: t("scoring.title"),
    outcome: t("outcome.title"),
    disconnect: t("disconnect.title"),
    results: t("results.title"),
    examples: t("examples.title"),
  };
  const startRange = {
    min: number(MIN_PARTICIPANTS_TO_START),
    max: number(START_NOW_MAX_PARTICIPANTS),
  };
  return (
    <article className="max-w-3xl mx-auto px-4 sm:px-6 py-8 sm:py-10 space-y-10 text-start text-ink leading-relaxed">
      <header className="space-y-3">
        <p className="eyebrow text-xs font-mono uppercase tracking-wider text-ink-muted">
          {t("eyebrow")}
        </p>
        <h1 className="text-3xl sm:text-4xl font-bold tracking-tight">
          {t("title")}
        </h1>
        <p className="text-ink-muted max-w-2xl">{t("intro")}</p>
        <nav aria-label={t("contents")}>
          <ol className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
            {sections.map((id) => (
              <li key={id}>
                <a className="underline" href={`#rules-${id}`}>
                  {titles[id]}
                </a>
              </li>
            ))}
          </ol>
        </nav>
      </header>

      <Section id="idea" title={titles.idea}>
        <p>{t("idea.body", { max: number(MAX_PARTICIPANTS) })}</p>
      </Section>

      <Section id="rooms" title={titles.rooms}>
        <ul className={listClass}>
          <li>
            {t("rooms.capacity", {
              max: number(MAX_PARTICIPANTS),
              minHumans: number(MIN_HUMANS),
            })}
          </li>
          <li>{t("rooms.join")}</li>
          <li>
            {t("rooms.labels", {
              first: number(FIRST_LABEL),
              last: number(LAST_LABEL),
            })}
          </li>
          <li>
            {t("rooms.randomLabel", {
              first: number(FIRST_LABEL),
              last: number(LAST_LABEL),
            })}
          </li>
          <li>{t("rooms.stable")}</li>
          <li>
            {t("rooms.bots", {
              min: number(MIN_BOTS_WHEN_ANY),
              max: number(MAX_BOTS),
            })}
          </li>
          <li>{t("rooms.lookAlike")}</li>
        </ul>
      </Section>

      <Section id="waiting" title={titles.waiting}>
        <ul className={listClass}>
          <li>
            {t("waiting.timer", { duration: minutes(ROOM_TIMER_MINUTES) })}
          </li>
          <li>{t("waiting.joining")}</li>
          <li>{t("waiting.shows", startRange)}</li>
          <li>{t("waiting.noChat")}</li>
          <li>{t("waiting.counts")}</li>
        </ul>
        <h3 className="pt-2 text-lg font-semibold">
          {t("waiting.startTitle")}
        </h3>
        <p>{t("waiting.startIntro")}</p>
        <ol className="list-decimal ps-5 space-y-2">
          <li>{t("waiting.startFull", { max: number(MAX_PARTICIPANTS) })}</li>
          <li>{t("waiting.startNow", startRange)}</li>
          <li>
            {t("waiting.startTimer", {
              min: number(MIN_PARTICIPANTS_TO_START),
            })}
          </li>
        </ol>
        <p>{t("waiting.late")}</p>
        <h3 className="pt-2 text-lg font-semibold">
          {t("waiting.leaveTitle")}
        </h3>
        <p>{t("waiting.leave")}</p>
        <p>{t("waiting.leaveLate")}</p>
        <h3 className="pt-2 text-lg font-semibold">
          {t("waiting.closeTitle")}
        </h3>
        <p>
          {t("waiting.close", {
            participants: number(ROOM_CLOSES_WITH_PARTICIPANTS),
          })}
        </p>
      </Section>

      <Section id="discussion" title={titles.discussion}>
        <p>{t("discussion.body")}</p>
      </Section>

      <Section id="voting" title={titles.voting}>
        <ul className={listClass}>
          <li>{t("voting.who")}</li>
          <li>{t("voting.preset")}</li>
          <li>{t("voting.change", { duration: voting })}</li>
          <li>{t("voting.final")}</li>
        </ul>
      </Section>

      <Section id="scoring" title={titles.scoring}>
        <ul className={listClass}>
          <li>{t("scoring.correct", { points: signed(POINTS_CORRECT) })}</li>
          <li>{t("scoring.wrong", { points: signed(POINTS_WRONG) })}</li>
        </ul>
        <p>{t("scoring.sum", { zero: number(0) })}</p>
      </Section>

      <Section id="outcome" title={titles.outcome}>
        <ul className={listClass}>
          <li>
            {t("outcome.many", {
              min: number(RELATIVE_OUTCOME_MIN_HUMANS),
              zero: number(0),
            })}
          </li>
          <li>
            {t("outcome.single", {
              humans: number(RELATIVE_OUTCOME_MIN_HUMANS - 1),
              threshold: number(SINGLE_HUMAN_THRESHOLD),
            })}
          </li>
          <li>{t("outcome.humansOnly")}</li>
          <li>{t("outcome.draw")}</li>
        </ul>
      </Section>

      <Section id="disconnect" title={titles.disconnect}>
        <ul className={listClass}>
          <li>{t("disconnect.keep")}</li>
          <li>{t("disconnect.counts")}</li>
          <li>{t("disconnect.back")}</li>
        </ul>
      </Section>

      <Section id="results" title={titles.results}>
        <p>{t("results.intro")}</p>
        <ul className={listClass}>
          <li>{t("results.bots")}</li>
          <li>{t("results.scores")}</li>
          <li>{t("results.rate")}</li>
        </ul>
      </Section>

      <Section id="examples" title={titles.examples}>
        <div className="space-y-6">
          <ExampleA />
          <ExampleB />
        </div>
      </Section>

      <p>
        <Link className="button" to="/game">
          {t("lobby")}
          <span aria-hidden="true">↗</span>
        </Link>
      </p>
    </article>
  );
}
