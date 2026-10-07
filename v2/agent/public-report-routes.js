// Retired entrance/exit reports with verified area-report replacements.
/** @type {Record<string, string>} */
var legacyReportRedirects = {
  "woodburn-gallows-road-merrifield-northbound/tysons-route-7-leesburg-pike-northbound": "northbound/woodburn-to-tysons/",
  "lorton-gordon-boulevard-route-123-northbound-i95-211no/idylwood-lee-highway-route-29-northbound": "northbound/lorton-to-idylwood/",
  "tysons-jones-branch-drive-route-123-southbound/stafford-courthouse-road-route-630-southbound": "southbound/tysons-to-stafford/",
  "tysons-westpark-drive-tysons-corner-southbound-i495-185so/stafford-courthouse-road-route-630-southbound": "southbound/tysons-to-stafford/",
  "tysons-route-7-leesburg-pike-southbound/woodburn-gallows-road-merrifield-southbound": "southbound/tysons-to-woodburn/",
  "washington-washington-d-c-district-of-columbia-southbound/fredericksburg-i-95-near-route-17-route-17-southbound-exit-southbound": "southbound/washington-to-fredericksburg/",
  "fredericksburg-i-95-near-route-17-route-17-northbound-entrance-northbound/tysons-jones-branch-drive-route-123-northbound": "northbound/fredericksburg-to-tysons/",
  "tysons-dulles-toll-road-dulles-access-road-southbound-i495-182so/lorton-route-1-richmond-highway-southbound-i95-210sd": "southbound/tysons-to-lorton/",
  "tysons-jones-branch-drive-route-123-southbound/arlington-washington-d-c-washington-northbound": "southbound/tysons-to-arlington/",
};

/** @param {string} location */
function permanentRedirect(location) {
  return {
    statusCode: 301,
    statusDescription: "Moved Permanently",
    headers: {
      location: { value: location },
      "cache-control": { value: "public, max-age=300" },
    },
  };
}

/** @param {{ request: { method: string, uri: string, headers?: Record<string, {value: string}> }, response?: { statusCode: number, headers: Record<string, {value: string}> } }} event */
function handler(event) {
  var request = event.request;
  if (event.response) {
    if (request.uri.startsWith("/assets/evals")) {
      event.response.headers["cache-control"] = { value: "no-store" };
    }
    return event.response;
  }
  if (request.uri === "/tolls" || request.uri === "/tolls/") {
    return permanentRedirect("/#toll-reports");
  }
  var legacy = request.uri.match(/^\/tolls\/i95-i495\/([^/]+)\/([^/]+)(?:\/(index\.html|report\.json))?\/?$/);
  var endpointSlug = /-(northbound|southbound)(?:-i(?:95|495)-[a-z0-9]+)?$/;
  if (legacy && endpointSlug.test(legacy[1]) && endpointSlug.test(legacy[2])) {
    var target = legacyReportRedirects[legacy[1] + "/" + legacy[2]];
    if (target) {
      return permanentRedirect("/tolls/i95-i495/" + target + (legacy[3] === "report.json" ? "report.json" : ""));
    }
    // The detailed-report namespace is retired; absent S3 keys otherwise look forbidden.
    return {
      statusCode: 410,
      statusDescription: "Gone",
      headers: {
        "cache-control": { value: "public, max-age=300" },
        "content-type": { value: "text/plain; charset=utf-8" },
        "x-content-type-options": { value: "nosniff" },
      },
      body: {
        encoding: "text",
        data: "This detailed entrance/exit report has been retired. Current area reports are at /tolls/i95-i495/.",
      },
    };
  }
  if (request.uri === "/release-dashboard" || request.uri === "/release-dashboard/") {
    request.uri = "/assets/releases.html";
  }
  if (request.uri === "/eval-dashboard" || request.uri === "/eval-dashboard/") {
    request.uri = "/evals.html";
  }
  if (request.uri === "/cost-dashboard" || request.uri === "/cost-dashboard/") {
    request.uri = "/costs.html";
  }
  if (request.uri.startsWith("/tolls/") && !request.uri.includes(".")) {
    request.uri += request.uri.endsWith("/") ? "index.html" : "/index.html";
  }
  return request;
}
