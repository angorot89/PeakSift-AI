import { redirect } from "next/navigation";

/** The dashboard is now Home; old links and bookmarks keep working. */
export default function DashboardPage() {
  redirect("/home");
}
