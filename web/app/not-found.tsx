import Link from "next/link";
import { buttonVariants } from "@/components/ui/button";
import { LogoMark } from "@/components/ui/logo-mark";

export default function NotFound() {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-5 px-4 py-24 text-center">
      <LogoMark size={28} />
      <div className="flex flex-col items-center gap-2">
        <span className="font-mono text-[12px] tracking-[1px] text-brand-deep">404</span>
        <h1 className="m-0 font-display text-[32px] font-medium tracking-[-0.6px] text-fg">
          No such route.
        </h1>
        <p className="m-0 text-[15px] text-fg-muted">
          The page you asked for is not part of this console.
        </p>
      </div>
      <Link href="/" className={buttonVariants({ variant: "default" })}>
        Return to landing
      </Link>
    </div>
  );
}
