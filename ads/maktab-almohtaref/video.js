// Render the poster timeline to MP4, optionally with a soundtrack.
// usage: node video.js poster.html out.mp4 width height size [soundtrack.wav]
// (needs FFMPEG env var pointing at an ffmpeg with libx264)
const { chromium } = require('playwright');
const { spawn } = require('child_process');
const path = require('path');
const FPS = 30;
(async () => {
  const [,, html, out, w, h, size, audio] = process.argv;
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: +w, height: +h }, deviceScaleFactor: 1 });
  await page.goto('file://' + path.resolve(html) + `?s=${size}&v=1`);
  await page.evaluate(() => window.animReady);
  const frames = Math.round((await page.evaluate(() => window.DUR)) * FPS);
  const inputs = ['-f', 'image2pipe', '-framerate', String(FPS), '-i', '-'];
  const audioArgs = audio ? ['-i', audio, '-map', '0:v', '-map', '1:a', '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-shortest'] : [];
  const ff = spawn(process.env.FFMPEG || 'ffmpeg', ['-y', '-loglevel', 'error', ...inputs, ...audioArgs,
    '-c:v', 'libx264', '-preset', 'slow', '-crf', '17', '-pix_fmt', 'yuv420p', '-profile:v', 'high', '-movflags', '+faststart', out],
    { stdio: ['pipe', 'inherit', 'inherit'] });
  for (let i = 0; i < frames; i++) {
    await page.evaluate(t => window.seek(t), i / FPS);
    const png = await page.screenshot({ type: 'png' });
    if (!ff.stdin.write(png)) await new Promise(r => ff.stdin.once('drain', r));
  }
  ff.stdin.end();
  await new Promise(r => ff.on('close', r));
  await browser.close();
  console.log('wrote', out, frames, 'frames', audio ? 'with audio' : 'silent');
})();
