import { AppShell } from "@/components/app/app-shell";
import { RequireAuth } from "@/components/app/require-auth";
import { ToastProvider } from "@/components/ui/toast";

/** Everything under this group requires a signed-in user and shares the app shell. */
export default function AppLayout({ children }: LayoutProps<"/">) {
  return (
    <RequireAuth>
      <ToastProvider>
        <AppShell>{children}</AppShell>
      </ToastProvider>
    </RequireAuth>
  );
}
