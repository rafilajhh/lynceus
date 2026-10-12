import Link from "next/link";

export default function NotFound() {
  return (
    <div className="flex flex-col items-center gap-3 px-4 py-10 text-center">
      <div className="figure text-[30px] leading-none text-faint">404</div>
      <p className="text-[13px] text-muted">
        No such route. <Link href="/">Return to landing</Link>.
      </p>
    </div>
  );
}
