import tempfile
import unittest
from pathlib import Path
from PIL import Image
from caption_text import caption_layout, clusters, emoji_font, emoji_image, text_font
from imaging import render

class MultilingualCaptions(unittest.TestCase):
    def test_graphemes_keep_joined_emoji_flags_and_accents(self):
        self.assertEqual(clusters('👩🏽‍💻🇰🇷1️⃣❤️'),['👩🏽‍💻','🇰🇷','1️⃣','❤️'])
        self.assertEqual(clusters('и\u0306'),['й'])
        self.assertEqual(clusters('한'),['한'])

    def test_supported_scripts_have_glyphs_and_wrap(self):
        font=text_font(18)
        missing=bytes(font.getmask('\U0010ffff'))
        for caption in ('美好的回忆 繁體中文','楽しい思い出','소중한 추억','Прекрасные воспоминания'):
            for ch in caption.replace(' ',''):
                self.assertNotEqual(bytes(font.getmask(ch)),missing,ch)
            image=caption_layout(caption*5,336)
            self.assertEqual(image.mode,'1')
            self.assertEqual(image.width,336)
            self.assertGreater(image.height,30)

    def test_real_render_preserves_multilingual_caption_and_emoji(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'photo.png';Image.new('RGB',(400,400),'white').save(path)
            for caption in ('一起旅行 日本語 한국어 Привет 👩🏽‍💻 🇯🇵 ❤️','回忆'*60):
                result=render(path,{'caption':caption,'frame':'plain'})
                caption_part=result.crop((8,376,376,result.height)).convert('L')
                self.assertEqual(result.width,384)
                self.assertEqual(result.mode,'1')
                self.assertLess(caption_part.getextrema()[0],255)

    def test_emoji_is_rendered_as_one_monochrome_sprite(self):
        emoji_font()
        for text in ('👩🏽‍💻','🇰🇷','1️⃣','❤️'):
            image=emoji_image(text,22)
            self.assertLessEqual(max(image.size),22)
            self.assertEqual(image.getextrema()[0],0)
        self.assertIsNone(caption_layout('',336))
        self.assertGreater(caption_layout('Привет\n你好',336).height,caption_layout('Привет',336).height)
