import http from "node:http";
import assert from "node:assert";

let server;
let serverPort;

function startMockServer(handler) {
  return new Promise((resolve) => {
    server = http.createServer(handler);
    server.listen(0, "127.0.0.1", () => {
      serverPort = server.address().port;
      process.env.NEXT_PUBLIC_API_BASE_URL = `http://127.0.0.1:${serverPort}`;
      resolve();
    });
  });
}

function stopMockServer() {
  return new Promise((resolve) => {
    if (server) {
      server.close(() => resolve());
    } else {
      resolve();
    }
  });
}

async function runTests() {
  const { checkBackendHealth } = await import("./src/lib/api.ts");
  console.log("Starting API timeout and error handling tests...");

  // Test 1: Hanging body after headers are sent
  console.log("Test 1: Hanging body after headers (should abort within timeout)...");
  await startMockServer((req, res) => {
    if (req.url === "/health") {
      res.writeHead(200, {
        "Content-Type": "application/json",
        "Transfer-Encoding": "chunked",
      });
      res.write('{"status":'); // Write partial chunk then stall completely
      // Never send remaining chunk or end response
    }
  });

  const startT1 = Date.now();
  const res1 = await checkBackendHealth(150); // 150ms timeout
  const durationT1 = Date.now() - startT1;

  await stopMockServer();

  assert.strictEqual(res1.ok, false, "Hanging body must return ok=false");
  assert(
    res1.error.includes("timed out") || res1.error.includes("aborted"),
    `Error message must indicate timeout: ${res1.error}`
  );
  assert(
    durationT1 < 500,
    `Duration (${durationT1}ms) must be near timeout (~150ms), not hanging indefinitely`
  );
  console.log(`✓ Test 1 passed: aborted after ${durationT1}ms with error: "${res1.error}"`);

  // Test 2: Healthy fast response
  console.log("Test 2: Healthy response (200 OK with healthy payload)...");
  await startMockServer((req, res) => {
    if (req.url === "/health") {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ status: "healthy" }));
    }
  });

  const res2 = await checkBackendHealth(500);
  await stopMockServer();

  assert.strictEqual(res2.ok, true, "Healthy response must return ok=true");
  assert.strictEqual(res2.data.status, "healthy");
  console.log(`✓ Test 2 passed: healthy status confirmed in ${res2.responseTimeMs}ms`);

  // Test 3: HTTP 500 server error
  console.log("Test 3: HTTP 500 server error...");
  await startMockServer((req, res) => {
    res.writeHead(500, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ detail: "Internal server error" }));
  });

  const res3 = await checkBackendHealth(500);
  await stopMockServer();

  assert.strictEqual(res3.ok, false, "500 error must return ok=false");
  assert(res3.error.includes("500"), `Error must contain 500: ${res3.error}`);
  console.log(`✓ Test 3 passed: 500 error handled cleanly: "${res3.error}"`);

  // Test 4: Invalid JSON body
  console.log("Test 4: Invalid non-JSON payload...");
  await startMockServer((req, res) => {
    res.writeHead(200, { "Content-Type": "text/html" });
    res.end("<html><body>Bad Gateway</body></html>");
  });

  const res4 = await checkBackendHealth(500);
  await stopMockServer();

  assert.strictEqual(res4.ok, false, "Invalid JSON must return ok=false");
  assert(res4.error.includes("JSON"), `Error must mention JSON: ${res4.error}`);
  console.log(`✓ Test 4 passed: malformed JSON handled cleanly: "${res4.error}"`);

  // Test 5: Backend unavailable (connection refused)
  console.log("Test 5: Backend connection refused...");
  process.env.NEXT_PUBLIC_API_BASE_URL = "http://127.0.0.1:59999"; // inactive port
  const res5 = await checkBackendHealth(500);
  assert.strictEqual(res5.ok, false);
  assert(
    res5.error.includes("Unable to connect") || res5.error.includes("Connection error"),
    `Error must indicate connection issue: ${res5.error}`
  );
  console.log(`✓ Test 5 passed: connection refusal caught cleanly: "${res5.error}"`);

  console.log("\nAll 5 API timeout and error handling tests passed successfully!");
}

runTests().catch((err) => {
  console.error("Test failed:", err);
  process.exit(1);
});
