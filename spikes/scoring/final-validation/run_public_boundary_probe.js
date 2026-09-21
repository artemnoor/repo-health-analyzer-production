#!/usr/bin/env node

/**
 * Read-only public-boundary probe for the final validation spike.
 *
 * It deliberately records only HTTP/status classes and permission booleans.
 * It never writes response bodies, cookies, source code, comments, or tokens.
 */

const fs = require("node:fs");
const { chromium } = require("playwright");

const REPOSITORIES = [
  "artem03102006/codex-external-audit-public-20260916",
  "artem03102006/codex-external-audit-private-20260916",
  "a-obraz60022006/mirea-trade",
  "k-5-45mm/dozzle-plus",
  "arceniytadevosyan/lmsweb",
  "astra-shellless-images/nginx",
  "astra-shellless-images/opensearch",
  "astra-shellless-images/tomcat",
  "fompronin/heh",
  "imbok/cosmos-ontology",
  "imbok/uims-portal",
  "sourcecraft/sourcecraft",
];

function browserExecutable() {
  const candidates = [
    process.env.REPO_HEALTH_BROWSER,
    "C:/Program Files/Google/Chrome/Application/chrome.exe",
    "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  ].filter(Boolean);
  return candidates.find((candidate) => fs.existsSync(candidate)) || null;
}

async function anonymousUiPermissions(page) {
  const rows = [];
  for (const repository of REPOSITORIES) {
    const row = {
      repository,
      permission_http_status: null,
      view_appsec: null,
      use_appsec: null,
      repo_loaded: false,
      raw_payload_retained: false,
    };
    const handler = async (response) => {
      const operation = response.url().split("/").pop();
      if (operation === "getRepo" && response.status() === 200) {
        row.repo_loaded = true;
      }
      if (operation !== "getOrganizationRepoPermissions") return;
      row.permission_http_status = response.status();
      if (response.status() !== 200) return;
      try {
        const payload = await response.json();
        row.view_appsec = typeof payload?.viewAppsec === "boolean" ? payload.viewAppsec : null;
        row.use_appsec = typeof payload?.useAppsec === "boolean" ? payload.useAppsec : null;
      } catch (_) {
        row.permission_parse_error = true;
      }
    };
    page.on("response", handler);
    try {
      await page.goto(`https://sourcecraft.dev/${repository}`, {
        waitUntil: "domcontentloaded",
        timeout: 30000,
      });
      await page.waitForTimeout(1200);
    } catch (error) {
      row.failure_kind = error?.name || "NavigationError";
    }
    page.off("response", handler);
    rows.push(row);
  }
  return rows;
}

async function anonymousCicd() {
  const rows = [];
  for (const repository of REPOSITORIES) {
    const row = {
      repository,
      http_status: null,
      record_count: null,
      pagination_complete: null,
      raw_payload_retained: false,
    };
    try {
      const response = await fetch(
        `https://api.sourcecraft.tech/repos/${repository}/cicd/runs?page_size=100`,
      );
      row.http_status = response.status;
      if (response.status === 200) {
        const payload = await response.json();
        const runs = Array.isArray(payload?.runs) ? payload.runs : null;
        row.record_count = runs ? runs.length : null;
        row.pagination_complete = !payload?.next_page_token;
      }
    } catch (error) {
      row.failure_kind = error?.name || "FetchError";
    }
    rows.push(row);
  }
  return rows;
}

async function main() {
  const executablePath = browserExecutable();
  if (!executablePath) {
    console.log(JSON.stringify({
      status: "UNAVAILABLE",
      reason: "browser_executable_missing",
      raw_payload_retained: false,
    }));
    return;
  }
  let browser;
  try {
    browser = await chromium.launch({ headless: true, executablePath });
    const page = await browser.newPage();
    const uiRows = await anonymousUiPermissions(page);
    const ciRows = await anonymousCicd();
    const countBy = (rows, key) => rows.reduce((counts, row) => {
      const value = row[key];
      if (value !== null && value !== undefined) counts[String(value)] = (counts[String(value)] || 0) + 1;
      return counts;
    }, {});
    console.log(JSON.stringify({
      status: "MEASURED",
      candidate_count: REPOSITORIES.length,
      anonymous_ui_appsec_permissions: {
        view_appsec_counts: countBy(uiRows, "view_appsec"),
        use_appsec_counts: countBy(uiRows, "use_appsec"),
        http_status_counts: countBy(uiRows, "permission_http_status"),
        repositories: uiRows,
        raw_payload_retained: false,
      },
      anonymous_cicd_probe: {
        http_status_counts: countBy(ciRows, "http_status"),
        repositories: ciRows,
        raw_payload_retained: false,
      },
      raw_payload_retained: false,
    }));
  } catch (error) {
    console.log(JSON.stringify({
      status: "ERROR",
      failure_kind: error?.name || "BrowserProbeError",
      raw_payload_retained: false,
    }));
  } finally {
    if (browser) await browser.close();
  }
}

main();
