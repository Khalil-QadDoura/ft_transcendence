# Turing Duel: rules and scoring

Shown in the app at /game/rules; numbers are checked by `npm run rules:check` (`frontend/scripts/game-rules.drift.ts`).

Rules of the Turing Duel mini-game, as decided by the Product Owner on 2026-11-04. The game rules page (FE-34) shows this text, the translation cards (FE-07) translate it, and the room, scoring and UI cards (BE-27, BE-10, FE-31, FE-32) implement exactly this text. Changing a rule means changing this file first.

Sections 1 to 8 are written for players. Section 9 is for implementers.

## 1. The idea

A room holds up to 5 participants. Some of them are real people, some may be bots. Everyone is anonymous. After a short chat, every human has to guess for each other participant: bot or human? Right guesses earn points, wrong guesses cost points. The human with the most points wins.

## 2. Rooms and participants

- A room holds up to 5 participants, and at least 1 of them is a human.
- A player creates a new room or joins an open one from the lobby.
- Every participant is shown only as a label: "Player 1" … "Player 5". There is no real name, no avatar and no link to a profile anywhere in the game.
- On joining, each participant gets a random free number from 1 to 5, not the next number in join order. "Player 1" therefore says nothing about who created the room or whether that participant is a human. Labels can have gaps, for example Player 2 and Player 5 in a room of two.
- A label stays the same for the whole room.
- Each human sees their own label marked as "You".
- Some participants may be bots. The game never says which ones, or whether a room has any, until the results (section 7).
- Bots behave like humans: same kind of label, same way of joining, same way of chatting.

## 3. Waiting room

- A single 3-minute timer starts when the room is created. It never restarts, whoever joins.
- Participants join one by one. Bots, if the room has any, join at random moments in between the humans.
- The waiting room shows: the number of participants, the labels present, the room timer and, while the room has 2 to 4 participants, a "Start now" button.
- There is no chat in the waiting room. Chat exists only in the discussion phase.
- Every participant count in the game counts bots as well as humans.

### When the game starts

The game starts as soon as one of these happens:

1. The 5th participant joins.
2. A human presses "Start now" (visible while the room has 2 to 4 participants). The first press starts the game for the participants present at that moment; later presses are ignored.
3. The room timer runs out and the room has 2 or more participants.

Participants who have not joined when the game starts do not join later.

### Leaving the waiting room

A human may leave the room before the game starts. Their label goes back to the pool and the participant count drops by one. The room timer keeps running. If no human is left in the room, the room closes at once and any bots that were planned for it are dropped.

Leaving after the game has started counts as a disconnect (section 6).

### When the room closes

If the room timer runs out with only 1 participant, the room closes. The human goes back to the lobby and can create or join a new room.

## 4. Discussion phase (120 seconds)

Participants chat in the room. Messages show only the sender's label.

## 5. Voting phase (45 seconds)

Each human marks every other participant as "bot" or "human". A participant cannot mark themselves. Bots do not vote.

- When voting starts, every other participant is already marked "human".
- A human switches any mark between "human" and "bot" as often as they like until the 45 seconds end.
- The marks at the end of the voting phase are the ones that count. There is no "no guess": a mark left at "human" counts like any other.

## 6. Scoring and outcome

### Points per guess

| Guess | Points |
| --- | --- |
| Correct (a bot marked bot, a human marked human) | +1 |
| Wrong (a bot marked human, a human marked bot) | −1 |

A human's score is the sum over all their guesses: one mark for each other participant, as it stands when voting ends, each worth +1 or −1. Marking a human as human earns a point; it is not worth 0.

### Who wins

- With 2 or more humans: the human with the highest score wins, even if that score is 0 or negative, because the game is relative: a player only has to do better than the other humans. If the top score is shared, those players draw. Everyone else loses.
- With exactly 1 human in the room (that human plus bots): a score above 0 is a win, exactly 0 is a draw, below 0 is a loss.
- Win, draw and loss apply to humans only. Bots have no score and no outcome.
- On a draw nobody is named the winner, and each human still gets win, draw or loss (the players who share the top score get draw).

### If a player disconnects

A player who disconnects keeps the marks they had at that moment, including the ones still at "human", and those marks count when voting ends. A player who disconnects before voting starts keeps every mark at "human".

A player who disconnects still counts as one of the humans when the winner is decided (a room with 2 humans stays a room with 2 humans), and gets a score and an outcome like every other human. A player who comes back before voting ends can still change their marks.

### Worked example A: 3 humans and 2 bots

Room of 5. Humans are Player 1, Player 2 and Player 4. Bots are Player 3 and Player 5. Each human marks the 4 other participants.

| Marked by | Player 1 | Player 2 | Player 3 | Player 4 | Player 5 | Score |
| --- | --- | --- | --- | --- | --- | --- |
| Player 1 | (self) | human ✓ | bot ✓ | human ✓ | bot ✓ | +1 +1 +1 +1 = **+4** |
| Player 2 | human ✓ | (self) | human ✗ | human ✓ | bot ✓ | +1 −1 +1 +1 = **+2** |
| Player 4 | bot ✗ | human ✓ | bot ✓ | (self) | bot ✓ | −1 +1 +1 +1 = **+2** |

