"""Turing Duel scoring: points, win / draw / loss and each bot's deception rate.

Pure rules, no database: docs/game/turing-duel-rules.md, sections 5 to 7.
Participants are given by their ids; `marks` holds only the marks a human actually sent,
keyed by (voter id, target id). A mark that was never sent counts as "human".
"""

from app.game.constants import DEFAULT_GUESS, POINTS_CORRECT, POINTS_WRONG

Marks = dict[tuple[int, int], str]


def mark_of(marks: Marks, voter_id: int, target_id: int) -> str:
    """The voter's mark on the target when voting ended; "human" if they never changed it."""
    return marks.get((voter_id, target_id), DEFAULT_GUESS)


def human_score(voter_id: int, everyone: list[int], bot_ids: set[int], marks: Marks) -> int:
    """+1 for each right mark, -1 for each wrong one, over every other participant."""
    score = 0
    for target_id in everyone:
        if target_id == voter_id:
            continue
        truth = "bot" if target_id in bot_ids else "human"
        right = mark_of(marks, voter_id, target_id) == truth
        score += POINTS_CORRECT if right else POINTS_WRONG
    return score


def outcomes(scores: dict[int, int]) -> dict[int, str]:
    """Win, draw or loss for each human, from the humans' scores (section 6)."""
    if not scores:
        return {}
    if len(scores) == 1:
        # One human against bots: above 0 wins, exactly 0 draws, below 0 loses.
        [(human_id, score)] = scores.items()
        if score > 0:
            return {human_id: "win"}
        return {human_id: "draw" if score == 0 else "loss"}
    # Two or more humans: the top score wins; a shared top score is a draw for those players.
    top = max(scores.values())
    top_shared = list(scores.values()).count(top) > 1
    result = {}
    for human_id, score in scores.items():
        if score < top:
            result[human_id] = "loss"
        else:
            result[human_id] = "draw" if top_shared else "win"
    return result


def deception_rate(bot_id: int, human_ids: list[int], marks: Marks) -> int:
    """Percentage (0-100) of the humans whose mark on this bot was "human" when voting ended."""
    if not human_ids:
        return 0
    fooled = sum(1 for human_id in human_ids if mark_of(marks, human_id, bot_id) == "human")
    return round(100 * fooled / len(human_ids))
