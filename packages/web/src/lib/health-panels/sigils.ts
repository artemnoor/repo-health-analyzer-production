/**
 * Directly reused GrimoireLab/Sigils visualization recipes.
 *
 * These are the upstream Kibana saved-object blocks copied into
 * `src/data/health/sigils`. The health page does not pretend that a legacy
 * Kibana JSON is a native React chart; this registry makes the reusable
 * recipes discoverable and keeps their original aggregation definitions
 * available for an adapter/exporter later.
 */
import git from "@/data/health/sigils/git.json";
import gitAreasOfCode from "@/data/health/sigils/git_areas_of_code.json";
import gitDemographics from "@/data/health/sigils/git_demographics.json";
import gitPairProgramming from "@/data/health/sigils/git_pair_programming.json";
import contributorsGrowth from "@/data/health/sigils/contributors_growth.json";
import githubIssues from "@/data/health/sigils/github_issues.json";
import githubIssuesBacklog from "@/data/health/sigils/github_issues_backlog.json";
import githubIssuesTiming from "@/data/health/sigils/github_issues_timing.json";
import githubPullRequests from "@/data/health/sigils/github_pull_requests.json";
import githubPullRequestsBacklog from "@/data/health/sigils/github_pull_requests_backlog.json";
import githubPullRequestsTiming from "@/data/health/sigils/github_pull_requests_timing.json";
import githubEventsClosed from "@/data/health/sigils/github_events_closed.json";

export interface SigilsHealthPanelRecipe {
  id: string;
  title: string;
  source: "chaoss.sigils";
  measures: string[];
  config: unknown;
}

export const SIGILS_HEALTH_PANELS: readonly SigilsHealthPanelRecipe[] = [
  {
    id: "git",
    title: "Git activity, authors and organizations",
    source: "chaoss.sigils",
    measures: ["commits", "authors", "organizations", "repositories"],
    config: git,
  },
  {
    id: "git_areas_of_code",
    title: "Areas of code and most modified files",
    source: "chaoss.sigils",
    measures: ["file areas", "modified files", "authors", "organizations"],
    config: gitAreasOfCode,
  },
  {
    id: "git_demographics",
    title: "Contributor demographics",
    source: "chaoss.sigils",
    measures: ["author domains", "organizations", "contributors"],
    config: gitDemographics,
  },
  {
    id: "git_pair_programming",
    title: "Pair programming and co-authorship",
    source: "chaoss.sigils",
    measures: ["co-authors", "pairing", "organizations"],
    config: gitPairProgramming,
  },
  {
    id: "contributors_growth",
    title: "Contributor growth",
    source: "chaoss.sigils",
    measures: ["new contributors", "returning contributors", "growth"],
    config: contributorsGrowth,
  },
  {
    id: "github_issues",
    title: "GitHub issue activity",
    source: "chaoss.sigils",
    measures: ["opened", "closed", "labels", "submitters"],
    config: githubIssues,
  },
  {
    id: "github_issues_backlog",
    title: "GitHub issue backlog",
    source: "chaoss.sigils",
    measures: ["open backlog", "age", "triage"],
    config: githubIssuesBacklog,
  },
  {
    id: "github_issues_timing",
    title: "GitHub issue timing",
    source: "chaoss.sigils",
    measures: ["time to close", "resolution", "lead time"],
    config: githubIssuesTiming,
  },
  {
    id: "github_pull_requests",
    title: "GitHub pull-request activity",
    source: "chaoss.sigils",
    measures: ["opened", "merged", "closed", "authors"],
    config: githubPullRequests,
  },
  {
    id: "github_pull_requests_backlog",
    title: "GitHub pull-request backlog",
    source: "chaoss.sigils",
    measures: ["open PRs", "age", "review load"],
    config: githubPullRequestsBacklog,
  },
  {
    id: "github_pull_requests_timing",
    title: "GitHub pull-request timing",
    source: "chaoss.sigils",
    measures: ["time to merge", "review time", "resolution"],
    config: githubPullRequestsTiming,
  },
  {
    id: "github_events_closed",
    title: "Closed GitHub events",
    source: "chaoss.sigils",
    measures: ["issues", "pull requests", "events"],
    config: githubEventsClosed,
  },
];