Outcome: Player 1 has the highest score (+4) and wins. Player 2 and Player 4 share +2, but that is not the top score, so both lose.

Bot deception rates (humans whose mark on the bot was "human" when voting ended ÷ humans in the game):

- Player 3: marked by Player 1 as bot, by Player 2 as human, by Player 4 as bot. 1 of 3 → 33%.
- Player 5: marked as bot by all three. 0 of 3 → 0%.

If Player 1 had also scored +2, all three humans would share the top score and all three would draw.

### Worked example B: 1 human and 2 bots

Room of 3. The human is Player 2. Bots are Player 1 and Player 4.

| Guesses by Player 2 | Score | Outcome |
| --- | --- | --- |
| Player 1 bot ✓, Player 4 bot ✓ | +1 +1 = **+2** | Win (above 0) |
| Player 1 bot ✓, Player 4 human ✗ | +1 −1 = **0** | Draw |
| Player 1 human ✗, Player 4 human ✗ | −1 −1 = **−2** | Loss (below 0) |

In the first row both bots were marked as bots, so each has a deception rate of 0% (0 of 1). In the second row Player 4 has 100% (1 of 1) and Player 1 has 0%.

## 7. Results

Results appear only after the game has ended. They show:

- which labels were bots;
- every human's score and outcome (win, draw or loss);
- each bot's deception rate: the number of humans whose mark on that bot was "human" when voting ended (a mark left at the preset counts), divided by the number of humans in the game (players who disconnected included, section 6), as a percentage.

## 8. Summary of the numbers

| Item | Value |
| --- | --- |
| Participants per room | up to 5, at least 1 human |
| Bots per room | none, or 1 to 4, decided secretly by the server |
| Room timer | 3 minutes from room creation, never restarts |
| Discussion phase | 120 seconds |
| Voting phase | 45 seconds |
| Points per guess | +1 correct, −1 wrong; every mark starts at "human" and counts |
| Bot join delay | random, for example 10 to 30 seconds, configurable |

## 9. No bot leak (for implementers)

Nothing before the results may show which participants are bots or whether the room has any. Players who can tell bots from humans by anything other than the chat itself would break the game.

Rules for implementers (BE-27, BE-10, BE-09, FE-31, FE-32):

- **Participant objects** have the same fields, with the same types, for bots and humans in every REST response and WebSocket event before the results. No `is_bot`, no null `user_id`, no extra or missing fields, no different id format. The result payload may carry `is_bot` only once the room is finished.
- **Labels** are drawn from the same random pool for bots and humans. Label order never follows join order or the bot / human split.
- **Identity before results**: clients know a participant only by its label number ("Player N", 1 to 5, stable for the room), never by the database participant id. This holds in the room state, chat messages, votes and every WebSocket event. A vote names its target by label number, and a chat message names its author by label number. Database ids may appear only in the results.
- **Default marks**: when voting starts, every other participant is marked "human" for each human voter, bots and humans alike. The server does not need to store this default: a target without a stored mark counts as "human". Nothing sent during voting differs between a bot target and a human target.
- **Join events** for bots and humans are the same event with the same shape. Bots join at random delays interleaved with humans; no bot joins in a burst or at a fixed offset from room creation.
- **Counts** shown to players (participants present, "Start now" visibility, start conditions) always include bots. A count of humans only is never exposed.
- **The last human leaves**: when the last human leaves the waiting room, the room just closes. Nothing sent to any client reveals whether the room had bots or planned any.
- **The bot plan** (whether the room has bots, how many, when they join) is chosen on the server, kept on the server and never sent to a client before the results. A planned bot that has not joined when the game starts is dropped silently; nothing tells a client that a bot was planned.
- **Timing and behaviour**: bot chat messages go through the same event and the same fields as human messages, with typing delays and message rates in the range of human behaviour. Bots have no profile, so no profile link or avatar exists for any participant.
- **Waiting room and phase events** carry the same data in every room, whether or not it has bots.
- **Result fields**: on a draw `winner_participant_ids` is empty and `is_draw` is true; each human participant carries its own `outcome` (win, draw or loss).

## Changes

**2026-11-15**, decided by byul-byul (PO); answers Khalil-QadDoura's questions of 2026-11-08 on the DOC-08 card:

1. **Changing a mark**: a human may change any mark any number of times until the voting phase ends; the marks at the end count (section 5).
2. **Default marks, no "no guess"**: every other participant starts marked "human", and every mark counts, +1 or −1. The "no guess = 0" rule is removed. A player who disconnects keeps the marks they had at that moment instead of scoring 0 for missing guesses (sections 5, 6 and 8).
3. **Identity**: before the results, clients see participants only by label number, never by database participant id; votes name their target by label number (section 9).

**2026-11-16**, decided by byul-byul (PO); confirms Khalil-QadDoura's reading on PR #60 and settles his wording question:

4. **Disconnected players**: a player who disconnects still counts as one of the humans when the winner is decided and gets a score and an outcome; a player who comes back before voting ends can still change their marks (section 6).
5. **Deception rate**: humans whose mark on the bot was "human" when voting ended (preset marks count), divided by all humans in the game. The "—" case is gone: every game has a human, and every human has a mark on every bot (sections 6 and 7).
