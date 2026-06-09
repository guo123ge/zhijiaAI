import { useEffect, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { App as AntApp, ConfigProvider, Modal, theme } from "antd";
import zhCN from "antd/locale/zh_CN";
import LandingPage from "./pages/LandingPage";
import Dashboard from "./pages/Dashboard";
import ProjectList from "./pages/ProjectList";
import ProjectDetail from "./pages/ProjectDetail";
import PricingManagement from "./pages/PricingManagement";
import SystemSettings from "./pages/SystemSettings";
import ReportsPage from "./pages/ReportsPage";
import RuleConfig from "./pages/RuleConfig";
import UnitPriceAnalysis from "./pages/UnitPriceAnalysis";
import DrawingRecognition from "./pages/DrawingRecognition";
import AuditWorkbench from "./pages/AuditWorkbench";
import ContactUs from "./pages/ContactUs";
import KnowledgeGraph from "./pages/KnowledgeGraph";
import AICommandCenter from "./pages/AICommandCenter";
import QuotaLibrary from "./pages/QuotaLibrary";
import { AUTH_CHANGED_EVENT, clearAuthSession, hasActiveTrial } from "./auth";

const NAV_ITEMS = [
  { path: "/", icon: "home", label: "首页" },
  { path: "/dashboard", icon: "dashboard", label: "仪表盘" },
  { path: "/projects", icon: "analytics", label: "项目管理" },
  { path: "/drawings", icon: "draw", label: "图纸库" },
  { path: "/pricing", icon: "calculate", label: "计价管理" },
  { path: "/quota-library", icon: "library_books", label: "定额库" },
  { path: "/reports", icon: "description", label: "报表中心" },
  { path: "/rules", icon: "rule", label: "规则配置" },
  { path: "/graph", icon: "hub", label: "数据图谱" },
  { path: "/ai-center", icon: "smart_toy", label: "AI 调度" },
  { path: "/audits", icon: "contract", label: "审计管理" },
  { path: "/contact", icon: "connect_without_contact", label: "联系我们" },
  { path: "/settings", icon: "settings", label: "系统设置" },
];

function AppSidebar() {
  const navigate = useNavigate();
  const location = useLocation();
  const [contactOpen, setContactOpen] = useState(false);

  return (
    <aside className="app-sidebar">
      <div className="app-sidebar-top">
        {/* Brand */}
        <a
          href="/projects"
          className="app-sidebar-brand"
          onClick={(e) => { e.preventDefault(); navigate("/projects"); }}
        >
          <div className="app-sidebar-brand-icon">
            <span className="material-symbols-outlined">architecture</span>
          </div>
          <div className="app-sidebar-brand-text">
            <h1>智价 AI</h1>
            <p>Cost Management System</p>
          </div>
        </a>
        {/* Nav */}
        <nav className="app-sidebar-nav">
          {NAV_ITEMS.map((item) => {
            const active = item.path === "/" ? location.pathname === "/" : location.pathname.startsWith(item.path);
            return (
              <a
                key={item.path}
                href={item.path}
                className={`app-sidebar-link${active ? " active" : ""}`}
                onClick={(e) => { e.preventDefault(); navigate(item.path); }}
              >
                <span className="material-symbols-outlined">{item.icon}</span>
                <span>{item.label}</span>
              </a>
            );
          })}
        </nav>
      </div>
      {/* Contact author */}
      <div className="app-sidebar-contact">
        <button className="app-sidebar-contact-btn" onClick={() => setContactOpen(true)}>
          <span className="material-symbols-outlined">qr_code_2</span>
          <span>添加微信</span>
        </button>
      </div>
      {/* User profile */}
      <div className="app-sidebar-footer">
        <div className="app-sidebar-user">
          <div className="app-sidebar-avatar">G</div>
          <div className="app-sidebar-user-info">
            <p className="app-sidebar-user-name">guoguo</p>
            <p className="app-sidebar-user-role">项目经理</p>
          </div>
          <span className="material-symbols-outlined app-sidebar-more">more_vert</span>
        </div>
      </div>
      <Modal
        open={contactOpen}
        onCancel={() => setContactOpen(false)}
        footer={null}
        centered
        width={360}
        title={null}
        className="contact-modal"
      >
        <div className="contact-modal-body">
          <img src={`${import.meta.env.BASE_URL}wechat-qrcode.png`} alt="联系作者" className="contact-qrcode" />
          <h3>添加微信</h3>
          <p>微信号：guo968673ge</p>
          <p style={{ marginTop: 4 }}>扫描二维码，与我取得联系</p>
        </div>
      </Modal>
    </aside>
  );
}

function ProtectedAppShell() {
  const [allowed, setAllowed] = useState(() => hasActiveTrial());

  useEffect(() => {
    const refresh = () => setAllowed(hasActiveTrial());
    window.addEventListener(AUTH_CHANGED_EVENT, refresh);
    return () => window.removeEventListener(AUTH_CHANGED_EVENT, refresh);
  }, []);

  if (!allowed) {
    clearAuthSession();
    return <Navigate to="/?activate=1" replace />;
  }

  return (
    <div className="app-layout">
      <AppSidebar />
      <main className="app-main">
        <Routes>
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/projects" element={<ProjectList />} />
          <Route path="/projects/:id" element={<ProjectDetail />} />
          <Route path="/pricing" element={<PricingManagement />} />
          <Route path="/quota-library" element={<QuotaLibrary />} />
          <Route path="/pricing/analysis/:projectId/:boqItemId" element={<UnitPriceAnalysis />} />
          <Route path="/drawings" element={<DrawingRecognition />} />
          <Route path="/drawings/:projectId" element={<DrawingRecognition />} />
          <Route path="/reports" element={<ReportsPage />} />
          <Route path="/rules" element={<RuleConfig />} />
          <Route path="/graph" element={<KnowledgeGraph />} />
          <Route path="/ai-center" element={<AICommandCenter />} />
          <Route path="/audits" element={<AuditWorkbench />} />
          <Route path="/contact" element={<ContactUs />} />
          <Route path="/settings" element={<div className="page-container"><SystemSettings /></div>} />
          <Route path="*" element={<Navigate to="/dashboard" replace />} />
        </Routes>
      </main>
    </div>
  );
}

export default function App() {
  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        algorithm: theme.darkAlgorithm,
        token: {
          colorPrimary: "#1456b8",
          borderRadius: 8,
          fontFamily: '"Inter", "Manrope", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
          colorBgContainer: "#151b28",
          colorBgElevated: "#1c2537",
          colorBorder: "#1e293b",
          colorText: "#e2e8f0",
          colorTextSecondary: "#94a3b8",
          colorBgLayout: "#0c1017",
          controlHeight: 36,
          colorBgTextHover: "rgba(64, 150, 255, 0.06)",
          colorBgTextActive: "rgba(64, 150, 255, 0.1)",
        },
        components: {
          Card: {
            colorBgContainer: "#151b28",
            colorBorderSecondary: "#1e293b",
          },
          Input: {
            colorBgContainer: "#0f1520",
            activeBorderColor: "#4096ff",
            hoverBorderColor: "rgba(64, 150, 255, 0.35)",
          },
          Select: {
            colorBgContainer: "#0f1520",
          },
          Table: {
            colorBgContainer: "#151b28",
            headerBg: "rgba(30, 41, 59, 0.5)",
            rowHoverBg: "rgba(20, 86, 184, 0.06)",
          },
          Modal: {
            contentBg: "#1c2537",
            headerBg: "#1c2537",
          },
          Drawer: {
            colorBgElevated: "#1c2537",
          },
          Collapse: {
            colorBgContainer: "#151b28",
            headerBg: "rgba(30, 41, 59, 0.3)",
          },
          Tag: {
            borderRadiusSM: 4,
          },
        },
      }}
    >
      <AntApp>
        <BrowserRouter basename={import.meta.env.BASE_URL.replace(/\/$/, '')}>
          <Routes>
            {/* Landing page — no sidebar */}
            <Route path="/" element={<LandingPage />} />

            {/* App shell — sidebar + main */}
            <Route path="/*" element={<ProtectedAppShell />} />
          </Routes>
        </BrowserRouter>
      </AntApp>
    </ConfigProvider>
  );
}
