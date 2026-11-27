from PIL import Image, ImageOps, ImageEnhance, ImageDraw, ImageFont
from caption_text import caption_layout
import math
import hashlib


def duplicate_groups(photos, directory):
    """Conservative suggestions: identical pixels or very similar color/structure."""
    signatures = []
    for photo in photos:
        with Image.open(directory / (photo['id'] + '.jpg')) as image:
            image = ImageOps.exif_transpose(image).convert('RGB')
            exact = hashlib.sha256(str(image.size).encode() + image.tobytes()).hexdigest()
            gray = list(image.convert('L').resize((9,8)).get_flattened_data())
            bits = sum((gray[y*9+x] > gray[y*9+x+1]) << (y*8+x) for y in range(8) for x in range(8))
            small = list(image.resize((16,16)).get_flattened_data())
            signatures.append((photo,exact,bits,small,image.width/image.height))
    groups = []
    consumed = set()
    for i, anchor in enumerate(signatures):
        if i in consumed:
            continue
        matches = [dict(anchor[0], match='original')]
        for j in range(i+1,len(signatures)):
            if j in consumed:
                continue
            candidate = signatures[j]
            exact = anchor[1] == candidate[1]
            similar = False
            if not exact and abs(anchor[4]-candidate[4]) < 0.02 and (anchor[2]^candidate[2]).bit_count() <= 4:
                mse = sum((a-b)**2 for p,q in zip(anchor[3],candidate[3]) for a,b in zip(p,q))/(256*3)
                similar = mse <= 100
            if exact or similar:
                matches.append(dict(candidate[0],match='exact' if exact else 'similar'))
                consumed.add(j)
        if len(matches)>1:
            groups.append(matches)
    return groups


def correct_color(path, options):
    """Create an RGB edit without modifying the original photo."""
    values = {}
    for name, default, low, high in (('exposure',1,0.5,1.8), ('contrast',1,0.5,1.8),
                                     ('saturation',1,0,2), ('warmth',0,-1,1)):
        try:
            value = float(options.get(name, default))
        except (TypeError, ValueError):
            raise ValueError('Invalid color adjustment')
        if not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f'{name} must be between {low} and {high}')
        values[name] = value
    with Image.open(path) as source:
        photo = ImageOps.exif_transpose(source).convert('RGB')
    photo = ImageEnhance.Brightness(photo).enhance(values['exposure'])
    photo = ImageEnhance.Contrast(photo).enhance(values['contrast'])
    photo = ImageEnhance.Color(photo).enhance(values['saturation'])
    red, green, blue = photo.split()
    shift = values['warmth'] * 24
    red = red.point(lambda value: max(0,min(255,round(value+shift))))
    blue = blue.point(lambda value: max(0,min(255,round(value-shift))))
    return Image.merge('RGB',(red,green,blue))


def render(path, options):
    width = int(options.get('width', 384))
    if width not in (384, 576):
        raise ValueError('Choose 384 or 576 dots')
    contrast = float(options.get('contrast', 1.2))
    if not 0.5 <= contrast <= 2.5:
        raise ValueError('Contrast must be between 0.5 and 2.5')
    frame = options.get('frame', 'polaroid')
    if frame not in ('polaroid', 'plain', 'double'):
        raise ValueError('Unknown frame')
    mode = options.get('mode', 'dither')
    if mode not in ('dither', 'soft', 'ordered', 'threshold'):
        raise ValueError('Unknown rendering method')
    try:
        brightness = float(options.get('brightness', 1))
        threshold = float(options.get('threshold', 128))
    except (TypeError, ValueError):
        raise ValueError('Invalid brightness or threshold')
    if not math.isfinite(brightness) or not 0.5 <= brightness <= 1.8:
        raise ValueError('Brightness must be between 0.5 and 1.8')
    if not math.isfinite(threshold) or not 32 <= threshold <= 224:
        raise ValueError('Threshold must be between 32 and 224')
    auto_levels = options.get('auto_levels', True)
    if type(auto_levels) is not bool:
        raise ValueError('Auto levels must be on or off')
    caption = str(options.get('caption', ''))
    margin = 24 if frame != 'plain' else 8
    inner = width - margin * 2
    aspect = options.get('aspect', 'square')
    if aspect not in ('square', 'portrait', 'landscape', 'original'):
        raise ValueError('Choose a valid photo shape')
    try:
        zoom = float(options.get('zoom', 1))
        x = float(options.get('crop_x', 0.5))
        y = float(options.get('crop_y', 0.5))
    except (TypeError, ValueError):
        raise ValueError('Invalid crop controls')
    if not all(math.isfinite(v) for v in (zoom,x,y)) or not 1 <= zoom <= 3 or not 0 <= x <= 1 or not 0 <= y <= 1:
        raise ValueError('Crop position must be 0–1 and zoom must be 1–3')
    with Image.open(path) as src:
        source = ImageOps.exif_transpose(src).convert('L')
        ratio = {'square':1, 'portrait':2/3, 'landscape':3/2, 'original':source.width/source.height}[aspect]
        photo_height = max(1, round(inner / ratio))
        if photo_height > 4096:
            raise ValueError('This original shape is too tall; choose portrait instead')
        crop_width = min(source.width, source.height * ratio) / zoom
        crop_height = crop_width / ratio
        left = (source.width-crop_width)*x
        top = (source.height-crop_height)*y
        photo = source.resize((inner,photo_height), Image.Resampling.LANCZOS,
                              box=(left,top,left+crop_width,top+crop_height))
    if auto_levels:
        photo = ImageOps.autocontrast(photo)
    photo = ImageEnhance.Contrast(photo).enhance(contrast)
    photo = ImageEnhance.Brightness(photo).enhance(brightness)
    if mode == 'soft':
        # Lift shadows/midtones before dithering to reduce large dark areas.
        photo = photo.point(lambda p: round(255 * (p / 255) ** 0.7))
    if mode in ('dither', 'soft'):
        photo = photo.convert('1', dither=Image.Dither.FLOYDSTEINBERG)
    elif mode == 'ordered':
        # Bayer 4x4 yields an even, repeatable dot texture with true 1-bit output.
        bayer=((0,8,2,10),(12,4,14,6),(3,11,1,9),(15,7,13,5))
        pixels=photo.load()
        output=Image.new('1',photo.size)
        dots=output.load()
        for py in range(photo.height):
            for px in range(photo.width):
                dots[px,py]=255 if pixels[px,py] > (bayer[py%4][px%4]+0.5)*16 else 0
        photo=output
    else:
        photo = photo.point(lambda p: 255 if p >= threshold else 0, mode='1')
    caption_image = caption_layout(caption,inner)
    bottom = max(64 if frame == 'polaroid' else 16, 24 + (caption_image.height if caption_image else 0))
    if width==384 and margin+photo_height+bottom>4300:
        raise ValueError('This photo and caption are too tall; choose a shorter photo shape.')
    result = Image.new('1', (width, margin + photo_height + bottom), 1)
    result.paste(photo, (margin, margin))
    draw = ImageDraw.Draw(result)
    if frame == 'double':
        draw.rectangle((8, 8, width-9, result.height-9), outline=0, width=2)
    if caption_image:
        result.paste(caption_image,(margin,margin+photo_height+12))
    return result
