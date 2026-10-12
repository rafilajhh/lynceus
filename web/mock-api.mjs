// Minimal mock of the (not-yet-implemented) /inspections contract.
// Serves the static export in ./out plus contract-shaped JSON.
import http from "node:http";
import { readFile } from "node:fs/promises";

const rec1 = JSON.parse(
  await readFile("../backend/runs/inspection-000001/audit.json", "utf8"),
);
const rec2 = JSON.parse(
  await readFile("../backend/runs/inspection-000002/audit.json", "utf8"),
);

const list = {
  inspections: [
    {
      record_id: "inspection-000001",
      truck_id: "demo-green",
      decision: "refuse_insufficient_input",
      decided_at_utc: "2026-10-12T18:27:34Z",
      prevented_loss_idr: 0,
      gate_states: { ocr_confidence: "not_evaluated", manifest_crosscheck: "not_run" },
    },
    {
      record_id: "inspection-000002",
      truck_id: "B-9112-GRK",
      decision: "reject",
      decided_at_utc: "2026-10-13T02:10:00Z",
      prevented_loss_idr: 798000000,
      gate_states: { vlm_confidence: "passed", weight_plausibility: "failed" },
    },
    {
      record_id: "inspection-000003",
      truck_id: "B-4471-SBY",
      decision: "escalate_human",
      decided_at_utc: "2026-10-13T04:45:00Z",
      prevented_loss_idr: 1250000,
      gate_states: { vlm_confidence: "passed", gas_plausibility: "failed" },
    },
    {
      record_id: "inspection-000004",
      truck_id: "B-2231-JKT",
      decision: "accept",
      decided_at_utc: "2026-10-13T06:05:00Z",
      prevented_loss_idr: 1950000,
      gate_states: { vlm_confidence: "passed", ocr_confidence: "passed" },
    },
  ],
};

const MIME = {
  ".html": "text/html",
  ".js": "text/javascript",
  ".css": "text/css",
  ".svg": "image/svg+xml",
  ".json": "application/json",
};

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://localhost");
  const path = url.pathname;
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Content-Type", "application/json");

  if (path === "/health") {
    res.end(JSON.stringify({ status: "ok", engine_available: true }));
    return;
  }
  if (path === "/inspections") {
    res.end(JSON.stringify(list));
    return;
  }
  const detailMatch = /^\/inspections\/(.+)$/.exec(path);
  if (detailMatch) {
    const id = decodeURIComponent(detailMatch[1]);
    const rec =
      id === "inspection-000001"
        ? rec1
        : id === "inspection-000002"
          ? rec2
          : { ...rec1, record_id: id };
    res.end(JSON.stringify(rec));
    return;
  }
  // Static export files.
  try {
    const file = path === "/" ? "/index.html" : path.endsWith("/") ? `${path}index.html` : path;
    const content = await readFile(`./out${file}`);
    res.setHeader("Content-Type", MIME[file.slice(file.lastIndexOf("."))] ?? "application/octet-stream");
    res.end(content);
  } catch {
    try {
      const content = await readFile(`./out${path}/index.html`);
      res.setHeader("Content-Type", "text/html");
      res.end(content);
    } catch {
      res.statusCode = 404;
      res.end(JSON.stringify({ error: "not found" }));
    }
  }
});
server.listen(4173, () => console.log("mock on :4173"));
