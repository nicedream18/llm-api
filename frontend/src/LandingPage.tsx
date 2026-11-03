import { lazy, Suspense, useState, type ReactNode } from "react";
import { Button, Collapse, ConfigProvider, Segmented, Tag, theme } from "antd";
import {
  ArrowDownOutlined, ArrowRightOutlined, ArrowUpOutlined, BookOutlined,
  CheckOutlined, CheckCircleFilled, CodeOutlined, CopyOutlined,
  DatabaseOutlined, GithubOutlined, GlobalOutlined, MenuOutlined, MoreOutlined,
  PlusOutlined, SafetyOutlined, ThunderboltOutlined, UnorderedListOutlined,
} from "@ant-design/icons";
import "./landing.css";

const LandingDrawer = lazy(() => import("./LandingDrawer"));
const repository = "https://github.com/nicedream18/llm-api";
type Demo = "gateway" | "knowledge" | "security";
type Language = "Python" | "cURL" | "Node.js";
const demoOptions = [
  { label: "模型网关", value: "gateway", icon: <GlobalOutlined aria-hidden="true" /> },
  { label: "知识检索", value: "knowledge", icon: <DatabaseOutlined aria-hidden="true" /> },
  { label: "安全审计", value: "security", icon: <SafetyOutlined aria-hidden="true" /> },
];
const demos: Record<Demo, { label: string; title: string; description: string; request: ReactNode; response: ReactNode }> = {
  gateway: {
    label: "统一模型接入", title: "一个入口，连接你的 AI 世界。", description: "熟悉的接口。自由选择的模型。",
    request: <HighlightedCode value={'const client = new OpenAI({\n  baseURL: "http://localhost:9900/v1",\n  apiKey: process.env.WALIAPI_API_KEY\n});\n\nawait client.chat.completions.create({\n  model: "my-model",\n  messages: [{ role: "user", content: "Hello, world." }]\n});'} />,
    response: <><span className="demo-log-time">01</span><span>解析模型与路由策略</span><CheckOutlined aria-hidden="true" /><span className="demo-log-time">02</span><span>选择可用的上游渠道</span><CheckOutlined aria-hidden="true" /><span className="demo-log-time">03</span><span>返回统一格式的响应</span><CheckOutlined aria-hidden="true" /></>,
  },
  knowledge: {
    label: "让 AI 理解你的上下文", title: "让答案，来自你的知识。", description: "文档不再散落，想法有据可循。",
    request: <><span className="syn-muted">// 把文档转成可检索的上下文</span><br /><span className="syn-purple">const</span> question = <span className="syn-green">"产品的接入流程是什么？"</span>;<br /><br /><span className="syn-purple">const</span> context = [<br />{"  "}<span className="syn-green">"快速开始.md"</span>,<br />{"  "}<span className="syn-green">"产品设计笔记.md"</span><br />];<br /><br /><span className="syn-muted">// 检索 → 引用 → 回答</span><br /><span className="syn-blue">answer</span>(question, context);</>,
    response: <><span className="demo-log-time">01</span><span>导入文档与项目资料</span><CheckOutlined aria-hidden="true" /><span className="demo-log-time">02</span><span>检索相关的知识片段</span><CheckOutlined aria-hidden="true" /><span className="demo-log-time">03</span><span>为回答补充来源与上下文</span><CheckOutlined aria-hidden="true" /></>,
  },
  security: {
    label: "把安全放在转发之前", title: "专注创造，也照顾好边界。", description: "可配置的规则，清晰可见的处置。",
    request: <><span className="syn-muted">// 开启密钥自动脱敏后的示例</span><br />{"{"}<br />{"  "}<span className="syn-blue">"model"</span>: <span className="syn-green">"my-model"</span>,<br />{"  "}<span className="syn-blue">"password"</span>: <span className="syn-green">"[REDACTED]"</span>,<br />{"  "}<span className="syn-blue">"messages"</span>: [{"{"}<br />{"    "}<span className="syn-blue">"role"</span>: <span className="syn-green">"user"</span>,<br />{"    "}<span className="syn-blue">"content"</span>: <span className="syn-green">"帮我整理今天的灵感"</span><br />{"  "}{"}"}]<br />{"}"}</>,
    response: <><span className="demo-log-time">01</span><span>按有效策略扫描请求</span><CheckOutlined aria-hidden="true" /><span className="demo-log-time">02</span><span>清理命中的敏感凭证</span><CheckOutlined aria-hidden="true" /><span className="demo-log-time">03</span><span>记录已脱敏的审计发现</span><CheckOutlined aria-hidden="true" /></>,
  },
};

