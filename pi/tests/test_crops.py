import tempfile
import unittest
from pathlib import Path
from PIL import Image, ImageDraw
from imaging import render


class CropTests(unittest.TestCase):
    def test_shapes_and_position(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'wide.png'
            source=Image.new('RGB',(600,300),'white')
            ImageDraw.Draw(source).rectangle((0,0,299,299),fill='black')
            source.save(path)
            base={'frame':'plain','mode':'threshold'}
            square=render(path,base)
            portrait=render(path,{**base,'aspect':'portrait'})
            landscape=render(path,{**base,'aspect':'landscape'})
            original=render(path,{**base,'aspect':'original'})
            self.assertGreater(portrait.height,square.height)
            self.assertLess(landscape.height,square.height)
            self.assertEqual(original.height,8+184+24)
            left=render(path,{**base,'crop_x':0})
            right=render(path,{**base,'crop_x':1})
            self.assertEqual(left.getpixel((100,100)),0)
            self.assertEqual(right.getpixel((100,100)),255)
            self.assertEqual(render(path,{**base,'zoom':2}).size,square.size)
            for options in ({'zoom':0},{'zoom':float('nan')},{'crop_y':2},{'aspect':'bad'}):
                with self.assertRaises(ValueError):
                    render(path,options)
