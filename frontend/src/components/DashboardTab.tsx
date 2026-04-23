import { useEffect, useRef, useState } from "react";
import {
  Card, Col, Progress, Row, Statistic, Timeline, Input, Tag, message,
} from "antd";
import {
  CommentOutlined, SendOutlined,
  ClockCircleOutlined, UserOutlined,
  DollarOutlined, BarChartOutlined,
} from "@ant-design/icons";
import type { AuditLog, CommentItem, DashboardSummary, HealthScore } from "../api";
import { api } from "../api";

interface Props { projectId: number }

/** Animated count-up for stat numbers */
function useCountUp(target: number, duration = 600) {
  const [val, setVal] = useState(0);
  const prev = useRef(0);
  useEffect(() => {
    if (target === prev.current) return;
    const start = prev.current;
    const diff = target - start;
    const t0 = performance.now();
    let raf = 0;
    const step = (now: number) => {
      const p = Math.min((now - t0) / duration, 1);
      const eased = 1 - Math.pow(1 - p, 3); // ease-out cubic
      setVal(Math.round(start + diff * eased));
      if (p < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    prev.current = target;
    return () => cancelAnimationFrame(raf);
  }, [target, duration]);
  return val;
}

const formatTime = (iso: string) => {
  try {
    const d = new Date(iso);
    return d.toLocaleDateString("zh-CN", { month: "short", day: "numeric" }) +
      " " + d.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
  } catch {
    return iso;
  }
};

export default function DashboardTab({ projectId }: Props) {
  const [boqCount, setBoqCount] = useState(0);
  const [unboundCount, setUnboundCount] = useState(0);
  const [dirtyCount, setDirtyCount] = useState(0);
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [comments, setComments] = useState<CommentItem[]>([]);
  const [commentText, setCommentText] = useState("");
  const [commentAuthor, setCommentAuthor] = useState(() => localStorage.getItem("userName") || "用户");
  const [aiInsight, setAiInsight] = useState<string | null>(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [health, setHealth] = useState<HealthScore | null>(null);
  const [recalcLoading, setRecalcLoading] = useState(false);

  useEffect(() => {
    api.getDashboardSummary(projectId).then((s) => {
      setSummary(s);
      setBoqCount(s.boq_count);
      setUnboundCount(s.unbound_count);
      setDirtyCount(s.dirty_count);
      // Fetch AI insight with dashboard data
      setAiLoading(true);
      api.aiAnalyze(projectId, "dashboard", {
        boq_count: s.boq_count,
        unbound_count: s.unbound_count,
        dirty_count: s.dirty_count,
        validation_total: s.validation_total,
        validation_errors: s.validation_errors,
        validation_warnings: s.validation_warnings,
      }).then((res) => {
        setAiInsight(res.insight);
      }).catch(() => {}).finally(() => setAiLoading(false));
    }).catch(() => {});
    api.listAuditLogs(projectId).then((r) => setLogs(r.slice(0, 8))).catch(() => {});
    api.listComments(projectId).then(setComments).catch(() => {});
    api.getHealthScore(projectId).then(setHealth).catch(() => {});
  }, [projectId]);

  const handleComment = async () => {
    if (!commentText.trim()) return;
    try {
      await api.addComment(projectId, commentAuthor, commentText.trim());
      setCommentText("");
      setComments(await api.listComments(projectId));
      message.success("评论已发送");
    } catch { message.error("发送失败"); }
  };

  const updateAuthor = (name: string) => {
    setCommentAuthor(name);
    localStorage.setItem("userName", name);
  };

  // Animated stat values
  const animBoq = useCountUp(boqCount);
  const animUnbound = useCountUp(unboundCount);
  const animDirty = useCountUp(dirtyCount);
  const animValidation = useCountUp(summary?.validation_total ?? 0);

  const actionLabels: Record<string, string> = {
    create_boq_item: "创建清单项",
    update_boq_item: "更新清单项",
    delete_boq_item: "删除清单项",
    bind_rule_package: "绑定规则包",
    batch_delete_boq_items: "批量删除清单",
    confirm_quota_binding: "绑定定额",
    replace_quota_binding: "替换定额",
  };

  return (
    <div>
      {/* AI Insight Card */}
      <div className="ai-insight-card">
        <div className="ai-insight-card-header">
          <div className="ai-insight-card-icon">
            <span className="material-symbols-outlined">psychology</span>
          </div>
          <span className="ai-insight-card-title">AI 项目洞察</span>
        </div>
        <div className="ai-insight-card-body">
          {aiLoading ? (
            <div>
              <div className="ai-insight-shimmer" />
              <div className="ai-insight-shimmer" />
              <div className="ai-insight-shimmer" />
            </div>
          ) : aiInsight ? (
            aiInsight
          ) : (
            <span style={{ color: "var(--text-muted)" }}>
              {boqCount === 0
                ? "项目尚无清单数据，请先导入或创建清单项。"
                : `项目包含 ${boqCount} 个清单项，${unboundCount} 个未绑定，${dirtyCount} 个待重算。配置 AI API Key 后可获取智能分析。`}
            </span>
          )}
        </div>
      </div>

      {/* Stat Cards — Row 1 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <div className="stat-card">
            <div className="stat-card-icon blue"><span className="material-symbols-outlined">description</span></div>
            <Statistic title="清单项总数" value={animBoq} />
          </div>
        </Col>
        <Col span={6}>
          <div className="stat-card">
            <div className="stat-card-icon red"><span className="material-symbols-outlined">link_off</span></div>
            <Statistic
              title="未绑定定额" value={animUnbound}
              styles={unboundCount > 0 ? { content: { color: "#ef4444" } } : undefined}
            />
          </div>
        </Col>
        <Col span={6}>
          <div className="stat-card">
            <div className="stat-card-icon orange"><span className="material-symbols-outlined">sync</span></div>
            <Statistic
              title="待重算" value={animDirty}
              styles={dirtyCount > 0 ? { content: { color: "#f59e0b" } } : undefined}
            />
          </div>
        </Col>
        <Col span={6}>
          <div className="stat-card">
            <div className="stat-card-icon purple"><span className="material-symbols-outlined">warning</span></div>
            <Statistic
              title="校验问题" value={animValidation}
              styles={(summary?.validation_errors ?? 0) > 0 ? { content: { color: "#ef4444" } } : undefined}
            />
          </div>
        </Col>
      </Row>

      {/* Health Score Section */}
      {health && (
        <div className="health-section">
          {/* Ring + Grade */}
          <div className="health-ring-card">
            <Progress
              type="dashboard"
              percent={health.overall_score}
              size={90}
              strokeColor={
                health.overall_score >= 90 ? "#22c55e" :
                health.overall_score >= 75 ? "#3b82f6" :
                health.overall_score >= 60 ? "#f59e0b" : "#ef4444"
              }
              trailColor="var(--border)"
              format={(pct: number | undefined) => <span style={{ fontSize: 22, fontWeight: 800, color: "var(--text-primary)" }}>{pct}</span>}
            />
            <div className="health-ring-label">
              <span className="material-symbols-outlined" style={{ fontSize: 16 }}>shield</span>
              健康度
              <span className={`health-grade ${health.grade}`}>{health.grade}</span>
            </div>
          </div>

          {/* Dimension Bars */}
          <div className="health-dims-card">
            {health.dimensions.map((d) => {
              const barColor = d.score >= 80 ? "green" : d.score >= 60 ? "yellow" : "red";
              const textColor = d.score >= 80 ? "#22c55e" : d.score >= 60 ? "#f59e0b" : "#ef4444";
              return (
                <div key={d.name} className="health-dim-row">
                  <span className="health-dim-name">{d.name}</span>
                  <div className="health-dim-bar-track">
                    <div className={`health-dim-bar-fill ${barColor}`} style={{ width: `${d.score}%` }} />
                  </div>
                  <span className="health-dim-score" style={{ color: textColor }}>{d.score}</span>
                  <span className="health-dim-detail" title={d.detail}>{d.detail}</span>
                </div>
              );
            })}
          </div>

          {/* Suggestions + Recalc */}
          <div className="health-actions-card">
            <div className="health-actions-title">
              <span className="material-symbols-outlined" style={{ fontSize: 16, color: "var(--primary)" }}>lightbulb</span>
              改进建议
            </div>
            {health.suggestions.length === 0 ? (
              <div className="health-ok-badge">
                <span className="material-symbols-outlined" style={{ fontSize: 16 }}>check_circle</span>
                项目状态良好
              </div>
            ) : (
              health.suggestions.map((s, i) => (
                <div key={i} className="health-suggestion">
                  <span className="health-suggestion-dot" />
                  <span>{s}</span>
                </div>
              ))
            )}
            {dirtyCount > 0 && (
              <button
                className={`recalc-btn${recalcLoading ? " loading" : ""}`}
                disabled={recalcLoading}
                onClick={async () => {
                  setRecalcLoading(true);
                  try {
                    await api.recalculateDirty(projectId);
                    message.success("增量重算完成");
                    const s = await api.getDashboardSummary(projectId);
                    setSummary(s); setBoqCount(s.boq_count); setUnboundCount(s.unbound_count); setDirtyCount(s.dirty_count);
                    const h = await api.getHealthScore(projectId);
                    setHealth(h);
                  } catch { message.error("重算失败"); }
                  setRecalcLoading(false);
                }}
              >
                <span className="material-symbols-outlined">bolt</span>
                增量重算 ({dirtyCount}项)
              </button>
            )}
          </div>
        </div>
      )}

      {/* Stat Cards — Row 2: Cost + Binding Rate + Budget + Top Divisions */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={6}>
          <div className="stat-card">
            <div className="stat-card-icon blue"><DollarOutlined style={{ fontSize: 20, color: "#1677ff" }} /></div>
            <Statistic
              title="工程总价"
              value={summary?.calc_total ?? 0}
              precision={2}
              prefix="¥"
            />
          </div>
        </Col>
        <Col span={6}>
          <div className="stat-card">
            <div className="stat-card-icon green"><span className="material-symbols-outlined">link</span></div>
            <Statistic
              title="绑定覆盖率"
              value={parseFloat(summary?.binding_rate ?? "0")}
              suffix="%"
              styles={parseFloat(summary?.binding_rate ?? "0") >= 80
                ? { content: { color: "#22c55e" } }
                : { content: { color: "#f59e0b" } }}
            />
          </div>
        </Col>
        <Col span={6}>
          <div className="stat-card">
            <div className="stat-card-icon orange"><DollarOutlined style={{ fontSize: 20, color: "#f59e0b" }} /></div>
            <Statistic
              title="项目预算"
              value={summary?.budget ?? 0}
              precision={2}
              prefix="¥"
            />
            {summary?.budget && summary.calc_total > 0 && (
              <Tag color={summary.calc_total > summary.budget ? "red" : "green"} style={{ marginTop: 4 }}>
                {summary.calc_total > summary.budget ? "超支" : "结余"}{" "}
                ¥{Math.abs(summary.calc_total - summary.budget).toLocaleString("zh-CN", { minimumFractionDigits: 2 })}
              </Tag>
            )}
          </div>
        </Col>
        <Col span={6}>
          <div className="stat-card" style={{ padding: "14px 18px" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 10, fontSize: 13, fontWeight: 600, color: "var(--text-secondary)" }}>
              <BarChartOutlined style={{ color: "var(--primary)" }} /> TOP 分部
            </div>
            {(summary?.top_divisions ?? []).length === 0 ? (
              <div style={{ color: "var(--text-muted)", fontSize: 12 }}>暂无数据</div>
            ) : (
              (summary?.top_divisions ?? []).map((d: any, i: number) => (
                <div key={d.division} style={{ display: "flex", justifyContent: "space-between", fontSize: 12, marginBottom: 4, lineHeight: 1.6 }}>
                  <span style={{ color: ["#3b82f6","#22c55e","#f59e0b","#ef4444","#8b5cf6"][i], fontWeight: 500 }}>{d.division}</span>
                  <span style={{ fontVariantNumeric: "tabular-nums" }}>¥{d.cost.toLocaleString("zh-CN")}</span>
                </div>
              ))
            )}
          </div>
        </Col>
      </Row>

      {/* Activity & Comments */}
      <Row gutter={20}>
        <Col span={12}>
          <Card
            title={
              <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <ClockCircleOutlined style={{ color: "var(--primary)" }} /> 最近操作记录
              </span>
            }
            size="small"
          >
            {logs.length === 0 ? (
              <div style={{ color: "var(--text-muted)", textAlign: "center", padding: 32 }}>
                <span className="material-symbols-outlined" style={{ fontSize: 32, display: "block", marginBottom: 8, opacity: 0.4 }}>history</span>
                暂无操作记录
              </div>
            ) : (
              <Timeline
                items={logs.map((l) => ({
                  content: (
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <Tag color="blue" style={{ margin: 0 }}>{actionLabels[l.action] ?? l.action}</Tag>
                      <span style={{ fontSize: 12, color: "var(--text-muted)" }}>{formatTime(l.timestamp)}</span>
                    </div>
                  ),
                }))}
              />
            )}
          </Card>
        </Col>
        <Col span={12}>
          <Card
            title={
              <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <CommentOutlined style={{ color: "#8b5cf6" }} /> 项目评论
              </span>
            }
            size="small"
          >
            <div style={{ maxHeight: 300, overflowY: "auto", marginBottom: 12 }}>
              {comments.length === 0 ? (
                <div style={{ color: "var(--text-muted)", textAlign: "center", padding: 24 }}>
                  <span className="material-symbols-outlined" style={{ fontSize: 32, display: "block", marginBottom: 8, opacity: 0.4 }}>chat_bubble_outline</span>
                  暂无评论
                </div>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                  {comments.map((c) => (
                    <div key={c.id} style={{ display: "flex", gap: 10, padding: "10px 0", borderBottom: "1px solid var(--border)" }}>
                      <div style={{
                        width: 32, height: 32, borderRadius: 8, flexShrink: 0,
                        background: "var(--primary)",
                        display: "flex", alignItems: "center", justifyContent: "center",
                        color: "#fff", fontSize: 14,
                      }}>
                        <UserOutlined />
                      </div>
                      <div>
                        <div style={{ fontWeight: 600, fontSize: 13 }}>{c.author}</div>
                        <div style={{ color: "var(--text-secondary)", marginTop: 2 }}>{c.content}</div>
                        <span style={{ fontSize: 11, color: "var(--text-muted)" }}>{formatTime(c.created_at)}</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
            <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 8 }}>
              <span style={{ fontSize: 12, color: "var(--text-secondary)", flexShrink: 0 }}>昵称：</span>
              <Input
                size="small"
                value={commentAuthor}
                onChange={(e) => updateAuthor(e.target.value)}
                style={{ width: 100 }}
              />
            </div>
            <Input.Search
              placeholder="输入评论..."
              enterButton={<SendOutlined />}
              value={commentText}
              onChange={(e) => setCommentText(e.target.value)}
              onSearch={handleComment}
              style={{ borderRadius: 12 }}
            />
          </Card>
        </Col>
      </Row>
    </div>
  );
}
