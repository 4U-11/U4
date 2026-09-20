import Link from "next/link";

export default function Home() {
  return (
    <div className="home-page">
      <header className="home-header">
        <Link
          href="/"
          className="home-brand"
          aria-label="课程材料学习助手首页"
        >
          <span className="home-logo-placeholder">LOGO 占位</span>
        </Link>
      </header>

      <main className="home-hero">
        <h1>让外教课学习变得简单高效</h1>

        <p>
          上传 PDF 或 DOCX，快速整理重点、翻译内容、提取代码，
          并生成清晰的学习步骤
        </p>

        <Link href="/mine" className="home-primary-button">
          <span>START</span>
          <span aria-hidden="true">→</span>
        </Link>
      </main>
    </div>
  );
}
