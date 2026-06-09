import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { ACTIVATE_EVENT, saveAuthSession } from "../auth";

const FEATURES = [
  {
    icon: "neurology",
    title: "AI 智能组价",
    desc: "基于深度学习的工程量清单自动生成与智能匹配定额，准确率高达 96%。",
    gradient: "linear-gradient(135deg, #1456b8 0%, #22a2f2 100%)",
  },
  {
    icon: "view_in_ar",
    title: "BIM 数据联动",
    desc: "无缝对接 Revit / IFC 模型，一键提取工程量并同步至造价清单。",
    gradient: "linear-gradient(135deg, #8b5cf6 0%, #a78bfa 100%)",
  },
  {
    icon: "monitoring",
    title: "实时市场价采集",
    desc: "每日同步全国 200+ 城市材料价格，动态生成精准单价分析。",
    gradient: "linear-gradient(135deg, #22c55e 0%, #4ade80 100%)",
  },
  {
    icon: "contract",
    title: "合规审计引擎",
    desc: "内置 GB50500 / HKSMM4 多标准规则库，自动识别计价偏差与违规项。",
    gradient: "linear-gradient(135deg, #f59e0b 0%, #fbbf24 100%)",
  },
  {
    icon: "draw",
    title: "智能图纸识别",
    desc: "OCR + AI 多模态识别建筑施工图，自动提取构件信息与工程量。",
    gradient: "linear-gradient(135deg, #ef4444 0%, #f87171 100%)",
  },
  {
    icon: "query_stats",
    title: "造价大数据分析",
    desc: "千万级历史工程数据驱动，为投标报价和成本控制提供数据支撑。",
    gradient: "linear-gradient(135deg, #06b6d4 0%, #67e8f9 100%)",
  },
];

const STATS = [
  { value: "96%", label: "清单匹配准确率" },
  { value: "200+", label: "城市价格覆盖" },
  { value: "50万+", label: "定额条目数据库" },
  { value: "10x", label: "效率提升" },
];

const FOOTER_LINKS = {
  产品: ["核心组价引擎", "BIM数据同步", "市场价采集", "合规审计"],
  服务: ["私有化部署", "定制化开发", "专家咨询", "培训支持"],
};

type TrialDays = 7 | 14;

const TRIAL_OPTIONS: Array<{
  days: TrialDays;
  title: string;
  desc: string;
  badge: string;
}> = [
  {
    days: 7,
    title: "7 天试用",
    desc: "适合快速体验核心项目、清单与组价流程。",
    badge: "快速体验",
  },
  {
    days: 14,
    title: "14 天试用",
    desc: "适合完整验证图纸识别、AI 组价和报表流程。",
    badge: "推荐",
  },
];

