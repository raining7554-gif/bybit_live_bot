import type { Metadata } from "next";
import { works } from "@/data/works";
import { WorkCard } from "@/components/WorkCard";

export const metadata: Metadata = {
  title: "Works",
  description: "디자인에빠지다의 브랜딩, 에디토리얼, 패키지 작업 모음."
};

export default function WorksPage() {
  const categories = Array.from(new Set(works.map((w) => w.category)));

  return (
    <section className="container-page py-20 md:py-28">
      <p className="eyebrow">Works · {works.length} projects</p>
      <h1 className="mt-4 font-display text-5xl md:text-7xl">
        브랜드의 결을 담은
        <br />
        그래픽 작업들.
      </h1>
      <div className="mt-10 flex flex-wrap gap-2">
        {categories.map((c) => (
          <span
            key={c}
            className="rounded-full border border-ink/20 px-3 py-1 text-xs uppercase tracking-widest text-ink/70"
          >
            {c}
          </span>
        ))}
      </div>

      <div className="mt-16 grid gap-x-8 gap-y-16 md:grid-cols-2 lg:grid-cols-3">
        {works.map((w) => (
          <article key={w.slug} id={w.slug} className="scroll-mt-24">
            <WorkCard work={w} />
            <p className="mt-3 max-w-md text-sm leading-relaxed text-ink/70">
              {w.summary}
            </p>
          </article>
        ))}
      </div>
    </section>
  );
}
