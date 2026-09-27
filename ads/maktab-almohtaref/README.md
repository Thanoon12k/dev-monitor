# Maktab Al-Muhtarif — plagiarism-zeroing ad

Sponsored-post creative for the Facebook/Instagram page "مكتب المحترف": poster images, animated videos and the post copy.

| File | Use |
|---|---|
| `out/poster-feed-1080x1350.png` | Feed image (4:5) |
| `out/poster-story-1080x1920.png` | Stories/Reels image (9:16) |
| `out/poster-square-1080x1080.png` | Square image (1:1) |
| `out/video-feed-1080x1350.mp4` | Feed video, 14 s, silent |
| `out/video-story-1080x1920.mp4` | Stories/Reels video, 14 s, silent |
| `copy.md` | Post text, first comment, greeting message, A/B test notes |

## Editing and re-rendering

Text and layout live in `poster.src.html`; the video timeline is `anim.js`. `build.py` inlines fonts, the traced brand mark and the timeline into `poster.html`.

```bash
npm i playwright && pip install imageio-ffmpeg
python3 build.py
node shot.js poster.html out/poster-feed-1080x1350.png 1080 1350 s=feed      # s=story 1080x1920, s=square 1080x1080
FFMPEG=$(python3 -c "import imageio_ffmpeg;print(imageio_ffmpeg.get_ffmpeg_exe())") \
  node video.js poster.html out/video-feed-1080x1350.mp4 1080 1350 feed       # or: 1080 1920 story
```

Fonts: Alexandria and Readex Pro (SIL Open Font License, see `fonts/`).
