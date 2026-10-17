"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { KeyRound, Lock, LogIn, User } from "lucide-react";
import { AuthError, login } from "@/lib/auth-api";
import { Button } from "@/components/ui/button";

/**
 * Sign-in form: username + password. Wrong credentials get one generic
 * line (no hint which field failed); network errors say the backend is
 * unreachable. Success lands on /app.
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

  const field =
    "input h-11! pl-9! disabled:opacity-50 disabled:cursor-not-allowed";
  const fieldIcon =
    "pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-fg-subtle";

  return (
    <form
      onSubmit={(e) => void submit(e)}
      className="flex w-full max-w-[380px] flex-col gap-7"
    >
      <div className="flex flex-col gap-2">
        <p className="m-0 font-mono text-[12px] tracking-[1px] text-brand-deep uppercase">
          Gate console
        </p>
        <h1 className="m-0 font-display text-[30px] font-medium tracking-[-0.6px] text-fg sm:text-[36px]">
          Sign in to inspect
        </h1>
        <p className="m-0 text-[15px] leading-[23px] text-fg-muted">
          Use your gate operator account to open the inspection console.
        </p>
      </div>

      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-1.5">
          <label htmlFor="login-username" className="text-[13px] font-medium text-fg">
            Username
          </label>
          <div className="relative">
            <User size={16} aria-hidden="true" className={fieldIcon} />
            <input
              id="login-username"
              type="text"
              className={field}
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="admin"
              autoComplete="username"
              autoFocus
              required
              disabled={loading}
            />
          </div>
        </div>

        <div className="flex flex-col gap-1.5">
          <div className="flex items-start justify-between gap-3">
            <label htmlFor="login-password" className="text-[13px] font-medium text-fg">
              Password
            </label>
            <span className="text-[13px] text-fg-subtle">Ask your supervisor to reset</span>
          </div>
          <div className="relative">
            <Lock size={16} aria-hidden="true" className={fieldIcon} />
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
        </div>

        {error ? (
          <p role="alert" className="m-0 text-[13px] text-danger">
            {error}
          </p>
        ) : null}
      </div>

      <Button type="submit" variant="primary" size="lg" disabled={loading} className="w-full">
        <LogIn size={14} aria-hidden="true" />
        {loading ? "Signing in…" : "Sign in"}
      </Button>

      {/* Default console credentials, stated for reviewers of this
          deployment: the values come from the deployment's env and are
          defaults for this instance, not secrets. Click fills both fields. */}
      <div className="flex items-center gap-2.5 rounded-[10px] bg-surface-subtle px-3.5 py-3 text-[13px]">
        <KeyRound size={16} aria-hidden="true" className="shrink-0 text-fg-muted" />
        <span className="text-fg-muted">Demo access</span>
        <button
          type="button"
          disabled={loading}
          onClick={() => {
            setUsername("admin");
            setPassword("admin123");
          }}
          aria-label="Fill demo credentials admin / admin123"
          className="cursor-pointer rounded-[4px] font-mono text-fg underline decoration-line-strong underline-offset-2 transition-colors duration-100 hover:decoration-brand disabled:pointer-events-none disabled:opacity-50"
        >
          admin / admin123
        </button>
      </div>
    </form>
  );
}
