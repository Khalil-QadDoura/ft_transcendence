"""Draw a self-contained GitHub README GIF. Requires Pillow; no downloaded assets."""

from pathlib import Path
import math
import os

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets"
W, H, SCALE = 960, 584, 2
BG = "#101322"
PANEL = "#191E32"
WHITE = "#F5F0E7"
MUTED = "#A6AEC9"
COLORS = ["#B5A1FF", "#FFD070", "#76DFC6", "#FF91B0"]
LABELS = ["THE PLANNER", "THE SPEEDRUNNER", "THE GHOST", "YOU"]
DIALOGUE = [
    [("made a", "group chat"), ("should take", "5 minutes"), ("last seen:", "syllabus day"), ("opened", "the README")],
    [("let's have", "a meeting"), ("wait, there's", "a rubric?"), ("", "..."), ("this counts", "as a commit")],
    [("made another", "group chat"), ("works on", "my imagination"), ("sorry just", "saw this"), ("carrying", "the vibes")],
    [("great meeting", "everyone"), ("we still", "have time"), ("", "[disconnected]"), ("at least", "it dances")],
]
LOG = [
    "> Waiting for someone to say: 'I'll start.'",
    "> Scope increased. Confidence inexplicably unchanged.",
    "> Someone is typing... It's been 40 minutes.",
    "> No code detected. Deploying additional optimism.",
]


