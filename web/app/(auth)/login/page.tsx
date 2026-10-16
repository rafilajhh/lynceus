import type { Metadata } from "next";
import { LoginForm } from "./login-form";

export const metadata: Metadata = {
  title: "Sign in",
};

/** Operator sign-in. Landing stays public; the console gates itself. */
export default function LoginPage() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-ground px-6">
      <LoginForm />
    </main>
  );
}
