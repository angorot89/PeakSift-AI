import type { Metadata } from "next";
import { MoroccoHomeView } from "@/components/app/morocco/morocco-views";

export const metadata: Metadata = { title: "Morocco Mode" };

export default function Page() {
  return <MoroccoHomeView />;
}