def font(size, bold=False):
    name = "consolab.ttf" if bold else "consola.ttf"
    candidates = [
        Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name,
        Path("/usr/share/fonts/truetype/dejavu") / ("DejaVuSansMono-Bold.ttf" if bold else "DejaVuSansMono.ttf"),
        Path("/System/Library/Fonts/Menlo.ttc"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size * SCALE)
    return ImageFont.load_default(size=size * SCALE)


FONTS = {(size, bold): font(size, bold) for size, bold in [(13, False), (14, False), (15, True), (16, False), (17, True), (19, True), (40, True)]}


def render(frame):
    im = Image.new("RGB", (W * SCALE, H * SCALE), BG)
    d = ImageDraw.Draw(im)
    phase = frame * math.tau / 24
    scene = frame // 24

    def box(xy, fill, outline=None, radius=0, width=1):
        coords = tuple(round(v * SCALE) for v in xy)
        if radius:
            d.rounded_rectangle(coords, radius * SCALE, fill=fill, outline=outline, width=width * SCALE)
        else:
            d.rectangle(coords, fill=fill, outline=outline, width=width * SCALE)

    def line(points, fill, width=2):
        d.line([(round(x * SCALE), round(y * SCALE)) for x, y in points], fill=fill, width=width * SCALE)

    def ellipse(xy, fill):
        d.ellipse(tuple(round(v * SCALE) for v in xy), fill=fill)

    def text(x, y, value, size=16, fill=WHITE, bold=False, anchor="mm"):
        d.text((round(x * SCALE), round(y * SCALE)), value, font=FONTS[size, bold], fill=fill, anchor=anchor)

    box((20, 20, 940, 564), PANEL, "#353C59", radius=18)
    line([(21, 65), (939, 65)], "#353C59", 1)
    for x, color in zip((44, 63, 82), ("#FF7C89", "#FFD070", "#76DFC6")):
        ellipse((x - 5, 38, x + 5, 48), color)
    text(109, 44, "group-project.exe", 14, MUTED, anchor="lm")
    ellipse((762, 39, 770, 47), COLORS[2])
    text(910, 44, "4 PLAYERS / 0 CODE", 13, MUTED, anchor="rm")

    text(480, 98, "INVITE ACCEPTED. PRODUCTIVITY PENDING.", 15, COLORS[2], True)
    text(480, 143, "THE GROUP PROJECT LOBBY", 40, WHITE, True)
    text(480, 183, "The assignment hasn't started. The side quest has.", 16, MUTED)

    # A small grid provides a stage for the world's least productive dance crew.
    for y in (363, 380, 400):
        line([(55, y), (905, y)], "#252C46", 1)
    for x in range(70, 920, 70):
        line([(480 + (x - 480) * .7, 350), (x, 402)], "#252C46", 1)

    for idx, cx in enumerate((165, 375, 585, 795)):
        color = COLORS[idx]
        p = phase + idx * .8
        bounce = math.sin(p) * 6
        sway = math.sin(p / 1) * 5
        cy = 323 + bounce
        body_x = cx + sway

        box((cx - 92, 214, cx + 92, 270), "#232A43", "#3E4869", radius=10)
        line([(cx - 7, 270), (cx, 277), (cx + 7, 270)], "#3E4869", 1)
        a, b = DIALOGUE[scene][idx]
        text(cx, 233, a, 14, WHITE)
        text(cx, 253, b, 14, WHITE)

        shadow_width = 51 + bounce * .6
        ellipse((cx - shadow_width, 384, cx + shadow_width, 395), "#0D1020")
        # Legs and shoes, with alternating kicks.
        for side in (-1, 1):
            hip_x = body_x + side * 22
            foot_x = hip_x + side * 7 + math.sin(p + side) * 13
            foot_y = 379 - max(0, math.sin(p + (0 if side == 1 else math.pi))) * 10
            line([(hip_x, cy + 24), (hip_x + side * 5, cy + 41), (foot_x, foot_y)], color, 7)
            box((foot_x - 9, foot_y - 3, foot_x + 11, foot_y + 4), WHITE, radius=3)

        # Flailing arms are a core feature, not a bug.
        for side in (-1, 1):
            elbow_x = body_x + side * 68
            elbow_y = cy + math.sin(p + side) * 9
            hand_x = body_x + side * (77 + math.cos(p) * 4)
            hand_y = cy - 21 + math.sin(p + side) * 17
            line([(body_x + side * 47, cy + 3), (elbow_x, elbow_y), (hand_x, hand_y)], color, 6)
            ellipse((hand_x - 5, hand_y - 5, hand_x + 5, hand_y + 5), WHITE)

        box((body_x - 48, cy - 37, body_x - 9, cy - 18), color, radius=5)
        box((body_x - 50, cy - 25, body_x + 50, cy + 31), color, radius=7)
        line([(body_x - 40, cy - 16), (body_x + 39, cy - 16)], "#FFFFFF", 2)
        blink = frame % 48 in (idx * 3, idx * 3 + 1)
        for eye_x in (body_x - 15, body_x + 15):
            if blink or (idx == 2 and scene == 3):
                line([(eye_x - 4, cy), (eye_x + 4, cy)], BG, 3)
            else:
                box((eye_x - 3, cy - 5, eye_x + 3, cy + 3), BG, radius=2)
        if idx == 1:  # Extremely confident sunglasses.
            box((body_x - 25, cy - 8, body_x - 6, cy + 4), BG, radius=3)
            box((body_x + 6, cy - 8, body_x + 25, cy + 4), BG, radius=3)
            line([(body_x - 6, cy - 4), (body_x + 6, cy - 4)], BG, 3)
        line([(body_x - 7, cy + 12), (body_x, cy + 17), (body_x + 7, cy + 12)], BG, 3)
        if idx == 0:
            box((body_x + 26, cy + 10, body_x + 43, cy + 24), WHITE, radius=2)
            line([(body_x + 30, cy + 15), (body_x + 39, cy + 15)], BG, 1)

        # Musical notes drift up and disappear at the top of their short loop.
        note_y = 340 - (frame * 2 + idx * 17) % 55
        note_x = cx + 90
        ellipse((note_x - 6, note_y, note_x + 1, note_y + 5), color)
        line([(note_x + 1, note_y + 2), (note_x + 1, note_y - 12), (note_x + 7, note_y - 9)], color, 2)

        text(cx, 422, LABELS[idx], 17, color, True)
        text(cx, 447, ["PLANNING", "ESTIMATING", "BUFFERING", "VIBING"][idx] + "." * (1 + (frame // 8) % 3), 13, MUTED)

    line([(48, 471), (912, 471)], "#353C59", 1)
    text(49, 493, "ACTUAL PROGRESS", 13, MUTED, anchor="lm")
    box((215, 485, 628, 501), "#0E1223", "#353C59", radius=5)
    # The loading marker runs forever, while actual progress stubbornly stays at 0%.
    marker_x = 220 + ((frame * 7) % 362)
    box((marker_x, 489, marker_x + 38, 497), COLORS[0], radius=3)
    text(654, 493, "0%", 15, WHITE, True)
    text(909, 493, "VIBES: 100%", 15, COLORS[2], True, anchor="rm")
    text(49, 534, LOG[scene], 16, WHITE, anchor="lm")
    text(910, 534, "|/-\\"[(frame // 3) % 4], 19, COLORS[1], True, anchor="rm")
    return im.resize((W, H), Image.Resampling.LANCZOS)


def main():
    OUT.mkdir(exist_ok=True)
    frames = [render(frame) for frame in range(96)]
    # One shared palette prevents color flicker between frames.
    palette = frames[0].quantize(colors=128, method=Image.Quantize.MEDIANCUT)
    indexed = [frame.quantize(palette=palette, dither=Image.Dither.NONE) for frame in frames]
    path = OUT / "group-project-lobby.gif"
    indexed[0].save(path, save_all=True, append_images=indexed[1:], duration=100, loop=0, optimize=True, disposal=1)
    print(f"Created {path} ({path.stat().st_size:,} bytes; {len(frames)} frames)")


if __name__ == "__main__":
    main()
