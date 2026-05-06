import Link from "next/link";
import type { Work } from "@/data/works";

type Props = {
  work: Work;
  size?: "default" | "large";
};

export function WorkCard({ work, size = "default" }: Props) {
  const aspect = size === "large" ? "aspect-[4/5]" : "aspect-[4/5]";
  return (
    <Link href={`/works#${work.slug}`} className="group block">
      <div
        className={`${aspect} relative w-full overflow-hidden rounded-sm`}
        style={{ background: work.cover }}
      >
        <div className="absolute inset-0 flex items-end p-6 opacity-0 transition-opacity duration-500 group-hover:opacity-100">
          <span className="rounded-full bg-paper/90 px-3 py-1 text-xs uppercase tracking-widest text-ink">
            View →
          </span>
        </div>
        <div className="absolute right-4 top-4 flex gap-1">
          {work.palette.map((c) => (
            <span
              key={c}
              className="h-3 w-3 rounded-full ring-1 ring-paper/60"
              style={{ background: c }}
            />
          ))}
        </div>
      </div>
      <div className="mt-4 flex items-start justify-between gap-4">
        <div>
          <p className="font-display text-xl leading-tight">{work.title}</p>
          <p className="mt-1 text-sm text-ink/60">
            {work.client} · {work.category}
          </p>
        </div>
        <span className="shrink-0 text-sm text-ink/50">{work.year}</span>
      </div>
    </Link>
  );
}
