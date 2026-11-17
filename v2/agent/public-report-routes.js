/** @param {{ request: { method: string, uri: string, headers?: Record<string, {value: string}> }, response?: { statusCode: number, headers: Record<string, {value: string}> } }} event */
function handler(event) {
  var request = event.request;
  if (event.response) {
    if (request.uri.startsWith("/assets/evals")) {
      event.response.headers["cache-control"] = { value: "no-store" };
    }
    return event.response;
  }
  if (request.uri === "/release-dashboard" || request.uri === "/release-dashboard/") {
    request.uri = "/assets/releases.html";
  }
  if (request.uri === "/cost-dashboard" || request.uri === "/cost-dashboard/") {
    request.uri = "/costs.html";
  }
  return request;
}
