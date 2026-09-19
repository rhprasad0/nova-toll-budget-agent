import type { Writable } from "node:stream";
import type { RequestEvent } from "./handler.mjs";

/** AWS Lambda injects this streaming API into the deployed Node runtime. */
declare global {
  var awslambda: {
    streamifyResponse(handler: (event: RequestEvent, stream: Writable, context: { invokedFunctionArn: string }) => Promise<void>): unknown;
    HttpResponseStream: {
      from(stream: Writable, metadata: { statusCode: number; headers: Record<string, string> }): Writable;
    };
  };
}
