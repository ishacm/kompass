"""Regenerate the README GIFs (original artwork, no third-party media).
Usage: python docs/make_gifs.py     -> docs/gifs/*.gif
"""
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).parent / "gifs"
OUT.mkdir(exist_ok=True)
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
BG, PANEL, INK, MUTED = (15, 23, 42), (30, 41, 59), (226, 232, 240), (148, 163, 184)
AMBER, GREEN, RED, BLUE = (245, 158, 11), (34, 197, 94), (239, 68, 68), (96, 165, 250)


def f(path, size):
    return ImageFont.truetype(path, size)


def centered(d, xy, text, font, fill):
    w = d.textlength(text, font=font)
    d.text((xy[0] - w / 2, xy[1]), text, font=font, fill=fill)


def save(frames, name, durations):
    frames[0].save(OUT / name, save_all=True, append_images=frames[1:], duration=durations, loop=0,
                   optimize=True, disposal=2)
    print(name, (OUT / name).stat().st_size // 1024, "KB")


# ---------------------------------------------------------------- 1. hero: the indecisive compass
def hero():
    W, H = 720, 300
    frames, dur = [], []
    angle = 0.0
    steps = 46
    for i in range(steps):
        speed = 38 * (1 - i / steps) ** 1.6
        angle += speed
        settling = i >= steps - 12
        target = -35
        if settling:
            k = (i - (steps - 12)) / 11
            angle = angle * (1 - k) + (angle - (angle % 360) + 360 + target) * k
        im = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(im)
        cx, cy, r = 150, 150, 96
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=PANEL, outline=MUTED, width=3)
        for a, lab in ((0, "N"), (90, "E"), (180, "S"), (270, "W")):
            x = cx + (r - 18) * math.sin(math.radians(a))
            y = cy - (r - 18) * math.cos(math.radians(a))
            centered(d, (x, y - 9), lab, f(BOLD, 15), MUTED)
        a = math.radians(angle)
        tip = (cx + (r - 30) * math.sin(a), cy - (r - 30) * math.cos(a))
        tail = (cx - (r - 45) * math.sin(a), cy + (r - 45) * math.cos(a))
        side = (6 * math.cos(a), 6 * math.sin(a))
        d.polygon([tip, (cx + side[0], cy + side[1]), (cx - side[0], cy - side[1])], fill=AMBER)
        d.polygon([tail, (cx + side[0], cy + side[1]), (cx - side[0], cy - side[1])], fill=MUTED)
        d.ellipse([cx - 7, cy - 7, cx + 7, cy + 7], fill=INK)
        d.text((290, 60), "kompass", font=f(BOLD, 40), fill=INK)
        if not settling:
            msgs = ["reading 500 job boards...", "hmm, is this a cobot company?", "checking the ICP. again."]
            d.text((292, 130), msgs[(i // 8) % 3], font=f(FONT, 22), fill=MUTED)
        else:
            d.text((292, 120), "found one.", font=f(BOLD, 24), fill=GREEN)
            d.text((292, 156), "Tier A  ·  hiring a Founding AE  [S1]", font=f(FONT, 20), fill=INK)
            d.text((292, 186), "a real reason to talk, with a source", font=f(FONT, 18), fill=MUTED)
        frames.append(im)
        dur.append(70)
    dur[-1] = 2600
    save(frames, "hero.gif", dur)


# ---------------------------------------------------------------- 2. volume is not a strategy
def spam():
    W, H = 720, 320
    frames, dur = [], []
    for i in range(34):
        im = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(im)
        d.rounded_rectangle([16, 16, 352, 304], 14, fill=PANEL)
        d.rounded_rectangle([368, 16, 704, 304], 14, fill=PANEL)
        d.text((32, 28), "AI SDR, 3 a.m.", font=f(BOLD, 20), fill=RED)
        d.text((384, 28), "Kompass", font=f(BOLD, 20), fill=GREEN)
        n = min(i + 1, 26)
        for k in range(n):
            x = 34 + (k % 4) * 78 + (k * 7) % 9
            y = 70 + (k // 4) * 30 + (k * 3) % 5
            d.rounded_rectangle([x, y, x + 70, y + 24], 4, fill=(51, 65, 85))
            d.text((x + 5, y + 5), "Quick q?", font=f(FONT, 11), fill=MUTED)
        d.text((32, 276), f"sent: {n * 431:,}   replies: crickets", font=f(MONO, 13), fill=MUTED)
        if i > 6:
            d.rounded_rectangle([392, 82, 680, 178], 8, fill=(51, 65, 85), outline=GREEN, width=2)
            d.text((406, 92), "Saw the Founding AE role [S1].", font=f(FONT, 14), fill=INK)
            d.text((406, 114), "Happy to share the account list", font=f(FONT, 14), fill=INK)
            d.text((406, 136), "I'd hand them on day one.", font=f(FONT, 14), fill=INK)
        if i > 14:
            d.text((392, 196), "cites its source", font=f(FONT, 15), fill=BLUE)
        if i > 19:
            d.text((392, 222), "approved by a human", font=f(FONT, 15), fill=GREEN)
        if i > 24:
            d.text((392, 248), "sent once, on LinkedIn (DACH rules)", font=f(FONT, 15), fill=AMBER)
        frames.append(im)
        dur.append(140)
    dur[-1] = 3000
    save(frames, "volume.gif", dur)


# ---------------------------------------------------------------- 3. the CI gate bouncer
def gate():
    W, H = 720, 260
    frames, dur = [], []

    def scene(card_x, label, color, verdict=None, vcolor=None, light=AMBER, live=None):
        im = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(im)
        d.rectangle([560, 40, 690, 220], fill=PANEL, outline=MUTED, width=2)
        centered(d, (625, 52), "PRODUCTION", f(BOLD, 15), MUTED)
        d.rounded_rectangle([470, 90, 540, 220], 10, fill=(51, 65, 85))
        centered(d, (505, 100), "CI", f(BOLD, 18), AMBER)
        centered(d, (505, 124), "gate", f(FONT, 14), MUTED)
        d.ellipse([489, 150, 521, 182], fill=light)
        if live:
            centered(d, (625, 120), live, f(BOLD, 20), GREEN)
            centered(d, (625, 150), "live", f(FONT, 15), MUTED)
        d.rounded_rectangle([card_x, 110, card_x + 230, 180], 8, fill=PANEL, outline=color, width=2)
        d.text((card_x + 12, 120), label[0], font=f(BOLD, 15), fill=color)
        d.text((card_x + 12, 146), label[1], font=f(FONT, 13), fill=INK)
        if verdict:
            d.text((30, 210), verdict, font=f(BOLD, 18), fill=vcolor)
        d.text((30, 20), "Every prompt change has to get past the golden set.", font=f(FONT, 17), fill=INK)
        return im

    bad = ("prompt v900", "\"we guarantee 300% growth!\"")
    good = ("prompt v2", "cited, 3 sentences, no hype")
    for x in range(20, 230, 18):
        frames.append(scene(x, bad, RED)); dur.append(60)
    for _ in range(3):
        frames.append(scene(230, bad, RED, "BLOCKED: unsupported claim, invented number", RED, light=RED)); dur.append(500)
    for x in range(230, -240, -40):
        frames.append(scene(x, bad, RED, "BLOCKED: unsupported claim, invented number", RED)); dur.append(50)
    for x in range(20, 232, 18):
        frames.append(scene(x, good, GREEN)); dur.append(60)
    frames.append(scene(230, good, GREEN, light=GREEN)); dur.append(500)
    frames.append(scene(230, good, GREEN, "passed: shipped as an A/B test", GREEN, light=GREEN, live="v2"))
    dur.append(2600)
    save(frames, "gate.gif", dur)


# ---------------------------------------------------------------- 4. the real demo, in a terminal
def demo():
    W, H = 760, 420
    lines = [
        ("$ python scripts/demo.py", INK),
        ("MODULE 1  context layer      5 rows -> 4 accounts, 1 duplicate merged", MUTED),
        ("MODULE 2  signal agent       6 postings -> 4 signals -> 1 cited draft", MUTED),
        ("          send to: founder_ceo via linkedin_or_phone (UWG s.7)", BLUE),
        ("          why now: hiring a Founding Account Executive [S1]", BLUE),
        ("          reviewer edited it: edit distance 0.558", AMBER),
        ("MODULE 3  CI/CD lab          v1 vs v2 on the golden set: gate passed", MUTED),
        ("MODULE 4  AEO radar          24 answers, DE vs EN share of voice", MUTED),
        ("MODULE 5  inbound agent      50 test leads, 98% routed correctly", MUTED),
        ("", INK),
        ("mock mode + fixtures: shows it works, not results to publish", GREEN),
    ]
    frames, dur = [], []

    def draw(n_lines, partial=None):
        im = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(im)
        d.rounded_rectangle([10, 10, W - 10, H - 10], 12, fill=(2, 6, 23))
        for k, c in enumerate([RED, AMBER, GREEN]):
            d.ellipse([28 + k * 20, 26, 40 + k * 20, 38], fill=c)
        y = 60
        for text, col in lines[:n_lines]:
            d.text((28, y), text, font=f(MONO, 14), fill=col); y += 28
        if partial is not None:
            d.text((28, y), partial + "_", font=f(MONO, 14), fill=INK)
        return im

    cmd = lines[0][0]
    for k in range(2, len(cmd) + 1, 2):
        frames.append(draw(0, cmd[:k])); dur.append(45)
    for n in range(1, len(lines) + 1):
        frames.append(draw(n)); dur.append(420)
    dur[-1] = 3200
    save(frames, "demo.gif", dur)


if __name__ == "__main__":
    hero(); spam(); gate(); demo()
