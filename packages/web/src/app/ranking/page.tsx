import type { Metadata } from "next";
import { RankingPage } from "@/components/health-ranking/ranking-page";

export const metadata: Metadata = {
  title: "Repository ranking",
  description: "A public, explainable ranking of repository health.",
};

export default function RankingRoute() {
  return <RankingPage />;
}
