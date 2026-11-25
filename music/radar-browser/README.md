# VALUTED MUSIC Radar — browser-only prototype

This is a static, client-side music fingerprint matcher. It makes no recognition API calls and requires no VPS, database server, or backend. Microphone capture, decoding, fingerprint generation, and matching happen in the visitor's browser.

## Important scope
- It does not identify every song in the world.
- It only recognizes tracks in the VALUTED Radar fingerprint library.
- The library builder fingerprints audio selected by the site owner. Only index audio the site has permission to process.
- The audio itself is not uploaded. Exported JSON contains fingerprints and metadata.
- This is an experimental constellation-fingerprint prototype, not a production-grade Shazam replacement. It needs device/browser testing and tuning against real-world noisy recordings.
- It does not recognize humming or singing.
- Microphone access requires HTTPS or localhost.

## Build the library
1. Open the Radar page in a secure browser.
2. Expand the Library builder section.
3. Enter metadata and choose an authorized audio file.
4. Select Add fingerprint to library.
5. Export the JSON library.
6. Publish that JSON as the shared library after review. Visitors can also import JSON locally.

The app stores the current library in browser local storage. Do not put copyrighted audio files in the repository.

## Static hosting
The repository includes a GitHub Actions Pages deployment workflow. After this change is merged to main, the workflow configures GitHub Pages and publishes this folder as a static HTTPS site at `https://elsherbinyk10-netizen.github.io/VALUTED_NEWS_AUTOMATION/` (the exact URL is also reported by the deployment job). The Radar can then be embedded in a Shopify page using an iframe; this does not require a theme edit or a server. Static hosting serves HTML, JavaScript and JSON only; it does not process or recognize audio server-side. The initial shared `library.json` is intentionally empty. Populate it with audio you are authorized to fingerprint, export the JSON, and update the shared catalogue through a reviewed repository change.

## Browser compatibility
Use a current Safari, Chrome, or Firefox. Microphone capture requires user permission and HTTPS. File upload is the fallback. iOS Safari MediaRecorder support varies by version; test on the target iPhone before release.

## Algorithm
The prototype downsamples decoded audio to 11.025 kHz, computes short-time Fourier transforms with a radix-2 FFT, selects local spectral peaks, and hashes peak pairs with their time delta. Matching votes for consistent time offsets against stored track fingerprints. The threshold is deliberately conservative and must be calibrated using labeled test recordings.

## Privacy
The app fetches only the static library.json file from the same site. It makes no external recognition API request. Audio samples remain in memory during processing. Browser local storage contains the fingerprint library and metadata only. A production release should add an explicit privacy notice and independent code review.
