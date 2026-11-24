/**
 * VALUTED MUSIC song-recognition proxy for Cloudflare Workers.
 * Deploy with AUDD_API_TOKEN as a Worker secret. Never expose that token to storefront JS.
 */
const MAX_BYTES = 10 * 1024 * 1024;
const ALLOWED_ORIGIN = "https://valutedmusic.site";

export default {
  async fetch(request, env) {
    const origin = request.headers.get("Origin") || "";
    const cors = {
      "Access-Control-Allow-Origin": ALLOWED_ORIGIN,
      "Access-Control-Allow-Methods": "POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type",
      "Vary": "Origin"
    };
    if (request.method === "OPTIONS") {
      if (origin !== ALLOWED_ORIGIN) return new Response(null, { status: 403 });
      return new Response(null, { status: 204, headers: cors });
    }
    if (origin !== ALLOWED_ORIGIN) return Response.json({ error: "Origin not allowed" }, { status: 403 });
    if (request.method !== "POST") return Response.json({ error: "Method not allowed" }, { status: 405, headers: cors });
    if (!env.AUDD_API_TOKEN) return Response.json({ error: "Recognition service is not configured" }, { status: 503, headers: cors });

    try {
      const form = await request.formData();
      const file = form.get("file");
      if (!(file instanceof File)) return Response.json({ error: "Choose an audio recording or file." }, { status: 400, headers: cors });
      if (file.size < 8 * 1024 || file.size > MAX_BYTES) return Response.json({ error: "Audio must be between 8 KB and 10 MB." }, { status: 413, headers: cors });
      const allowed = new Set(["audio/mpeg", "audio/mp4", "audio/aac", "audio/wav", "audio/x-wav", "audio/ogg", "audio/webm", "audio/mp4; codecs=mp4a.40.2"]);
      if (!allowed.has((file.type || "").toLowerCase())) return Response.json({ error: "Unsupported audio format. Try MP3, M4A, WAV, OGG or WebM." }, { status: 415, headers: cors });

      const payload = new FormData();
      payload.append("api_token", env.AUDD_API_TOKEN);
      payload.append("return", "spotify,apple_music");
      payload.append("market", "eg");
      payload.append("file", file, file.name || "music-sample");
      const upstream = await fetch("https://api.audd.io/", { method: "POST", body: payload });
      if (!upstream.ok) return Response.json({ error: "Recognition provider is temporarily unavailable." }, { status: 502, headers: cors });
      const data = await upstream.json();
      if (data.status !== "success") return Response.json({ error: "The recording could not be identified. Try a clearer 8–20 second clip." }, { status: 422, headers: cors });
      const r = data.result;
      if (!r) return Response.json({ match: null }, { status: 200, headers: cors });
      return Response.json({
        match: {
          title: r.title || "",
          artist: r.artist || "",
          album: r.album || "",
          release_date: r.release_date || "",
          label: r.label || "",
          timecode: r.timecode || "",
          song_link: r.song_link || "",
          apple_music: r.apple_music || null,
          spotify: r.spotify || null
        }
      }, { status: 200, headers: cors });
    } catch (error) {
      return Response.json({ error: "Could not process this recording. Please try again." }, { status: 500, headers: cors });
    }
  }
};
