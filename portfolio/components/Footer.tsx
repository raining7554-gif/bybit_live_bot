import Link from "next/link";
import { site } from "@/data/site";

export function Footer() {
  const year = new Date().getFullYear();
  return (
    <footer className="mt-32 border-t border-ink/10">
      <div className="container-page grid gap-10 py-14 md:grid-cols-3">
        <div>
          <p className="font-display text-2xl">{site.name}</p>
          <p className="mt-2 max-w-xs text-sm text-ink/70">{site.tagline}</p>
        </div>
        <div className="text-sm text-ink/70">
          <p className="eyebrow mb-3">Contact</p>
          <a className="link-underline block" href={`mailto:${site.email}`}>
            {site.email}
          </a>
          <p className="mt-1">{site.location}</p>
        </div>
        <div className="text-sm text-ink/70">
          <p className="eyebrow mb-3">Follow</p>
          <a
            className="link-underline block"
            href={site.instagram}
            target="_blank"
            rel="noreferrer"
          >
            Instagram
          </a>
          <Link href="/contact" className="link-underline mt-1 block">
            프로젝트 의뢰
          </Link>
        </div>
      </div>
      <div className="container-page flex flex-col items-start justify-between gap-2 border-t border-ink/10 py-6 text-xs text-ink/50 sm:flex-row sm:items-center">
        <span>© {year} {site.name}. All rights reserved.</span>
        <span>Designed in Seoul · Built with Next.js</span>
      </div>
    </footer>
  );
}
