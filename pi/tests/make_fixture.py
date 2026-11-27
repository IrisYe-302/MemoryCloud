"""Create a deterministic grayscale calibration image for manual upload testing."""
from PIL import Image, ImageDraw

image = Image.new('RGB', (640, 640), 'white')
draw = ImageDraw.Draw(image)
for x in range(640):
    shade = int(x * 255 / 639)
    draw.line((x, 0, x, 400), fill=(shade, shade, shade))
for i in range(8):
    draw.rectangle((i*80, 420, i*80+39, 540), fill='black')
draw.text((30, 580), 'THERMAL CALIBRATION / MEMORY CLOUD', fill='black')
image.save('/private/tmp/memory-cloud-calibration.png')
