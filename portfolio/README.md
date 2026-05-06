# 디자인에빠지다 — Portfolio

그래픽/브랜딩 스튜디오 **디자인에빠지다**의 포트폴리오 홈페이지.

- Next.js 14 (App Router) + TypeScript
- Tailwind CSS (커스텀 paper/ink 팔레트, Display serif 타이포)
- 페이지: Home / Works / About / Contact

## 시작하기

```bash
cd portfolio
npm install
npm run dev
```

브라우저에서 http://localhost:3000 으로 접속.

## 구조

```
portfolio/
  app/                  # 라우트 (Next.js App Router)
    page.tsx            # Home
    works/page.tsx      # 작업물 갤러리
    about/page.tsx      # 스튜디오 소개
    contact/page.tsx    # 의뢰 폼
  components/           # 공통 UI (Header, Footer, WorkCard)
  data/                 # 사이트/작업물 데이터 (편집 포인트)
```

## 콘텐츠 편집

- 사이트 메타정보, 연락처, SNS: `data/site.ts`
- 작업물 카드/팔레트/요약: `data/works.ts`

이미지 자산은 `public/` 에 추가한 뒤 `data/works.ts` 의 `cover` 필드를
파일 경로(`/works/foo.jpg`)로 바꿔 사용하면 됩니다. 현재는 그라디언트
플레이스홀더를 사용하고 있어 자산 없이도 미리볼 수 있습니다.
