function handler(event) {
  var request = event.request;
  if (request.uri.startsWith("/tolls/") && !request.uri.includes(".")) {
    request.uri += request.uri.endsWith("/") ? "index.html" : "/index.html";
  }
  return request;
}
