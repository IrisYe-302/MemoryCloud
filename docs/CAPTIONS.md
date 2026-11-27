# Multilingual print captions

Type or paste Chinese (simplified/traditional), Japanese, Korean, Russian, English, or emoji into “A few words”. No language selector is required. The same renderer makes previews and the printer raster. IME composition is allowed to finish before refreshing the preview.

Pi installation and update scripts install `fonts-noto-cjk` and `fonts-noto-color-emoji` before stopping the service. Font installation requires Internet access on the Pi. The server uses Noto Sans CJK for multilingual text and Noto Color Emoji for emoji, rendered into black-and-white pixels. Apple keyboard input works through Unicode, but the Pi's artwork differs from Apple's. New emoji not present in the installed font may not render correctly, and small printed emoji lose color/detail.

Captions wrap by measured pixel width, preserve explicit newlines, and keep emoji ZWJ sequences, modifiers, regional flags, and combining marks together. The 120-character limit remains; the renderer avoids truncating within a complete cluster. Tall photo/caption combinations beyond the 384-dot printer's raster limit return an explanatory error.

For local Mac development, Arial Unicode and Apple Color Emoji are used if Noto is not installed. `MEMORY_CAPTION_FONT` and `MEMORY_EMOJI_FONT` can override the font file paths. Restart the service after changing fonts. The sample checks also run with official Noto font files to verify Pi-style output.

Sources: [Noto CJK coverage](https://notofonts.github.io/noto-docs/specimen/NotoSansCJKsc/) and [Noto Emoji](https://github.com/googlefonts/noto-emoji).
