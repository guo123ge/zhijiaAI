import { useEffect, useState } from "react";
import {
  Button,
  Card,
  Drawer,
  Empty,
  Input,
  Segmented,
  Space,
  Spin,
  Tag,
  Tooltip,
  message,
} from "antd";
import {
  BookOutlined,
  ReloadOutlined,
  SearchOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import type { SkillDetail, SkillMatch, SkillSummary } from "../api";
import { api } from "../api";

type SkillMode = "all" | "keyword" | "semantic";

export default function SkillsPanel() {
  const [mode, setMode] = useState<SkillMode>("all");
  const [query, setQuery] = useState("");
  const [tags, setTags] = useState("");
  const [loading, setLoading] = useState(false);
  const [items, setItems] = useState<(SkillSummary | SkillMatch)[]>([]);
  const [detail, setDetail] = useState<SkillDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const loadAll = async () => {
    setLoading(true);
    try {
      const res = await api.listSkills();
      setItems(res.skills);
    } catch (err) {
      message.error(`加载失败: ${String(err)}`);
    } finally {
      setLoading(false);
    }
  };

  const runSearch = async () => {
    if (mode === "all") {
      await loadAll();
      return;
    }
    if (mode === "semantic" && !query.trim()) {
      message.warning("请输入语义查询");
      return;
    }
    if (mode === "keyword" && !query.trim() && !tags.trim()) {
      message.warning("请输入关键词或标签");
      return;
    }
    setLoading(true);
    try {
      if (mode === "semantic") {
        const res = await api.searchSkillsSemantic({
          query: query.trim(),
          limit: 20,
        });
        setItems(res.matches);
      } else {
        const res = await api.searchSkills({
          query: query.trim() || undefined,
          tags: tags.trim() || undefined,
        });
        setItems(res.matches);
      }
    } catch (err) {
      message.error(`搜索失败: ${String(err)}`);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (mode === "all") {
      loadAll();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode]);

  const openDetail = async (name: string) => {
    setDetailLoading(true);
    try {
      const d = await api.getSkill(name);
      setDetail(d);
    } catch (err) {
      message.error(`加载失败: ${String(err)}`);
    } finally {
      setDetailLoading(false);
    }
  };

  return (
    <div className="orch-panel" style={{ padding: 20 }}>
      <div className="orch-panel-header" style={{ marginBottom: 12 }}>
        <BookOutlined style={{ fontSize: 20, color: "#eb2f96" }} />
        <span className="orch-panel-title">领域知识库</span>
        <Tag color="magenta">Skills</Tag>
        <div style={{ flex: 1 }} />
        <Button
          size="small"
          icon={<ReloadOutlined />}
          onClick={() => (mode === "all" ? loadAll() : runSearch())}
          loading={loading}
        >
          刷新
        </Button>
      </div>

      <Space wrap size="middle" style={{ marginBottom: 16 }}>
        <Segmented
          value={mode}
          onChange={(v) => setMode(v as SkillMode)}
          options={[
            { label: "全部", value: "all" },
            { label: "关键词搜索", value: "keyword" },
            { label: "语义搜索", value: "semantic" },
          ]}
        />
        {mode !== "all" && (
          <>
            <Input
              placeholder={mode === "semantic" ? "例如：香港混凝土量度规则" : "触发词"}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onPressEnter={runSearch}
              style={{ width: 280 }}
              
            />
            {mode === "keyword" && (
              <Input
                placeholder="tag1,tag2 (AND)"
                value={tags}
                onChange={(e) => setTags(e.target.value)}
                onPressEnter={runSearch}
                style={{ width: 200 }}
              />
            )}
            <Button
              type="primary"
              icon={mode === "semantic" ? <ThunderboltOutlined /> : <SearchOutlined />}
              onClick={runSearch}
            >
              {mode === "semantic" ? "语义搜索" : "搜索"}
            </Button>
          </>
        )}
      </Space>

      <Spin spinning={loading}>
        {items.length === 0 && !loading ? (
          <div style={{ padding: 40, textAlign: "center" }}>
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="无匹配 Skill" />
          </div>
        ) : (
          <div className="skills-grid">
            {items.map((s) => {
              const score = (s as SkillMatch).score;
              return (
                <Card
                  key={s.name}
                  size="small"
                  hoverable
                  onClick={() => openDetail(s.name)}
                  title={
                    <Space size="small" wrap>
                      <span style={{ fontWeight: 600 }}>{s.title}</span>
                      <Tag color="blue">v{s.version}</Tag>
                      {score != null && <Tag color="purple">{score.toFixed(3)}</Tag>}
                    </Space>
                  }
                  extra={
                    <Tooltip title={s.name}>
                      <span style={{ fontSize: 11, color: "var(--text-muted, #94a3b8)" }}>
                        {s.name}
                      </span>
                    </Tooltip>
                  }
                >
                  <div
                    style={{
                      color: "var(--text-secondary, #94a3b8)",
                      marginBottom: 8,
                      minHeight: 36,
                    }}
                  >
                    {s.description}
                  </div>
                  <Space size={[4, 4]} wrap>
                    {s.tags.slice(0, 5).map((t) => (
                      <Tag key={t}>{t}</Tag>
                    ))}
                    {s.triggers.slice(0, 3).map((t) => (
                      <Tag key={`trig-${t}`} color="geekblue">
                        #{t}
                      </Tag>
                    ))}
                  </Space>
                </Card>
              );
            })}
          </div>
        )}
      </Spin>

      <Drawer
        open={detail != null || detailLoading}
        onClose={() => setDetail(null)}
        size="large"
        title={
          detail ? (
            <Space size="small" wrap>
              <span>{detail.title}</span>
              <Tag color="blue">v{detail.version}</Tag>
              <Tag>{detail.name}</Tag>
            </Space>
          ) : (
            "加载中..."
          )
        }
      >
        {detailLoading && !detail ? (
          <div style={{ textAlign: "center", padding: 40 }}>
            <Spin />
          </div>
        ) : detail ? (
          <div>
            <div style={{ marginBottom: 12, color: "var(--text-secondary, #94a3b8)" }}>
              {detail.description}
            </div>
            <Space size={[4, 4]} wrap style={{ marginBottom: 12 }}>
              {detail.tags.map((t) => (
                <Tag key={t}>{t}</Tag>
              ))}
              {detail.triggers.map((t) => (
                <Tag key={`trig-${t}`} color="geekblue">
                  #{t}
                </Tag>
              ))}
            </Space>
            <pre
              style={{
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
                background: "var(--bg-elevated, #1c2537)",
                padding: 16,
                borderRadius: 8,
                fontSize: 13,
                lineHeight: 1.65,
                fontFamily:
                  '"Inter", "Manrope", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
              }}
            >
              {detail.body}
            </pre>
          </div>
        ) : null}
      </Drawer>
    </div>
  );
}
