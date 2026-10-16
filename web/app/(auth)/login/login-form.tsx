"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { AuthError, login } from "@/lib/auth-api";
import { Button } from "@/components/ui/button";
import { LogoMark } from "@/components/ui/logo-mark";
import { Panel } from "@/components/ui/panel";

/**
 * Sign-in form: username + password, one panel, no chrome. Wrong
 * credentials get one generic line (no hint which field failed); network
 * errors say the backend is unreachable. Success lands on /app.
 */
export function LoginForm() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const submit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (loading) return;
    setError(null);
    setLoading(true);
    try {
      await login(username.trim(), password);
      router.replace("/app");
    } catch (err) {
      setError(
        err instanceof AuthError
          ? err.message
          : "Sign-in failed unexpectedly. Try again.",
      );
      setLoading(false);
    }
  };

  const field = "input disabled:opacity-50 disabled:cursor-not-allowed";

  return (
    <Panel className="w-full max-w-[380px]">
      <form onSubmit={(e) => void submit(e)} className="flex flex-col gap-4 p-6">
        <div className="flex items-center gap-3">
          <LogoMark size={26} />
          <div className="flex flex-col">
            <span className="text-[15px] font-bold tracking-[2px] text-ink">LYNCEUS</span>
            <span className="text-[11px] font-semibold tracking-[1px] text-muted uppercase">
              Gate console sign-in
            </span>
          </div>
        </div>

        <div>
          <label htmlFor="login-username" className="smallcaps mb-1 block">
            Username
          </label>
          <input
            id="login-username"
            type="text"
            className={field}
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            autoFocus
            required
            disabled={loading}
          />
        </div>

        <div>
          <label htmlFor="login-password" className="smallcaps mb-1 block">
            Password
          </label>
          <input
            id="login-password"
            type="password"
            className={field}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
            disabled={loading}
          />
        </div>

        {error ? (
          <p role="alert" className="m-0 text-[13px] text-verdict-red">
            {error}
          </p>
        ) : null}

        <Button type="submit" variant="primary" disabled={loading} className="mt-1">
          {loading ? "Signing in…" : "Sign in"}
        </Button>
      </form>
    </Panel>
  );
}
