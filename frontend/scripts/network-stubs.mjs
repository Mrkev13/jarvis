// Browser checks wait for `waitUntil: "networkidle"`, which two requests can block forever:
// - MRK-19: the app keeps one SSE connection (GET /events/stream) open on every page. Checks that do not test
//   realtime get a finished response: a valid `ready` position and a long `retry`, so EventSource stays
//   CONNECTING (no client backoff reconnect) and does not reopen the stream during the check.
// - Fresh clone without game assets (public/game-assets/ is gitignored): the manifest request gets Next's large
//   404 page, whose unread body keeps the request open in Chromium. An empty 404 is the same "no manifest" case.
//   Page-level routes (ui-check withGameAssets) take precedence over this context route.
export const SSE_STUB_BODY = 'retry: 3600000\n\nid: 0\nevent: ready\ndata: {"latest_id":0}\n\n';

export async function stubLongRequests(ctx, { eventStream = true } = {}) {
  await ctx.route("**/game-assets/manifest.json", (route) => route.fulfill({ status: 404, body: "" }));
  if (!eventStream) return;
  await ctx.route("**/events/stream**", (route) =>
    route.fulfill({
      status: 200,
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-store",
        "Access-Control-Allow-Origin": route.request().headers().origin || "*",
        "Access-Control-Allow-Credentials": "true",
      },
      body: SSE_STUB_BODY,
    }),
  );
}
