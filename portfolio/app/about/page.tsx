import type { Metadata } from "next";
import { site } from "@/data/site";

export const metadata: Metadata = {
  title: "About",
  description: `${site.name}의 일하는 방식과 철학.`
};

const services = [
  {
    title: "Brand Identity",
    items: [
      "BI/CI 시스템",
      "로고 · 워드마크",
      "타이포그래피 시스템",
      "브랜드 가이드라인"
    ]
  },
  {
    title: "Editorial",
    items: ["도서 · 매거진", "전시 도록", "리포트 · 카탈로그", "리소그래피"]
  },
  {
    title: "Packaging",
    items: ["F&B 패키지", "리테일 굿즈", "리미티드 에디션", "라벨 시스템"]
  }
];

const process = [
  {
    step: "01",
    name: "Discover",
    desc: "브랜드의 시작점, 사용자, 시장의 결을 듣고 이해합니다."
  },
  {
    step: "02",
    name: "Define",
    desc: "키워드와 무드를 정리해 시각의 방향을 제안합니다."
  },
  {
    step: "03",
    name: "Design",
    desc: "여러 갈래의 시안을 만들고 함께 결정해 나갑니다."
  },
  {
    step: "04",
    name: "Deliver",
    desc: "인쇄·디지털 환경에서 일관되게 작동하는 자산으로 마무리합니다."
  }
];

export default function AboutPage() {
  return (
    <>
      <section className="container-page py-20 md:py-28">
        <p className="eyebrow">About</p>
        <h1 className="mt-4 max-w-4xl font-display text-5xl leading-[1.05] md:text-7xl">
          느린 호흡으로,
          <br />
          한 결의 디자인을 만듭니다.
        </h1>
        <div className="mt-10 grid gap-10 md:grid-cols-12">
          <p className="text-lg leading-relaxed text-ink/75 md:col-span-8">
            {site.name}은 작은 동네 가게부터 문화 브랜드까지, 브랜드가 가진
            고유한 결을 발견해 시각 언어로 옮기는 그래픽 디자인 스튜디오입니다.
            매번 ‘처음 본 것 같은 익숙함’을 만들기 위해 클라이언트와 깊이
            대화하고, 인쇄 · 디지털 · 공간을 가로지르는 통합된 디자인 시스템을
            제안합니다.
          </p>
          <dl className="grid grid-cols-2 gap-6 self-end md:col-span-4">
            {[
              { k: "Founded", v: "2019" },
              { k: "Studio", v: site.location },
              { k: "Projects", v: "60+" },
              { k: "Clients", v: "40+" }
            ].map((s) => (
              <div key={s.k}>
                <dt className="eyebrow">{s.k}</dt>
                <dd className="mt-1 font-display text-2xl">{s.v}</dd>
              </div>
            ))}
          </dl>
        </div>
      </section>

      <section className="border-y border-ink/10 bg-paper">
        <div className="container-page py-20 md:py-28">
          <p className="eyebrow">Services</p>
          <h2 className="mt-3 font-display text-4xl md:text-5xl">
            함께 만드는 것들.
          </h2>
          <div className="mt-12 grid gap-10 md:grid-cols-3">
            {services.map((s) => (
              <div key={s.title} className="border-t border-ink pt-6">
                <p className="font-display text-2xl">{s.title}</p>
                <ul className="mt-4 space-y-1 text-sm text-ink/75">
                  {s.items.map((it) => (
                    <li key={it}>— {it}</li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="container-page py-20 md:py-28">
        <p className="eyebrow">Process</p>
        <h2 className="mt-3 font-display text-4xl md:text-5xl">
          일하는 순서.
        </h2>
        <ol className="mt-12 grid gap-8 md:grid-cols-4">
          {process.map((p) => (
            <li key={p.step} className="border-t border-ink/30 pt-5">
              <p className="text-sm text-ink/50">{p.step}</p>
              <p className="mt-2 font-display text-2xl">{p.name}</p>
              <p className="mt-2 text-sm leading-relaxed text-ink/70">
                {p.desc}
              </p>
            </li>
          ))}
        </ol>
      </section>
    </>
  );
}
