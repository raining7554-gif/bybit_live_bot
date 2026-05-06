export type Work = {
  slug: string;
  title: string;
  client: string;
  category: "Branding" | "Editorial" | "Packaging" | "Identity" | "Typography";
  year: number;
  cover: string;
  palette: string[];
  summary: string;
};

export const works: Work[] = [
  {
    slug: "moam-coffee",
    title: "MOAM Coffee",
    client: "MOAM Roasters",
    category: "Branding",
    year: 2025,
    cover: "linear-gradient(135deg,#e9dccb 0%,#bca082 100%)",
    palette: ["#2a1f17", "#bca082", "#e9dccb"],
    summary:
      "느린 호흡으로 원두를 다루는 로스터리의 시각 언어. 손글씨 워드마크와 크라프트 패키지로 작업실의 공기를 담았습니다."
  },
  {
    slug: "neulbom-bakery",
    title: "늘봄 베이커리",
    client: "Neulbom Bake Studio",
    category: "Identity",
    year: 2024,
    cover: "linear-gradient(135deg,#ffd9c2 0%,#ff8a5b 100%)",
    palette: ["#3a1d10", "#ff8a5b", "#ffd9c2"],
    summary:
      "동네 단골을 위한 따뜻한 아이덴티티. 모던 산세리프와 손그림 일러스트가 공존하는 시스템을 구축했습니다."
  },
  {
    slug: "object-magazine",
    title: "OBJECT Magazine Vol.04",
    client: "OBJECT Press",
    category: "Editorial",
    year: 2024,
    cover: "linear-gradient(135deg,#dfe7e1 0%,#5d7466 100%)",
    palette: ["#1c2a22", "#5d7466", "#dfe7e1"],
    summary:
      "일상의 사물을 새롭게 바라보는 독립 매거진의 04호 아트디렉션. 활자 중심의 그리드와 풍성한 여백을 활용했습니다."
  },
  {
    slug: "haedam-tea",
    title: "해담 차(茶)",
    client: "Haedam Tea Atelier",
    category: "Packaging",
    year: 2023,
    cover: "linear-gradient(135deg,#f4ecd8 0%,#9aa66c 100%)",
    palette: ["#2d3015", "#9aa66c", "#f4ecd8"],
    summary:
      "동양 전통의 결을 현대적으로 풀어낸 차 패키지. 한지 질감과 묵의 농담을 그래픽으로 변환했습니다."
  },
  {
    slug: "studio-noon",
    title: "Studio NOON",
    client: "NOON Architects",
    category: "Identity",
    year: 2023,
    cover: "linear-gradient(135deg,#eef0f2 0%,#9ba4ad 100%)",
    palette: ["#15181b", "#9ba4ad", "#eef0f2"],
    summary:
      "정오의 빛을 모티브로 한 건축 스튜디오의 BI. 그림자 길이를 따라 변하는 모듈형 로고 시스템을 설계했습니다."
  },
  {
    slug: "type-specimen",
    title: "한글 타입 스페시멘 '결'",
    client: "Self-initiated",
    category: "Typography",
    year: 2022,
    cover: "linear-gradient(135deg,#111111 0%,#3a3a3a 100%)",
    palette: ["#111111", "#3a3a3a", "#f7f5f0"],
    summary:
      "한글 자소의 결을 시각화한 자체 타입 스페시멘. 24페이지 리소그래피 출판물로 발행되었습니다."
  }
];