export const codeSamples: Record<Language, string> = {
  Python: `import os\nfrom openai import OpenAI\n\nclient = OpenAI(\n    base_url="http://localhost:9900/v1",\n    api_key=os.environ["WALIAPI_API_KEY"],\n)\n\nresponse = client.chat.completions.create(\n    model="my-model",\n    messages=[{"role": "user", "content": "让我们开始创造。"}],\n)\nprint(response.choices[0].message.content)`,
  cURL: `curl http://localhost:9900/v1/chat/completions \\\n  -H "Authorization: Bearer $WALIAPI_API_KEY" \\\n  -H "Content-Type: application/json" \\\n  -d '{\n    "model": "my-model",\n    "messages": [\n      {"role": "user", "content": "让我们开始创造。"}\n    ]\n  }'`,
  "Node.js": `import OpenAI from "openai";\n\nconst client = new OpenAI({\n  baseURL: "http://localhost:9900/v1",\n  apiKey: process.env.WALIAPI_API_KEY,\n});\n\nconst response = await client.chat.completions.create({\n  model: "my-model",\n  messages: [{ role: "user", content: "让我们开始创造。" }],\n});\nconsole.log(response.choices[0].message.content);`,
};

function Brand({ small = false }: { small?: boolean }) {
  return <a className={`landing-brand${small ? " landing-brand-small" : ""}`} href="#top" aria-label="WaLiAPI 首页"><span className="landing-brand-symbol" aria-hidden="true"><svg viewBox="0 0 30 30" fill="none"><path d="m4 10 5 12 6-15 6 15 5-12" stroke="currentColor" strokeWidth="2.7" strokeLinecap="round" strokeLinejoin="round" /></svg></span><span>WaLi<span className="brand-api">API</span></span></a>;
}

function ProductPreview() {
  const [active, setActive] = useState<Demo>("gateway");
  const demo = demos[active];
  return <div className="product-stage" id="product-demo">
    <div className="stage-glow" aria-hidden="true" />
    <div className="product-window">
      <div className="window-topbar"><div className="window-dots" aria-hidden="true"><i /><i /><i /></div><span><span className="tiny-brand">W</span> my-workspace <span className="window-slash">/</span> overview</span><span className="demo-indicator"><i />交互演示</span></div>
      <div className="window-layout">
        <div className="preview-sidebar" aria-hidden="true"><div className="workspace-name"><span className="workspace-avatar">M</span> 我的工作台 <MoreOutlined aria-hidden="true" /></div><span className="sidebar-section-label">WORKSPACE</span><div className={`preview-nav${active === "gateway" ? " selected" : ""}`}><GlobalOutlined aria-hidden="true" />模型网关<span>⌘ 1</span></div><div className={`preview-nav${active === "knowledge" ? " selected" : ""}`}><DatabaseOutlined aria-hidden="true" />知识库<span>⌘ 2</span></div><div className={`preview-nav${active === "security" ? " selected" : ""}`}><SafetyOutlined aria-hidden="true" />安全审计<span>⌘ 3</span></div><div className="preview-nav"><UnorderedListOutlined aria-hidden="true" />请求日志</div><div className="sidebar-project"><span className="sidebar-section-label">MY PROJECTS</span><PlusOutlined aria-hidden="true" /></div><div className="preview-project"><i />下一个好产品</div><div className="preview-project"><i />周末实验室</div><div className="sidebar-bottom"><span className="avatar-circle">Y</span><span>Just you. And your ideas.</span></div></div>
        <div className="preview-content">
          <div className="preview-breadcrumb">工作空间 <span>/</span> 产品概览 <span className="preview-keyboard">⌘ K</span></div>
          <div className="preview-title-row"><div><span className="preview-eyebrow">YOUR NEXT BIG THING</span><h2>{demo.title}</h2><p>{demo.description}</p></div><Tag variant="filled" className="preview-example-tag">示例数据</Tag></div>
          <Segmented aria-label="产品能力演示" block options={demoOptions} value={active} onChange={value => setActive(value as Demo)} className="demo-segmented" />
          <div className="preview-panels"><div className="preview-code-panel"><div className="preview-panel-header"><span><CodeOutlined aria-hidden="true" />{active === "gateway" ? "hello-world.ts" : active === "knowledge" ? "knowledge.ts" : "sanitized-request.json"}</span><span className="panel-file-type">{active === "security" ? "JSON" : "TypeScript"}</span></div><pre aria-label={demo.label}><code>{demo.request}</code></pre></div><div className="preview-flow-panel"><div className="preview-panel-header"><span><ThunderboltOutlined aria-hidden="true" />执行链路</span><span className="flow-status">PREVIEW</span></div><div className="request-flow">{demo.response}</div><div className="preview-response"><span><CheckCircleFilled aria-hidden="true" /> {active === "security" ? "凭证已替换" : active === "knowledge" ? "上下文已就绪" : "统一接口已就绪"}</span><p>{active === "gateway" ? "用你熟悉的方式，构建不一样的产品。" : active === "knowledge" ? "让每个回答，都有自己的知识底座。" : "安全策略，在连接上游之前生效。"}</p></div></div></div>
          <div className="preview-bottom-line"><span><i />{demo.label}</span><span>一个工作空间，无限种可能 <ArrowUpOutlined aria-hidden="true" /></span></div>
        </div>
      </div>
    </div>
    <div className="stage-footnote"><span className="footnote-line" />从第一行代码，到下一个作品。<span className="footnote-line" /></div>
  </div>;
}

