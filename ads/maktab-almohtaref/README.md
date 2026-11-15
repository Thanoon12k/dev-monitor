# Maktab Al-Muhtarif — plagiarism & AI-score reduction ad

Sponsored-post creative for the Facebook/Instagram page "مكتب المحترف": reducing or zeroing the Turnitin
similarity score and AI-writing score. Poster images, 15 s videos with an original soundtrack, and the post copy.

| File | Use |
|---|---|
| `out/poster-feed-1080x1350.png` | Feed image (4:5) |
| `out/poster-story-1080x1920.png` | Stories/Reels image (9:16) |
| `out/poster-square-1080x1080.png` | Square image (1:1) |
| `out/video-feed-1080x1350.mp4` | Feed video, 15 s, music + sound effects |
| `out/video-story-1080x1920.mp4` | Stories/Reels video, 15 s, music + sound effects |
| `copy.md` | Post text, headline, first comment, greeting message, A/B test notes |

## Editing and re-rendering

Text and layout live in `poster.src.html`; the video timeline is `anim.js`; the soundtrack is synthesised by
`audio.py` (128 BPM, 8 bars — its cue times match `anim.js`). `build.py` inlines fonts, the traced brand mark
and the timeline into `poster.html`.

```bash
npm i playwright && pip install imageio-ffmpeg numpy scipy pyloudnorm
export FFMPEG=$(python3 -c "import imageio_ffmpeg;print(imageio_ffmpeg.get_ffmpeg_exe())")
python3 build.py
python3 audio.py out/soundtrack.wav
node shot.js poster.html out/poster-feed-1080x1350.png 1080 1350 s=feed           # s=story 1080x1920, s=square 1080x1080
node video.js poster.html out/video-feed-1080x1350.mp4 1080 1350 feed out/soundtrack.wav   # or: 1080 1920 story
```

Fonts: Alexandria and Readex Pro (SIL Open Font License, see `fonts/`).
