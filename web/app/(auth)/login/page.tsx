import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import { LogoMark } from "@/components/ui/logo-mark";
import { EnginePill } from "./engine-pill";
import { LoginForm } from "./login-form";

export const metadata: Metadata = {
  title: "Sign in",
};

/** Product facts, not live counts: the page renders before sign-in. */
const MINI_STATS = [
  { value: "6", label: "checks per truck" },
  { value: "SHA-256", label: "sealed record" },
  { value: "~20 s", label: "median verdict" },
] as const;

/**
 * Operator sign-in (pen.dev redesign, frame nODQb): form on the left,
 * dark brand panel on the right (lg+). Landing stays public; the console
 * gates itself.
 */
export default function LoginPage() {
  return (
    <main className="flex min-h-screen flex-1 bg-background">
      <div className="flex flex-1 flex-col justify-between gap-12 px-6 py-8 sm:px-10 sm:py-10 xl:px-16">
        <Link href="/" className="flex w-fit items-center gap-2.5" aria-label="Lynceus home">
          <LogoMark size={28} />
          <span className="font-display text-[19px] font-medium text-fg">Lynceus</span>
        </Link>
        <div className="flex w-full justify-center">
          <LoginForm />
        </div>
        <p className="m-0 text-[12px] text-fg-subtle">
          © Lynceus · AMD Developer Hackathon ACT III
        </p>
      </div>

      <aside
        aria-label="Lynceus at the gate"
        className="hidden shrink-0 p-4 lg:flex lg:w-[520px] xl:w-[640px]"
      >
        <div
          className="flex flex-1 flex-col justify-between gap-10 overflow-hidden rounded-[24px] bg-fg p-12"
          style={{
            backgroundImage:
              "radial-gradient(ellipse 80% 60% at 90% 0%, #2563EB55 0%, #2563EB00 100%)",
          }}
        >
          <EnginePill />

          <div className="relative h-[260px] w-full shrink-0 overflow-hidden rounded-[20px] border border-white/[0.14]">
            <Image
              src="/demo/t-metal-1.jpg"
              alt="Truck load with a rusted steel pipe and foil at the weighbridge"
              fill
              sizes="(min-width: 1280px) 576px, 456px"
              className="object-cover"
            />
            <div className="absolute bottom-4 left-4 flex max-w-[calc(100%-32px)] items-center gap-3 rounded-[10px] bg-surface px-3.5 py-2.5 shadow-[0px_8px_24px_#18191B33]">
              <span className="inline-flex items-center gap-1.5 rounded-full bg-danger-tint px-2.5 py-[3px] font-mono text-[12px] font-medium tracking-[0.6px] text-danger">
                <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-danger" />
                REJECT
              </span>
              <span className="truncate text-[13px] font-medium text-fg">
                Metal contaminant · 0.94
              </span>
              <span className="font-mono text-[12px] whitespace-nowrap text-fg-subtle">18.4 s</span>
            </div>
          </div>

          <div className="flex flex-col gap-8">
            <p className="m-0 font-display text-[28px] leading-[34px] font-medium tracking-[-0.4px] text-white xl:text-[32px] xl:leading-[38px]">
              One photo, one verdict, one sealed record — before the load ever touches the line.
            </p>
            <dl className="m-0 flex border-t border-white/[0.14] pt-6">
              {MINI_STATS.map((s) => (
                <div key={s.label} className="flex flex-1 flex-col-reverse gap-1">
                  <dt className="text-[13px] text-white/[0.68]">{s.label}</dt>
                  <dd className="m-0 font-mono text-[28px] font-light whitespace-nowrap text-white">
                    {s.value}
                  </dd>
                </div>
              ))}
            </dl>
          </div>
        </div>
      </aside>
    </main>
  );
}
