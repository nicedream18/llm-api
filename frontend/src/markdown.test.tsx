import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { renderWikiMarkdown } from "./markdown";

const attachmentPrefix = "/api/v1/wiki/projects/project-1/attachments/";
const render = (source: string) => renderToStaticMarkup(renderWikiMarkdown(source, attachmentPrefix));

describe("Wiki Markdown preview", () => {
  it("renders basic formatting while escaping HTML", () => {
    const html = render("# <img src=x onerror=alert(1)>\n**<script>bad()</script>**");
    expect(html).toContain("&lt;img src=x onerror=alert(1)&gt;");
    expect(html).toContain("&lt;script&gt;bad()&lt;/script&gt;");
    expect(html).not.toContain("<img src=x");
    expect(html).not.toContain("<script>");
  });

  it("keeps fenced code as escaped code and supports lists", () => {
    const html = render("```ts\n# code\n<img>\n```\n- first\n- second");
    expect(html).toContain('<pre><code class="language-ts"># code\n&lt;img&gt;</code></pre>');
    expect(html).toContain("<ul><li><span>first</span></li><li><span>second</span></li></ul>");
    expect(html).not.toContain("<h1>");
  });

  it("rejects unsafe targets and limits inline images to project attachments", () => {
    const html = render(`[unsafe](javascript:alert(1)) ![remote](https://tracker.example/pixel.png) ![local](${attachmentPrefix}asset-1)`);
    expect(html).not.toContain('<a href="javascript:');
    expect(html).not.toContain('<img src="https://tracker.example');
    expect(html).toContain(`<img src="${attachmentPrefix}asset-1" alt="local" loading="lazy"/>`);
    expect(html).toContain("unsafe");
  });

  it("opens external links with noopener protection", () => {
    const html = render("[manual](https://docs.example.test/guide)");
    expect(html).toContain('target="_blank" rel="noopener noreferrer"');
  });
});
