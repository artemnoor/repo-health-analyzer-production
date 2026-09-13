import { expect, test } from "@playwright/test";

const alpha = {
  repository_id: "repo-alpha",
  name: "alpha",
  url: "https://example.test/alpha",
  snapshot_id: "snapshot-alpha",
  score_config_digest: "score-v1",
  overall_score: 91,
  band: "excellent",
  grade: "A",
  status: "pass",
  dimensions: { code: 95, security: 88 },
  languages: ["typescript"],
  confidence: 0.9,
  coverage: 0.9,
  evidence_coverage: 0.86,
  analyzed_at: "2026-09-10T12:00:00Z",
  stale: false,
  eligible: true,
  eligibility_reason: null,
  score_delta: 2.4,
};

const beta = {
  ...alpha,
  repository_id: "repo-beta",
  name: "beta",
  snapshot_id: "snapshot-beta",
  overall_score: 74,
  band: "fair",
  grade: "C",
  languages: ["python"],
  dimensions: { code: 70, security: 78 },
  score_delta: -1.1,
};

const stale = {
  ...beta,
  repository_id: "repo-stale",
  name: "stale",
  snapshot_id: "snapshot-stale",
  stale: true,
  eligible: false,
  eligibility_reason: "stale_snapshot",
};

const unranked = {
  ...beta,
  repository_id: "repo-unranked",
  name: "unranked",
  snapshot_id: "snapshot-unranked",
  overall_score: null,
  band: "unknown",
  grade: "?",
  status: "inconclusive",
  stale: false,
  eligible: false,
  eligibility_reason: "score_unavailable",
};

test.beforeEach(async ({ page }) => {
  await page.route("**/api/health/ranking/trend*", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        items: [
          {
            repository_id: alpha.repository_id,
            name: alpha.name,
            points: [
              { ...alpha, snapshot_id: "snapshot-old", analyzed_at: "2026-09-01T12:00:00Z", overall_score: 88 },
              { ...alpha, snapshot_id: alpha.snapshot_id },
            ],
          },
        ],
        limit: 12,
        generated_at: "2026-09-11T12:00:00Z",
      }),
    });
  });
  await page.route("**/api/health/ranking/compare*", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        items: [alpha, beta],
        dimensions: { code: { [alpha.repository_id]: 95, [beta.repository_id]: 70 } },
        score_config_digests: ["score-v1"],
        truncated: false,
        generated_at: "2026-09-11T12:00:00Z",
      }),
    });
  });
  await page.route("**/api/health/ranking?*", async (route) => {
    const requestUrl = new URL(route.request().url());
    const includeIneligible = requestUrl.searchParams.get("include_ineligible") === "true";
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        items: includeIneligible ? [stale, unranked] : [alpha, beta],
        page: 1,
        limit: 50,
        total: 2,
        facets: {
          dimensions: ["code", "security"],
          languages: ["python", "typescript"],
          statuses: ["pass"],
        },
        generated_at: "2026-09-11T12:00:00Z",
      }),
    });
  });
});

test("public ranking loads, preserves filters, and compares selected repositories", async ({ page }) => {
  await page.goto("/ranking");
  await expect(page.getByRole("heading", { name: "Repository ranking" })).toBeVisible();
  await expect(page.getByRole("link", { name: "alpha" })).toHaveAttribute(
    "href",
    "/repos/repo-alpha/code-health",
  );
  await expect(page.getByText("91.0")).toBeVisible();
  await expect(page.getByText("/100").first()).toBeVisible();
  await expect(page.getByLabel("Language").locator("option", { hasText: "python" })).toBeAttached();

  await page.getByLabel("Band").selectOption("good");
  await expect(page).toHaveURL(/band=good/);

  await page.getByRole("checkbox", { name: "Compare alpha" }).check();
  await page.getByRole("checkbox", { name: "Compare beta" }).check();
  await page.getByRole("button", { name: "Compare (2)" }).click();
  await expect(page.getByRole("complementary", { name: "Repository comparison" })).toBeVisible();
  await expect(page.getByText("Same score policy · up to four public rows")).toBeVisible();
});

test("public ranking keeps stale and not-ranked rows explicit", async ({ page }) => {
  await page.goto("/ranking?include_ineligible=true&stale=true");

  await expect(page.getByRole("link", { name: "stale" })).toBeVisible();
  await expect(page.getByText("stale", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("stale_snapshot")).toBeVisible();
  await expect(page.getByRole("link", { name: "unranked" })).toBeVisible();
  await expect(page.getByLabel("Repository score unknown")).toBeVisible();
  await expect(page.getByText("score_unavailable")).toBeVisible();
});
