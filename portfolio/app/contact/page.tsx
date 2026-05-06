import type { Metadata } from "next";
import { site } from "@/data/site";

export const metadata: Metadata = {
  title: "Contact",
  description: `${site.name}에게 프로젝트 의뢰하기.`
};

const fields: Array<{
  name: string;
  label: string;
  type?: "text" | "email" | "textarea";
  placeholder?: string;
}> = [
  { name: "name", label: "성함 / 브랜드명", placeholder: "예) 늘봄 베이커리" },
  { name: "email", label: "이메일", type: "email", placeholder: "you@brand.com" },
  { name: "budget", label: "예상 예산 / 일정", placeholder: "예) 1,000만원 / 8주" },
  {
    name: "message",
    label: "프로젝트 내용",
    type: "textarea",
    placeholder: "어떤 결의 디자인을 찾고 계신가요? 자유롭게 적어주세요."
  }
];

export default function ContactPage() {
  return (
    <section className="container-page py-20 md:py-28">
      <div className="grid gap-16 md:grid-cols-12">
        <div className="md:col-span-5">
          <p className="eyebrow">Contact</p>
          <h1 className="mt-4 font-display text-5xl leading-[1.05] md:text-6xl">
            함께 만들고 싶은
            <br />
            이야기를 들려주세요.
          </h1>
          <p className="mt-6 text-ink/75">
            아래 양식을 채워 보내주시거나, 메일로 직접 연락 주셔도 좋습니다.
            영업일 기준 2일 안에 답변드립니다.
          </p>

          <dl className="mt-10 space-y-6 border-t border-ink/15 pt-8">
            <div>
              <dt className="eyebrow">Email</dt>
              <dd className="mt-1">
                <a className="link-underline" href={`mailto:${site.email}`}>
                  {site.email}
                </a>
              </dd>
            </div>
            <div>
              <dt className="eyebrow">Studio</dt>
              <dd className="mt-1 text-ink/80">{site.location}</dd>
            </div>
            <div>
              <dt className="eyebrow">Instagram</dt>
              <dd className="mt-1">
                <a
                  className="link-underline"
                  href={site.instagram}
                  target="_blank"
                  rel="noreferrer"
                >
                  @design.eppajida
                </a>
              </dd>
            </div>
          </dl>
        </div>

        <form
          className="md:col-span-7"
          action={`mailto:${site.email}`}
          method="post"
          encType="text/plain"
        >
          <div className="grid gap-6">
            {fields.map((f) => (
              <label key={f.name} className="block">
                <span className="eyebrow">{f.label}</span>
                {f.type === "textarea" ? (
                  <textarea
                    name={f.name}
                    rows={6}
                    placeholder={f.placeholder}
                    className="mt-2 w-full resize-none border-b border-ink/30 bg-transparent py-3 text-base outline-none placeholder:text-ink/30 focus:border-ink"
                  />
                ) : (
                  <input
                    name={f.name}
                    type={f.type ?? "text"}
                    placeholder={f.placeholder}
                    className="mt-2 w-full border-b border-ink/30 bg-transparent py-3 text-base outline-none placeholder:text-ink/30 focus:border-ink"
                  />
                )}
              </label>
            ))}
          </div>
          <button
            type="submit"
            className="mt-10 inline-flex items-center gap-2 rounded-full bg-ink px-6 py-3 text-sm text-paper transition-colors hover:bg-ink/85"
          >
            보내기 <span aria-hidden>→</span>
          </button>
          <p className="mt-3 text-xs text-ink/50">
            전송 시 기본 메일 앱이 열립니다. 백엔드 연결은 추후 추가 예정입니다.
          </p>
        </form>
      </div>
    </section>
  );
}
