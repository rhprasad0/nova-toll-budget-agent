function handler(event) {
  var request = event.request;
  if (request.uri.startsWith("/tolls/") && request.uri.endsWith("/")) {
    request.uri += "index.html";
  }
  return request;
}
