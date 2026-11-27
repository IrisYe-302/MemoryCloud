import tempfile
import unittest
from pathlib import Path
from PIL import Image, ImageStat
from imaging import render


class ProcessingTests(unittest.TestCase):
    def test_modes_and_tone_controls(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'gradient.png'
            Image.linear_gradient('L').resize((300,300)).save(path)
            def output(**options):
                return render(path,{'frame':'plain','contrast':1,'auto_levels':False,**options})
            def lightness(image):
                return ImageStat.Stat(image.convert('L')).mean[0]
            fine=output(mode='dither')
            soft=output(mode='soft')
            ordered=output(mode='ordered')
            self.assertEqual(soft.mode,'1')
            self.assertEqual(ordered.mode,'1')
            self.assertEqual(fine.size,ordered.size)
            self.assertNotEqual(fine.tobytes(),ordered.tobytes())
            self.assertGreater(lightness(soft),lightness(fine))
            self.assertGreater(lightness(output(mode='threshold',threshold=80)),lightness(output(mode='threshold',threshold=180)))
            self.assertGreater(lightness(output(brightness=1.5)),lightness(output(brightness=0.7)))
            for options in ({'brightness':float('nan')},{'brightness':2},{'threshold':0},{'threshold':float('inf')},{'auto_levels':'yes'}):
                with self.assertRaises(ValueError):
                    output(**options)