function HighlightedCode({ value }: { value: string }) {
  return <>{value.split(/("[^"\n]*"|'[^'\n]*'|\b(?:import|from|const|await|new|print)\b)/g).map((part, index) => <span key={index} className={/^["']/.test(part) ? "syn-green" : /^(import|from|const|await|new|print)$/.test(part) ? "syn-purple" : undefined}>{part}</span>)}</>;
}

export function LandingPage() {
  const [menuOpen, setMenuOpen] = useState(false);
  const [language, setLanguage] = useState<Language>("Python");
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState(false);
  const copy = async () => {
    setCopied(false); setCopyError(false);
    try { await navigator.clipboard.writeText(codeSamples[language]); setCopied(true); }
    catch { setCopyError(true); }
  };
  const links = <><a href="#features" onClick={() => setMenuOpen(false)}>产品能力</a><a href="#developers" onClick={() => setMenuOpen(false)}>开发者</a><a href="#questions" onClick={() => setMenuOpen(false)}>常见问题</a><a href={repository} target="_blank" rel="noreferrer">源码 <ArrowUpOutlined aria-hidden="true" /></a></>;
  return <ConfigProvider theme={{ algorithm: theme.darkAlgorithm, token: { colorPrimary: "#b8b4ff", colorBgBase: "#08090b", colorText: "#eeeeF0", colorTextSecondary: "#96969f", colorBorder: "#28292e", borderRadius: 8, fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif', controlHeight: 42 }, components: { Button: { primaryShadow: "none", fontWeight: 500 }, Segmented: { trackBg: "#111216", itemSelectedBg: "#25262d", itemSelectedColor: "#f7f7f8" }, Collapse: { headerBg: "transparent", contentBg: "transparent" } } }}>
    <div className="landing-site" id="top">
      <a href="#landing-main" className="landing-skip-link">跳到主要内容</a>
      <header className="landing-header"><div className="landing-header-inner"><Brand /><nav aria-label="主导航" className="landing-nav">{links}</nav><div className="landing-header-actions"><a className="header-github" href={repository} target="_blank" rel="noreferrer" aria-label="在 GitHub 查看 WaLiAPI"><GithubOutlined aria-hidden="true" /></a><Button href="/admin/" className="landing-console-button">进入控制台 <ArrowRightOutlined aria-hidden="true" /></Button><Button type="text" className="landing-mobile-menu" aria-label="打开导航菜单" icon={<MenuOutlined aria-hidden="true" />} onClick={() => setMenuOpen(true)} /></div></div></header>
      {menuOpen && <Suspense fallback={<span role="status" className="landing-sr-only">正在加载导航…</span>}><LandingDrawer title={<Brand small />} onClose={() => setMenuOpen(false)}><nav aria-label="移动导航" className="landing-drawer-links">{links}<Button href="/admin/" className="landing-white-button">进入控制台 <ArrowRightOutlined aria-hidden="true" /></Button></nav></LandingDrawer></Suspense>}
      <main id="landing-main" tabIndex={-1}>
        <section className="landing-hero" aria-labelledby="hero-title"><a className="hero-announcement" href="#features"><span className="announcement-dot" />为独立开发者而构建<span className="announcement-divider" /><span className="announcement-detail">小团队，大想法</span><ArrowRightOutlined aria-hidden="true" /></a><h1 id="hero-title">让灵感，<br /><span>快一步成为产品。</span></h1><p className="hero-description">你的下一个作品，值得更专注的创造。<br />将模型、知识与工具连接起来，把复杂留给 WaLiAPI。</p><div className="hero-actions"><Button href="/admin/" className="landing-white-button" size="large">开始构建 <ArrowRightOutlined aria-hidden="true" /></Button><Button href="#developers" type="text" size="large" className="landing-text-button">查看接入示例 <ArrowDownOutlined aria-hidden="true" /></Button></div><p className="hero-note">自主部署 <span>·</span> 兼容 OpenAI 接口 <span>·</span> 为你的工作流而生</p></section>
        <div className="landing-container"><ProductPreview /></div>
        <section className="landing-integrations landing-container" aria-label="兼容模型生态"><p>连接你已在用的模型，让创造不受边界限制。</p><div className="integration-wordmarks"><span><span className="provider-mark openai-mark" aria-hidden="true">✺</span>OpenAI</span><span className="anthropic-wordmark">ANTHROPIC</span><span className="gemini-wordmark"><span aria-hidden="true">✦</span> Gemini</span><span className="ollama-wordmark"><span aria-hidden="true">♧</span>ollama</span><span className="compatible-wordmark"><CodeOutlined aria-hidden="true" />你的 API</span></div></section>
        <section className="landing-features landing-container" id="features" aria-labelledby="features-title"><div className="section-heading"><div><span className="landing-eyebrow">LESS FRICTION. MORE CREATION.</span><h2 id="features-title">一个人的创造力，<br /><span>不该被工具限制。</span></h2></div><p>从一个灵感，到一次真实的发布。<br />你需要的 AI 基础能力，在这里协同工作。</p></div><div className="feature-grid"><article className="landing-feature"><div className="feature-icon"><GlobalOutlined aria-hidden="true" /></div><h3>模型自由，接口统一。</h3><p>连接不同模型渠道，沿用熟悉的接口。切换模型时，专注产品，而不是重写接入代码。</p><div className="model-diagram" aria-hidden="true"><span className="diagram-source">你的产品</span><span className="diagram-wire" /><span className="diagram-hub">W</span><span className="diagram-branches"><i>OpenAI</i><i>Anthropic</i><i>Gemini</i></span></div><span className="feature-caption">01 <span>UNIFIED GATEWAY</span></span></article><article className="landing-feature"><div className="feature-icon"><BookOutlined aria-hidden="true" /></div><h3>给 AI，一份你的知识。</h3><p>连接项目文档与知识库，把检索到的上下文带进回答。让通用能力，理解你的具体问题。</p><div className="knowledge-diagram" aria-hidden="true"><div><span className="doc-fold" /><span>产品笔记.md</span><i>Markdown</i></div><div><span className="doc-fold" /><span>接入指南.pdf</span><i>Document</i></div><div className="knowledge-result"><CheckCircleFilled aria-hidden="true" />找到相关上下文<span>↗</span></div></div><span className="feature-caption">02 <span>YOUR OWN CONTEXT</span></span></article><article className="landing-feature"><div className="feature-icon"><SafetyOutlined aria-hidden="true" /></div><h3>安全感，藏在细节里。</h3><p>用规则管理风险，在转发前清理敏感凭证。黑白名单、审计发现，让每次处置有迹可循。</p><div className="security-diagram" aria-hidden="true"><div><span>api_key</span><code>•••• •••• ••••</code><SafetyOutlined aria-hidden="true" /></div><div className="security-status"><i />[REDACTED]<span>凭证脱敏</span></div></div><span className="feature-caption">03 <span>BUILT WITH BOUNDARIES</span></span></article></div></section>
        <section className="landing-developers landing-container" id="developers" aria-labelledby="developers-title"><div className="developer-intro"><span className="landing-eyebrow">FEELS FAMILIAR. GOES FURTHER.</span><h2 id="developers-title">熟悉的代码，<br /><span>新的可能。</span></h2><p>保留你喜欢的 SDK，只需把请求指向自己的网关。剩下的时间，写那些让产品与众不同的代码。</p><ul><li><CheckOutlined aria-hidden="true" />兼容 OpenAI SDK 的调用方式</li><li><CheckOutlined aria-hidden="true" />集中管理渠道、密钥与路由</li><li><CheckOutlined aria-hidden="true" />在控制台查看请求与安全发现</li></ul><a className="inline-arrow-link" href={`${repository}#快速启动`} target="_blank" rel="noreferrer">阅读快速开始 <ArrowRightOutlined aria-hidden="true" /></a></div><div className="developer-code"><div className="developer-code-toolbar"><Segmented aria-label="示例代码语言" options={["Python", "cURL", "Node.js"]} value={language} onChange={value => { setLanguage(value as Language); setCopied(false); setCopyError(false); }} /><Button type="text" aria-label={copied ? "代码已复制" : "复制示例代码"} icon={copied ? <CheckOutlined aria-hidden="true" /> : <CopyOutlined aria-hidden="true" />} onClick={() => void copy()}>{copied ? "已复制" : "复制"}</Button></div><pre tabIndex={0} aria-label={`${language} 接入示例`}><code><HighlightedCode value={codeSamples[language]} /></code></pre><div className="developer-code-note"><span className="code-file-dot" />{language === "Python" ? "hello_world.py" : language === "cURL" ? "terminal" : "hello-world.ts"}<span>YOUR NEXT IDEA STARTS HERE</span></div><p className="code-setup-note">先在控制台配置渠道，再将 my-model 替换为你的模型名称。</p>{copyError && <p className="landing-copy-error" role="alert">复制失败，请手动选择代码。</p>}<span className="landing-sr-only" role="status">{copied ? "示例代码已复制到剪贴板" : ""}</span></div></section>
        <section className="landing-ownership landing-container" aria-labelledby="ownership-title"><div className="ownership-symbol" aria-hidden="true"><span /><GlobalOutlined aria-hidden="true" /><span /></div><span className="landing-eyebrow">YOUR STACK. YOUR RULES.</span><h2 id="ownership-title">你的工作流。<br /><span>始终由你掌控。</span></h2><p>部署在自己的环境，连接自己选择的模型。<br />从周末的小实验，到认真打磨的产品，按你的节奏生长。</p><a href={repository} className="inline-arrow-link" target="_blank" rel="noreferrer"><GithubOutlined aria-hidden="true" />探索项目源码 <ArrowRightOutlined aria-hidden="true" /></a></section>
        <section className="landing-faq landing-container" id="questions" aria-labelledby="faq-title"><div><span className="landing-eyebrow">A FEW MORE THINGS.</span><h2 id="faq-title">开始之前，<br /><span>你可能想知道。</span></h2></div><Collapse ghost expandIconPosition="end" items={[
          { key: "start", label: "我该从哪里开始？", children: <p>按照项目 README 完成部署，在控制台添加模型渠道、配置访问密钥，再使用上面的 SDK 示例接入。<a href={`${repository}#快速启动`} target="_blank" rel="noreferrer">查看快速启动指南 ↗</a></p> },
          { key: "models", label: "可以使用哪些模型和工具？", children: <p>项目提供 OpenAI 兼容、Anthropic、Gemini 和 Ollama 适配器，也支持配置知识库与 MCP 工具。具体可用模型取决于你接入的上游渠道和权限。</p> },
          { key: "hosting", label: "这是一个托管的 AI 服务吗？", children: <p>这是可自行部署的 AI 网关与工作台。你需要准备运行环境、数据库和上游模型凭证；模型调用费用及可用性由你选择的供应商决定。</p> },
          { key: "security", label: "安全扫描覆盖哪些内容？", children: <p>支持普通 JSON、流式请求体、multipart 文本字段与普通响应。密钥自动脱敏需要在安全策略中开启；暂不扫描二进制附件和流式响应。<a href={`${repository}/blob/codex/security-rules-redaction/docs/security/upgrade.md`} target="_blank" rel="noreferrer">了解能力边界 ↗</a></p> },
        ]} /></section>
        <section className="landing-final-cta landing-container"><span className="landing-eyebrow">MAKE SOMETHING THAT MATTERS.</span><h2>下一个好作品，<br /><span>从你的想法开始。</span></h2><p>少一点准备，多一点开始。</p><Button href="/admin/" className="landing-white-button" size="large">开始构建 <ArrowRightOutlined aria-hidden="true" /></Button></section>
      </main>
      <footer className="landing-footer landing-container"><div><Brand small /><p>Built for the ones who build.</p></div><nav aria-label="页脚导航"><a href={`${repository}#快速启动`} target="_blank" rel="noreferrer">文档</a><a href={repository} target="_blank" rel="noreferrer">GitHub <ArrowUpOutlined aria-hidden="true" /></a><a href="/admin/">控制台 <ArrowUpOutlined aria-hidden="true" /></a></nav><span className="footer-credit">独立创造，保持好奇。</span></footer>
    </div>
  </ConfigProvider>;
}
