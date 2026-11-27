"""Unicode caption layout for the same preview and physical print raster."""
from functools import lru_cache
from pathlib import Path
import os
import unicodedata
from PIL import Image, ImageDraw, ImageFont


def clusters(text):
    """Keep combining marks, emoji sequences, flags and modifiers together."""
    result=[]
    for ch in unicodedata.normalize('NFC',text.replace('\r\n','\n').replace('\r','\n')):
        n=ord(ch)
        extend=unicodedata.category(ch).startswith('M') or n in (0xfe0e,0xfe0f,0x200d) or 0x1f3fb<=n<=0x1f3ff or 0xe0020<=n<=0xe007f
        flag=0x1f1e6<=n<=0x1f1ff
        if result and (extend or result[-1].endswith('\u200d') or (flag and len(result[-1])==1 and 0x1f1e6<=ord(result[-1])<=0x1f1ff)):
            result[-1]+=ch
        else:
            result.append(ch)
    return result


def is_emoji(text):
    if '\ufe0e' in text: return False
    return '\ufe0f' in text or '\u20e3' in text or any(0x1f000<=ord(c)<=0x1faff or 0x2600<=ord(c)<=0x27bf for c in text)


@lru_cache(maxsize=12)
def text_font(size,region='SC'):
    candidates=[os.environ.get('MEMORY_CAPTION_FONT',''),
                '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
                '/System/Library/Fonts/Supplemental/Arial Unicode.ttf']
    for path in candidates:
        if not path or not Path(path).is_file(): continue
        font=ImageFont.truetype(path,size)
        if 'NotoSansCJK' in path:
            for index in range(5):
                candidate=ImageFont.truetype(path,size,index=index)
                if candidate.getname()[0].endswith(region): return candidate
        return font
    raise ValueError('Caption fonts are missing. Install fonts-noto-cjk on the Pi and restart the app.')


@lru_cache(maxsize=1)
def emoji_font():
    for path in (os.environ.get('MEMORY_EMOJI_FONT',''),'/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf','/System/Library/Fonts/Apple Color Emoji.ttc'):
        if not path or not Path(path).is_file(): continue
        for size in (109,64,160):
            try: return ImageFont.truetype(path,size)
            except OSError: pass
    raise ValueError('Emoji font is missing. Install fonts-noto-color-emoji on the Pi and restart the app.')


@lru_cache(maxsize=256)
def emoji_image(text,size):
    font=emoji_font()
    left,top,right,bottom=font.getbbox(text)
    image=Image.new('RGBA',(max(1,right-left),max(1,bottom-top)))
    ImageDraw.Draw(image).text((-left,-top),text,font=font,embedded_color=True)
    bounds=image.getbbox()
    if bounds: image=image.crop(bounds)
    image.thumbnail((size,size),Image.Resampling.LANCZOS)
    white=Image.new('RGB',image.size,'white');white.paste(image,mask=image.getchannel('A'))
    return white.convert('L').convert('1',dither=Image.Dither.FLOYDSTEINBERG).convert('L')


def caption_layout(caption,width):
    # Truncate only at whole clusters, never inside a joined emoji.
    parts=[];length=0
    for part in clusters(str(caption)):
        if length+len(part)>120: break
        parts.append(part);length+=len(part)
    if not parts or not ''.join(parts).strip(): return None
    text=''.join(p for p in parts if not is_emoji(p))
    region='JP' if any(0x3040<=ord(c)<=0x30ff for c in text) else 'KR' if any(0xac00<=ord(c)<=0xd7af for c in text) else 'SC'
    font=text_font(18,region) if any(ord(c)>127 for c in text) else ImageFont.load_default(size=15)
    ascent,descent=font.getmetrics();ascent=max(ascent,22);line_height=ascent+descent+5
    units=[]
    for part in parts:
        if part=='\n': units.append((part,0,None));continue
        if part=='\t': part=' '
        if is_emoji(part):
            sprite=emoji_image(part,22);units.append((part,24,sprite))
        else: units.append((part,float(font.getlength(part)),None))
    lines=[];line=[];used=0
    for unit in units:
        if unit[0]=='\n':lines.append(line);line=[];used=0;continue
        while line and used+unit[1]>width:
            # Prefer a word boundary for Russian/English; CJK can wrap without spaces.
            spaces=[i for i,u in enumerate(line) if u[0].isspace()]
            if spaces:
                at=spaces[-1];lines.append(line[:at]);line=line[at+1:]
            else:lines.append(line);line=[]
            used=sum(u[1] for u in line)
        if not line and unit[0].isspace():continue
        line.append(unit);used+=unit[1]
    if line:lines.append(line)
    image=Image.new('L',(width,len(lines)*line_height),255);draw=ImageDraw.Draw(image)
    for row,items in enumerate(lines):
        while items and items[-1][0].isspace():items.pop()
        x=(width-sum(u[1] for u in items))/2
        for text,advance,sprite in items:
            baseline=row*line_height+ascent
            if sprite is None:draw.text((x,baseline),text,font=font,fill=0,anchor='ls')
            else:image.paste(sprite,(round(x+(advance-sprite.width)/2),baseline-sprite.height))
            x+=advance
    return image.point(lambda p:255 if p>=170 else 0,mode='1')