export default function LandingPage() {
  const navigate = useNavigate();
  const [trialOpen, setTrialOpen] = useState(false);
  const [selectedTrialDays, setSelectedTrialDays] = useState<TrialDays>(14);
  const [activationCode, setActivationCode] = useState("");
  const [activationError, setActivationError] = useState("");
  const [activationLoading, setActivationLoading] = useState(false);

  const openTrial = (days: TrialDays = 14) => {
    setSelectedTrialDays(days);
    setActivationCode("");
    setActivationError("");
    setTrialOpen(true);
  };

  useEffect(() => {
    const onActivate = (event: Event) => {
      const days = (event as CustomEvent<{ days?: TrialDays }>).detail?.days;
      openTrial(days === 7 || days === 14 ? days : 14);
    };
    window.addEventListener(ACTIVATE_EVENT, onActivate);
    if (new URLSearchParams(window.location.search).has("activate")) {
      openTrial(14);
    }
    return () => window.removeEventListener(ACTIVATE_EVENT, onActivate);
  }, []);

  const startTrial = async () => {
    const code = activationCode.trim();
    if (!code) {
      setActivationError("请输入激活码");
      return;
    }
    setActivationLoading(true);
    setActivationError("");
    try {
      const session = await api.activateTrial(code, selectedTrialDays);
      saveAuthSession(session);
      setTrialOpen(false);
      navigate("/dashboard?trial=started");
    } catch (error) {
      setActivationError(error instanceof Error ? error.message : "激活失败，请检查激活码");
    } finally {
      setActivationLoading(false);
    }
  };

  return (
    <div className="landing">
      {/* ── Navbar ── */}
      <header className="landing-nav">
        <div className="landing-container landing-nav-inner">
          <a href="/" className="landing-brand">
            <span className="material-symbols-outlined">architecture</span>
            <span className="landing-brand-text">智价 AI</span>
          </a>
          <nav className="landing-nav-links">
            <a href="#features">产品功能</a>
            <a href="#stats">数据优势</a>
            <a href="#cta">联系我们</a>
          </nav>
          <button className="landing-btn landing-btn-primary landing-btn-sm" onClick={() => navigate("/dashboard")}>
            <span className="material-symbols-outlined" style={{ fontSize: 16 }}>login</span>
            进入系统
          </button>
        </div>
      </header>

      {/* ── Hero ── */}
      <section className="landing-hero">
        <div className="landing-hero-glow" />
        <div className="landing-container landing-hero-inner">
          <span className="landing-hero-badge">
            <span className="material-symbols-outlined" style={{ fontSize: 14 }}>auto_awesome</span>
            AI 驱动的下一代造价平台
          </span>
          <h1 className="landing-hero-title">
            用人工智能重新定义<br />
            <span className="landing-hero-title-accent">建筑工程造价管理</span>
          </h1>
          <p className="landing-hero-desc">
            从工程量清单生成、定额智能匹配到市场价实时分析 —— 一站式 AI 平台覆盖全流程，让造价工作更精准、更高效。
          </p>
          <div className="landing-hero-actions">
            <button className="landing-btn landing-btn-primary landing-btn-lg" onClick={() => openTrial(14)}>
              开启 14 天免费试用
            </button>
            <button className="landing-btn landing-btn-outline landing-btn-lg" onClick={() => openTrial(7)}>
              开启 7 天试用
            </button>
            <button className="landing-btn landing-btn-outline landing-btn-lg" onClick={() => navigate("/projects")}>
              浏览演示项目
            </button>
          </div>
        </div>
      </section>

      {/* ── Stats ── */}
      <section className="landing-stats" id="stats">
        <div className="landing-container landing-stats-grid">
          {STATS.map((s) => (
            <div key={s.label} className="landing-stat-card">
              <span className="landing-stat-value">{s.value}</span>
              <span className="landing-stat-label">{s.label}</span>
            </div>
          ))}
        </div>
      </section>

      {/* ── Features ── */}
      <section className="landing-features" id="features">
        <div className="landing-container">
          <div className="landing-section-header">
            <span className="landing-section-badge">核心能力</span>
            <h2 className="landing-section-title">全方位赋能建筑造价</h2>
            <p className="landing-section-desc">
              覆盖造价管理全生命周期的 AI 能力矩阵，从数据采集到决策输出。
            </p>
          </div>
          <div className="landing-features-grid">
            {FEATURES.map((f) => (
              <div key={f.title} className="landing-feature-card">
                <div className="landing-feature-icon" style={{ background: f.gradient }}>
                  <span className="material-symbols-outlined">{f.icon}</span>
                </div>
                <h3>{f.title}</h3>
                <p>{f.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Workflow ── */}
      <section className="landing-workflow">
        <div className="landing-container">
          <div className="landing-section-header">
            <span className="landing-section-badge">工作流程</span>
            <h2 className="landing-section-title">四步完成智能造价</h2>
          </div>
          <div className="landing-workflow-grid">
            {[
              { step: "01", icon: "upload_file", title: "导入图纸 / 创建项目", desc: "上传 BIM 模型或施工图，AI 自动识别构件信息" },
              { step: "02", icon: "auto_fix_high", title: "AI 生成工程量清单", desc: "智能分析图纸数据，一键生成规范化的 BOQ 清单" },
              { step: "03", icon: "link", title: "定额匹配 & 组价", desc: "AI 引擎自动匹配最优定额，计算综合单价" },
              { step: "04", icon: "description", title: "审核 & 输出报表", desc: "合规引擎检查，一键导出专业造价报告" },
            ].map((w) => (
              <div key={w.step} className="landing-workflow-card">
                <span className="landing-workflow-step">{w.step}</span>
                <div className="landing-workflow-icon">
                  <span className="material-symbols-outlined">{w.icon}</span>
                </div>
                <h3>{w.title}</h3>
                <p>{w.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── CTA ── */}
      <section className="landing-cta" id="cta">
        <div className="landing-cta-glow" />
        <div className="landing-container landing-cta-inner">
          <h2>准备好提升您的造价效率了吗？</h2>
          <p>加入超过 500 家领先建筑单位，利用 AI 技术全面提升您的核心竞争力。</p>
          <div className="landing-hero-actions">
            <button className="landing-btn landing-btn-primary landing-btn-lg" onClick={() => openTrial(14)}>
              开启 14 天免费试用
            </button>
            <button className="landing-btn landing-btn-outline landing-btn-lg" onClick={() => openTrial(7)}>
              开启 7 天试用
            </button>
            <button className="landing-btn landing-btn-outline landing-btn-lg">联系技术专家</button>
          </div>
        </div>
      </section>

      {trialOpen && (
        <div className="landing-trial-modal" role="dialog" aria-modal="true" aria-labelledby="trial-title">
          <button className="landing-trial-backdrop" aria-label="关闭试用选择" onClick={() => setTrialOpen(false)} />
          <div className="landing-trial-panel">
            <div className="landing-trial-header">
              <span className="landing-section-badge">免费试用</span>
              <h3 id="trial-title">输入激活码</h3>
              <p>请选择试用时长，并输入对应的 {selectedTrialDays} 天激活码。</p>
            </div>
            <div className="landing-trial-options">
              {TRIAL_OPTIONS.map((option) => (
                <button
                  key={option.days}
                  className={`landing-trial-option${selectedTrialDays === option.days ? " active" : ""}`}
                  onClick={() => setSelectedTrialDays(option.days)}
                >
                  <span className="landing-trial-badge">{option.badge}</span>
                  <strong>{option.title}</strong>
                  <span>{option.desc}</span>
                </button>
              ))}
            </div>
            <div className="landing-trial-code">
              <label htmlFor="trial-code">激活码</label>
              <input
                id="trial-code"
                value={activationCode}
                onChange={(event) => setActivationCode(event.target.value)}
                placeholder={`请输入 ${selectedTrialDays} 天激活码`}
                autoComplete="off"
              />
              {activationError && <p>{activationError}</p>}
            </div>
            <div className="landing-trial-actions">
              <button className="landing-btn landing-btn-outline landing-btn-lg" onClick={() => setTrialOpen(false)} disabled={activationLoading}>
                暂不启用
              </button>
              <button className="landing-btn landing-btn-primary landing-btn-lg" onClick={startTrial} disabled={activationLoading}>
                {activationLoading ? "正在激活..." : `激活 ${selectedTrialDays} 天试用`}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Footer ── */}
      <footer className="landing-footer">
        <div className="landing-container landing-footer-grid">
          <div className="landing-footer-brand">
            <div className="landing-brand">
              <span className="material-symbols-outlined">architecture</span>
              <span className="landing-brand-text">智价 AI</span>
            </div>
            <p>引领建筑造价智能化变革，打造全球领先的 AI 建筑数字孪生引擎。</p>
          </div>
          {Object.entries(FOOTER_LINKS).map(([title, links]) => (
            <div key={title} className="landing-footer-col">
              <h4>{title}</h4>
              {links.map((l) => (
                <a key={l} href="#">{l}</a>
              ))}
            </div>
          ))}
        <div className="landing-footer-col">
            <h4>联系</h4>
            <a href="mailto:contact@cyberdigital.ai" className="landing-footer-mail">
              <span className="material-symbols-outlined" style={{ fontSize: 14 }}>mail</span>
              contact@cyberdigital.ai
            </a>
            <div className="landing-footer-socials">
              <div className="landing-footer-social-icon">
                <span className="material-symbols-outlined" style={{ fontSize: 16 }}>public</span>
              </div>
              <div className="landing-footer-social-icon">
                <span className="material-symbols-outlined" style={{ fontSize: 16 }}>share</span>
              </div>
            </div>
          </div>
          <div className="landing-footer-col">
            <h4>添加微信</h4>
            <div className="landing-footer-qrcode">
              <img src={`${import.meta.env.BASE_URL}wechat-qrcode.png`} alt="添加微信" />
            </div>
            <p style={{ fontSize: 13, color: "var(--text-secondary)", marginTop: 8 }}>guo968673ge</p>
            <p style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 2 }}>扫码添加微信</p>
          </div>
        </div>
        <div className="landing-container landing-footer-bottom">
          <p>© 2026 智价 AI Technology. All rights reserved.</p>
          <div className="landing-footer-legal">
            <a href="#">隐私权政策</a>
            <a href="#">服务条款</a>
          </div>
        </div>
      </footer>
    </div>
  );
}
