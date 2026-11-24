/**
 * Retired AudD proxy.
 * VALUTED MUSIC Radar now uses the self-hosted Chromaprint service in
 * music/radar-selfhosted/. Do not deploy this legacy Worker.
 */
export default {
  async fetch() {
    return Response.json(
      {
        error: "This recognition proxy has been retired.",
        mode: "self-hosted-no-external-recognition-api",
        next: "Deploy music/radar-selfhosted/ and point the Radar interface to your own HTTPS host."
      },
      { status: 410, headers: { "Cache-Control": "no-store" } }
    );
  }
};
