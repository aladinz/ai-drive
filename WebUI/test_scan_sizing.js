const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function createApp() {
  const elements = {
    "scan-account": { value: "14000" },
    "scan-risk": { value: "1" }
  };
  const storage = {};
  const context = vm.createContext({
    document: { getElementById: id => elements[id] || null },
    localStorage: {
      getItem: key => storage[key] || null,
      setItem: (key, value) => { storage[key] = value; }
    },
    navigator: { clipboard: { writeText: async text => { context.copied = text; } } },
    console, URLSearchParams, setTimeout, clearTimeout
  });
  const source = fs.readFileSync(path.join(__dirname, "app.js"), "utf8");
  vm.runInContext(source.slice(0, source.indexOf("const scanFilters =")), context);
  vm.runInContext(`
    function escapeHtml(value) { return String(value); }
    const setup = {
      entry: 31.33, stop: 29.76, stop_pct: 5, target1: 34.17, target2: 35.59,
      target3: 37.72, rr_t1: 1.8, rr_t2: 2.7, rr_t3: 4.1,
      setup_type: "Breakout", warnings: []
    };
    const plan = {
      entry: setup.entry, stop: setup.stop, atr: 1.42, total_shares: 170,
      tp1: { price: 34.17, mult: 2, pct: 50, shares: 85, profit: 241.4 },
      tp2: { price: 35.59, mult: 3, pct: 30, shares: 51, profit: 217.26 },
      tp3: { price: 37.72, mult: 4.5, pct: 20, shares: 34, profit: 217.26 },
      total_profit: 675.92, blended_rr: 2.53
    };
    const row = { ticker: "CHYM", score: "8/8", trade_setup: setup, scaling_plan: plan, checks: [] };
    scanResults = [row];
  `, context);
  return { context, elements, storage };
}

test("scan sizes every scaling tranche, profit, copy and journal from the risk inputs", async () => {
  const { context, elements, storage } = createApp();
  const run = code => vm.runInContext(code, context);
  let html = run("tradeCardHtml(row)");
  assert.match(html, /CHYM LONG · 89 shares/);
  assert.match(html, /Exit volume: <b>44 shares/);
  assert.match(html, /Exit volume: <b>26 shares/);
  assert.match(html, /Exit volume: <b>19 shares/);
  assert.match(html, /Profit at TP1: \+\$124\.96/);
  assert.match(html, /Total projected profit: \+\$357\.13/);
  assert.match(html, /risk => <b>89<\/b>/);
  await run('copyScalingPlan("CHYM", { textContent: "" })');
  assert.match(context.copied, /TP1: 44 shares/);
  assert.match(context.copied, /TP3: 19 shares/);
  run('setTaken("CHYM", true)');
  assert.equal(JSON.parse(storage["trades.json"])[0].shares, 89);

  elements["scan-account"].value = "10000";
  elements["scan-risk"].value = "2";
  html = run("tradeCardHtml(row)");
  assert.match(html, /CHYM LONG · 127 shares/);
  assert.match(html, /risk => <b>127<\/b>/);
  await run('copyScalingPlan("CHYM", { textContent: "" })');
  assert.match(context.copied, /TP1: 63 shares/);
});

test("target changes retain live position sizing and note updates preserve scan levels", async () => {
  const { context, elements } = createApp();
  const run = code => vm.runInContext(code, context);
  run(`
    const stopMult = { value: "1.5" };
    row.chart = { entry: 31.33, atr: 1.42 };
    row.levels = {};
    renderScanTable = () => {};
  `);
  context.fetch = async url => {
    if (url.startsWith("/api/scaling")) {
      assert.equal(new URLSearchParams(url.split("?")[1]).get("tp1"), "1.5");
      const plan = JSON.parse(run("JSON.stringify(row.scaling_plan)"));
      plan.tp1.mult = 1.5;
      plan.tp1.price = 33.46;
      return { ok: true, json: async () => plan };
    }
    return {
      ok: true,
      json: async () => ({
        trade_setup: { entry: 40, stop: 38, setup_type: "Pullback", confidence: 90, rationale: "Notes" }
      })
    };
  };
  await run('updateScaling("CHYM", 1.5)');
  elements["scan-account"].value = "10000";
  assert.match(run("tradeCardHtml(row)"), /CHYM LONG · 63 shares/);
  assert.match(run("tradeCardHtml(row)"), /Profit at TP1: \+\$66\.03/);
  await run('loadSetupNotes("CHYM")');
  assert.equal(run("row.trade_setup.entry"), 31.33);
  assert.equal(run("row.trade_setup.stop"), 29.76);
  assert.equal(run("row.trade_setup.rationale"), "Notes");
  assert.match(run("tradeCardHtml(row)"), /CHYM LONG · 63 shares/);
});

test("zero and invalid sizing never display the fixed default position", () => {
  const { context, elements } = createApp();
  const render = () => vm.runInContext("tradeCardHtml(row)", context);
  elements["scan-account"].value = "0";
  assert.match(render(), /CHYM LONG · 0 shares/);
  assert.match(render(), /Total projected profit: \+\$0\.00/);
  elements["scan-risk"].value = "";
  const html = render();
  assert.doesNotMatch(html, /CHYM LONG/);
  assert.match(html, /Enter a non-negative account size/);
  assert.match(html, /data-taken="CHYM"[^>]*disabled/);
});
