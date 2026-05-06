import Link from "next/link";
import { site } from "@/data/site";

export function Header() {
  return (
    <header className="sticky top-0 z-50 border-b border-ink/10 bg-paper/80 backdrop-blur">
      <div className="container-page flex h-16 items-center justify-between">
        <Link href="/" className="flex items-baseline gap-2">
          <span className="font-display text-xl tracking-tight">
            {site.name}
          </span>
          <span className="hidden text-[11px] uppercase tracking-[0.25em] text-ink/50 sm:inline">
            {site.nameEn}
          </span>
        </Link>
        <nav className="flex items-center gap-6 text-sm">
          {site.nav.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className="link-underline text-ink/80 hover:text-ink"
            >
              {item.label}
            </Link>
          ))}
        </nav>
      </div>
    </header>
  );
}
