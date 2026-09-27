#!/bin/sh
# Record a saved debate as a video (picture + sound) using Chrome's own tab recorder.
#
#   sh backend/scripts/record_video.sh 20260927-143000 [name]   ->  videos/<name or id>.mp4
#
# Needs the studio running on :8010. Play the debate live once first (or replay it) so all the
# speech is cached, otherwise the video would include pauses while voices are generated.
# Opens a separate Chrome window with a throwaway profile; it closes by itself when done.
set -e
ID=$1
NAME=${2:-debate-$ID}
[ -n "$ID" ] || { echo "usage: $0 <debate id from backend/data/debates>"; exit 1; }
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
OUT="$ROOT/videos"
PROFILE=$(mktemp -d)
mkdir -p "$PROFILE/Default" "$OUT"
# Save downloads straight to videos/ without asking.
cat > "$PROFILE/Default/Preferences" <<EOF
{"download": {"default_directory": "$OUT", "prompt_for_download": false}}
EOF

"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --user-data-dir="$PROFILE" --no-first-run --no-default-browser-check \
  --auto-accept-this-tab-capture --autoplay-policy=no-user-gesture-required \
  --force-device-scale-factor=1 --window-size=1280,720 --app="http://localhost:8010/?replay=$ID&record=1&clean=1" &
CHROME=$!

# Wait for the finished file (Chrome writes *.crdownload while saving).
while ! ls "$OUT"/debate-"$ID".* 2>/dev/null | grep -qv crdownload; do sleep 2; done
sleep 2
kill $CHROME 2>/dev/null || true
sleep 2; rm -rf "$PROFILE" 2>/dev/null || true  # Chrome may still be flushing it

# Chrome writes a fragmented MP4 without a total duration (players think it's a few seconds long).
# Rewrite the container with macOS's built-in avconvert, without re-encoding.
RAW=$(ls "$OUT"/debate-"$ID".*)
avconvert --source "$RAW" --preset PresetPassthrough --output "$OUT/$NAME.mp4.tmp.mp4" --replace >/dev/null
rm "$RAW"
mv "$OUT/$NAME.mp4.tmp.mp4" "$OUT/$NAME.mp4"
ls -lh "$OUT/$NAME.mp4"
