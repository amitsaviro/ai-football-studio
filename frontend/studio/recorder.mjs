// Records the studio tab (picture + sound) while a saved debate plays, then downloads the video.
// Used by /?replay=<id>&record=1 in a Chrome started with --auto-accept-this-tab-capture
// (see backend/scripts/record_video.sh), so no screen-recording software is needed.

const TYPES = ["video/mp4;codecs=avc1,mp4a.40.2", "video/mp4", "video/webm;codecs=vp9,opus", "video/webm"];

export async function record(play, name, setStatus) {
  const stream = await navigator.mediaDevices.getDisplayMedia({
    video: { frameRate: 30 }, audio: { suppressLocalAudioPlayback: false },
    preferCurrentTab: true, selfBrowserSurface: "include", systemAudio: "include",
  });
  const mimeType = TYPES.find(t => MediaRecorder.isTypeSupported(t));
  const recorder = new MediaRecorder(stream, { mimeType, videoBitsPerSecond: 3_500_000 });
  const chunks = [];
  recorder.ondataavailable = e => e.data.size && chunks.push(e.data);
  const stopped = new Promise(resolve => recorder.onstop = resolve);

  recorder.start(1000);
  await new Promise(r => setTimeout(r, 1000));  // a beat of the empty studio before the show
  play();
  while (!window.debateDone) await new Promise(r => setTimeout(r, 250));
  await new Promise(r => setTimeout(r, 2000));  // let the last words ring out
  recorder.stop();
  stream.getTracks().forEach(t => t.stop());
  await stopped;

  const ext = mimeType.startsWith("video/mp4") ? "mp4" : "webm";
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob(chunks, { type: mimeType }));
  link.download = `${name}.${ext}`;
  link.click();
  setStatus(`הסרטון נשמר: ${link.download}`);
  window.recordingSaved = link.download;
}
