function handler(event) {
  var request = event.request;
  var allowed =
    (request.method === "GET" && request.uri === "/api/config") ||
    (request.method === "POST" &&
      (request.uri === "/api/chat" || request.uri === "/api/reset"));
  if (allowed) return request;
  return {
    statusCode: 404,
    statusDescription: "Not Found",
    headers: {
      "cache-control": { value: "no-store" },
      "content-type": { value: "application/json" },
      "x-content-type-options": { value: "nosniff" },
    },
    body: { encoding: "text", data: '{"error":{"code":"not_found"}}' },
  };
}
