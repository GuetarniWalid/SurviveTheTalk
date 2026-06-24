"""Generate the Google Play feature graphic (1024x500) for "Survive the Talk".

On-brand per the "Handler's Brief": dark ground (#1E1F23), off-white text
(#F0F0F0), accent green (#00E5A0) as FILL ONLY (glow + a short bar — never as
text). Composes the real app icon + the wordmark in the app's own Frijole face.
Run with the server venv (Pillow installed):
    server/.venv/Scripts/python _bmad-output/planning-artifacts/store-assets/make_feature_graphic.py
"""

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

BASE = "C:/Users/gueta/Documents/Mes_projets/surviveTheTalk2"
OUT = f"{BASE}/_bmad-output/planning-artifacts/store-assets/play-feature-graphic-1024x500.png"
W, H = 1024, 500

BG_TOP = (32, 33, 38)
BG_BOT = (18, 19, 23)
TEXT = (240, 240, 240)   # #F0F0F0
TEXT2 = (138, 138, 149)  # #8A8A95
ACCENT = (0, 229, 160)   # #00E5A0

FRIJOLE = f"{BASE}/client/assets/fonts/frijole/Frijole-Regular.ttf"
INTER_SB = f"{BASE}/landing/public/fonts/inter/Inter-SemiBold.ttf"
ICON = f"{BASE}/client/assets/images/icon/app_icon.png"

# --- background gradient (top -> bottom) ---
img = Image.new("RGB", (W, H), BG_TOP)
d = ImageDraw.Draw(img)
for y in range(H):
    t = y / (H - 1)
    d.line(
        [(0, y), (W, y)],
        fill=(
            int(BG_TOP[0] + (BG_BOT[0] - BG_TOP[0]) * t),
            int(BG_TOP[1] + (BG_BOT[1] - BG_TOP[1]) * t),
            int(BG_TOP[2] + (BG_BOT[2] - BG_TOP[2]) * t),
        ),
    )
img = img.convert("RGBA")

# --- mark geometry ---
S = 336
mark_x, mark_y = 104, (H - S) // 2
cx, cy = mark_x + S // 2, mark_y + S // 2

# --- accent green glow behind the mark (FILL, not text) ---
glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
ImageDraw.Draw(glow).ellipse(
    [cx - 205, cy - 205, cx + 205, cy + 205], fill=(0, 229, 160, 52)
)
glow = glow.filter(ImageFilter.GaussianBlur(95))
img = Image.alpha_composite(img, glow)

# --- drop shadow under the mark ---
sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
ImageDraw.Draw(sh).rounded_rectangle(
    [mark_x + 6, mark_y + 18, mark_x + S + 6, mark_y + S + 18], radius=74, fill=(0, 0, 0, 140)
)
sh = sh.filter(ImageFilter.GaussianBlur(26))
img = Image.alpha_composite(img, sh)

# --- the app icon, rounded ---
icon = Image.open(ICON).convert("RGBA").resize((S, S), Image.LANCZOS)
mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=74, fill=255)
r, g, b, a = icon.split()
icon = Image.merge("RGBA", (r, g, b, ImageChops.multiply(a, mask)))
img.alpha_composite(icon, (mark_x, mark_y))

d = ImageDraw.Draw(img)

# --- wordmark, two lines, auto-fit to the right column ---
text_x = 512
max_w = W - text_x - 56
lines = ["SURVIVE", "THE TALK"]
size = 100
while size > 30:
    f = ImageFont.truetype(FRIJOLE, size)
    if max(d.textlength(s, font=f) for s in lines) <= max_w:
        break
    size -= 2
frij = ImageFont.truetype(FRIJOLE, size)
bb = d.textbbox((0, 0), "SURVIVE", font=frij)
line_h = bb[3] - bb[1]
gap = int(size * 0.40)
block_h = line_h * 2 + gap
y0 = (H - block_h) // 2 - 26

ty = y0
for s in lines:
    sb = d.textbbox((0, 0), s, font=frij)
    d.text((text_x, ty - sb[1]), s, font=frij, fill=TEXT)
    ty += line_h + gap

# --- accent bar (green FILL) + tagline below ---
bar_y = y0 + block_h + 22
d.rectangle([text_x + 2, bar_y, text_x + 92, bar_y + 6], fill=ACCENT)
inter = ImageFont.truetype(INTER_SB, 25)
d.text((text_x + 2, bar_y + 20), "Survive English phone calls", font=inter, fill=TEXT2)

# --- save flattened (no alpha — Play requires it) ---
img.convert("RGB").save(OUT, "PNG")
print("saved", OUT, "->", Image.open(OUT).size)
