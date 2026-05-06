import Link from "next/link";
import { WorkCard } from "@/components/WorkCard";
import { works } from "@/data/works";
import { site } from "@/data/site";

export default function HomePage() {
  const featured = works.slice(0, 4);

  return (
    <>
      <section className="container-page pt-20 pb-24 md:pt-32 md:pb-32">
        <p className="eyebrow">Graphic & Branding Studio</p>
        <h1 className="mt-6 font-display text-5xl leading-[1.05] tracking-tight md:text-7xl lg:text-[88px]">
          한 장의 그래픽이
          <br />
          브랜드의 첫인상이 됩니다.
        </h1>
        <div className="mt-10 grid gap-10 md:grid-cols-12">
          <p className="text-lg leading-relaxed text-ink/75 md:col-span-7 md:col-start-1">
            {site.description}
          </p>
          <div className="flex items-end justify-start gap-4 md:col-span-5 md:justify-end">
            <Link
              href="/works"
              className="rounded-full bg-ink px-6 py-3 text-sm text-paper transition-colors hover:bg-ink/85"
            >
              작업물 보기 →
            </Link>
            <Link
              href="/contact"
              className="rounded-full border border-ink/20 px-6 py-3 text-sm text-ink transition-colors hover:border-ink"
            >
              프로젝트 의뢰
            </Link>
          </div>
        </div>
      </section>

      <section className="border-y border-ink/10 bg-ink text-paper">
        <div className="container-page grid gap-8 py-14 md:grid-cols-3">
          {[
            { k: "Branding", v: "브랜드 아이덴티티 시스템 구축" },
            { k: "Editorial", v: "도서 · 매거진 · 카탈로그 디자인" },
            { k: "Packaging", v: "리테일 · F&B 패키지 디자인" }
          ].map((item) => (
            <div key={item.k} className="border-l border-paper/20 pl-5">
              <p className="eyebrow text-paper/60">{item.k}</p>
              <p className="mt-2 font-display text-2xl">{item.v}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="container-page py-24 md:py-32">
        <div className="flex items-end justify-between">
          <div>
            <p className="eyebrow">Selected Works</p>
            <h2 className="mt-3 font-display text-4xl md:text-5xl">
              최근 작업
            </h2>
          </div>
          <Link href="/works" className="link-underline text-sm text-ink/70">
            전체 보기 →
          </Link>
        </div>
        <div className="mt-12 grid gap-x-8 gap-y-16 md:grid-cols-2">
          {featured.map((w) => (
            <WorkCard key={w.slug} work={w} size="large" />
          ))}
        </div>
      </section>

      <section className="container-page pb-32">
        <div className="rounded-sm border border-ink/15 bg-paper p-10 md:p-16">
          <div className="grid gap-10 md:grid-cols-12">
            <div className="md:col-span-7">
              <p className="eyebrow">Let&apos;s collaborate</p>
              <h3 className="mt-4 font-display text-3xl leading-tight md:text-5xl">
                브랜드의 다음 챕터,
                <br /> 함께 디자인할 준비가 되어 있나요?
              </h3>
            </div>
            <div className="flex items-end md:col-span-5 md:justify-end">
              <Link
                href="/contact"
                className="rounded-full bg-ink px-6 py-3 text-sm text-paper hover:bg-ink/85"
              >
                의뢰 보내기 →
              </Link>
            </div>
          </div>
        </div>
      </section>
    </>
  );
}
