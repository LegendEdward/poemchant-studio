"""Draw a code-authored icon; no third-party artwork or bundled system font."""
from pathlib import Path
import subprocess
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
folder = ROOT / 'build' / 'PoemChant.iconset'
folder.mkdir(parents=True, exist_ok=True)
size = 1024
image = Image.new('RGBA', (size, size), (0, 0, 0, 0))
draw = ImageDraw.Draw(image)
draw.rounded_rectangle((45, 45, 979, 979), radius=207, fill='#e9eee2')
draw.rounded_rectangle((112, 112, 912, 912), radius=160, fill='#286b5e')
# Three lyric blocks and a continuous, non-notated phrase curve.
for x in (270, 470, 670):
    draw.rounded_rectangle((x, 590, x+84, 688), radius=16, fill='#faf8ec')
curve = [(225, 470), (320, 425), (385, 440), (448, 495), (540, 390), (638, 350), (733, 395), (800, 330)]
draw.line(curve, fill='#faf8ec', width=22, joint='curve')
for x, y in (curve[0], curve[4], curve[-1]):
    draw.ellipse((x-17, y-17, x+17, y+17), fill='#dab587')
for resolution in (16, 32, 128, 256, 512):
    image.resize((resolution, resolution), Image.Resampling.LANCZOS).save(folder / f'icon_{resolution}x{resolution}.png')
    image.resize((resolution*2, resolution*2), Image.Resampling.LANCZOS).save(folder / f'icon_{resolution}x{resolution}@2x.png')
subprocess.run(['iconutil', '-c', 'icns', str(folder), '-o', str(ROOT / 'native' / 'PoemChant.icns')], check=True)
