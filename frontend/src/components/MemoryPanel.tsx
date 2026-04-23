import { useEffect, useMemo, useState } from "react";
import {
  Button,
  Empty,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Segmented,
  Select,
  Space,
  Spin,
  Tag,
  Tooltip,
  message,
} from "antd";
import {
  DeleteOutlined,
  DatabaseOutlined,
  PlusOutlined,
  ReloadOutlined,
  SearchOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import type {
  AgentMemoryDTO,
  AgentMemoryWithScore,
  MemoryScope,
} from "../api";
import { api } from "../api";

type SearchMode = "list" | "substring" | "semantic";

interface MemoryPanelProps {
  /** Current project for scope=project queries. */
  projectId: number | null;
  /** Current user id for scope=user queries. Defaults to 1 if you don't have auth wired up. */
  userId?: number;
}

const SCOPE_OPTIONS: { label: string; value: MemoryScope }[] = [
  { label: "全局 (global)", value: "global" },
  { label: "项目 (project)", value: "project" },
  { label: "用户 (user)", value: "user" },
];

export default function MemoryPanel({ projectId, userId = 1 }: MemoryPanelProps) {
  const [scope, setScope] = useState<MemoryScope>("project");
  const [mode, setMode] = useState<SearchMode>("list");
  const [query, setQuery] = useState("");
  const [tags, setTags] = useState("");
  const [loading, setLoading] = useState(false);
  const [items, setItems] = useState<(AgentMemoryDTO | AgentMemoryWithScore)[]>([]);
  const [creating, setCreating] = useState(false);

  const scopeId = useMemo<number | null>(() => {
    if (scope === "global") return null;
    if (scope === "user") return userId;
    return projectId;
  }, [scope, userId, projectId]);

  const canQuery = scope === "global" || scopeId != null;

  const loadList = async () => {
    if (!canQuery) return;
    setLoading(true);
    try {
      const res = await api.listMemories({ scope, scope_id: scopeId, limit: 100 });
      setItems(res.memories);
    } catch (err) {
      message.error(`加载失败: ${String(err)}`);
    } finally {
      setLoading(false);
    }
  };

  const runSearch = async () => {
    if (!canQuery) return;
    if (!query.trim() && !tags.trim() && mode !== "list") {
      message.warning("请输入搜索关键词或标签");
      return;
    }
    setLoading(true);
    try {
      if (mode === "semantic") {
        const res = await api.searchMemoriesSemantic({
          scope,
          scope_id: scopeId,
          query: query.trim(),
          limit: 20,
        });
        setItems(res.matches);
      } else if (mode === "substring") {
        const res = await api.searchMemories({
          scope,
          scope_id: scopeId,
          query: query.trim() || undefined,
          tags: tags.trim() || undefined,
          limit: 50,
        });
        setItems(res.matches);
      } else {
        await loadList();
      }
    } catch (err) {
      message.error(`搜索失败: ${String(err)}`);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (mode === "list") {
      loadList();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope, scopeId, mode]);

  const handleDelete = async (id: number | null) => {
    if (id == null) return;
    try {
      await api.deleteMemory(id);
      message.success("已删除");
      setItems((prev) => prev.filter((m) => m.id !== id));
    } catch (err) {
      message.error(`删除失败: ${String(err)}`);
    }
  };

  return (
    <div className="orch-panel" style={{ padding: 20 }}>
      <div className="orch-panel-header" style={{ marginBottom: 12 }}>
        <DatabaseOutlined style={{ fontSize: 20, color: "#13c2c2" }} />
        <span className="orch-panel-title">记忆管理</span>
        <Tag color="cyan">Agent Memory</Tag>
        <div style={{ flex: 1 }} />
        <Button
          size="small"
          icon={<ReloadOutlined />}
          onClick={() => (mode === "list" ? loadList() : runSearch())}
          loading={loading}
        >
          刷新
        </Button>
        <Button
          size="small"
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => setCreating(true)}
          disabled={!canQuery}
        >
          新建
        </Button>
      </div>

      {/* Controls */}
      <Space wrap size="middle" style={{ marginBottom: 16 }}>
        <Select
          value={scope}
          onChange={(v) => setScope(v)}
          style={{ width: 180 }}
          options={SCOPE_OPTIONS}
        />
        <Segmented
          value={mode}
          onChange={(v) => setMode(v as SearchMode)}
          options={[
            { label: "列表", value: "list" },
            { label: "关键词搜索", value: "substring" },
            { label: "语义搜索", value: "semantic" },
          ]}
        />
        {mode !== "list" && (
          <>
            <Input
              placeholder={mode === "semantic" ? "语义查询..." : "子串匹配 key/content"}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onPressEnter={runSearch}
              style={{ width: 260 }}
              
            />
            {mode === "substring" && (
              <Input
                placeholder="tag1,tag2 (AND)"
                value={tags}
                onChange={(e) => setTags(e.target.value)}
                onPressEnter={runSearch}
                style={{ width: 180 }}
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

      {!canQuery && (
        <div style={{ padding: 40, textAlign: "center", color: "var(--text-muted, #94a3b8)" }}>
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={scope === "project" ? "请先选择项目" : "缺少 user_id 上下文"}
          />
        </div>
      )}

      {/* Results */}
      {canQuery && (
        <Spin spinning={loading}>
          {items.length === 0 && !loading ? (
            <div style={{ padding: 40, textAlign: "center" }}>
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无记忆" />
            </div>
          ) : (
            <div className="memory-list">
              {items.map((m) => {
                const score = (m as AgentMemoryWithScore).score;
                return (
                  <div key={(m.id ?? m.key) as React.Key} className="memory-item">
                    <div className="memory-item-body">
                      <div className="memory-item-title">
                        <Space size="small" wrap>
                          <span style={{ fontWeight: 600 }}>{m.key}</span>
                          <Tag color={scopeColor(m.scope)}>{m.scope}</Tag>
                          <Tag color="gold">重要度 {m.importance}</Tag>
                          {score != null && (
                            <Tag color="purple">score {score.toFixed(3)}</Tag>
                          )}
                          {m.tags.map((t) => (
                            <Tag key={t}>{t}</Tag>
                          ))}
                        </Space>
                      </div>
                      <div style={{ whiteSpace: "pre-wrap", marginBottom: 4, color: "var(--text-secondary, #94a3b8)" }}>
                        {m.content}
                      </div>
                      <div style={{ fontSize: 11, color: "var(--text-muted, #64748b)" }}>
                        {m.created_by_agent && `by ${m.created_by_agent} · `}
                        updated {m.updated_at?.slice(0, 19) || "—"}
                        {m.accessed_count > 0 && ` · read ${m.accessed_count}×`}
                      </div>
                    </div>
                    <Popconfirm
                      title="确定删除这条记忆？"
                      onConfirm={() => handleDelete(m.id)}
                      okText="删除"
                      cancelText="取消"
                    >
                      <Tooltip title="删除">
                        <Button type="text" danger icon={<DeleteOutlined />} />
                      </Tooltip>
                    </Popconfirm>
                  </div>
                );
              })}
            </div>
          )}
        </Spin>
      )}

      <CreateMemoryModal
        open={creating}
        scope={scope}
        scopeId={scopeId}
        onClose={() => setCreating(false)}
        onCreated={(created) => {
          setCreating(false);
          message.success("已保存");
          setItems((prev) => {
            const filtered = prev.filter(
              (m) => !(m.scope === created.scope && m.key === created.key),
            );
            return [created, ...filtered];
          });
        }}
      />
    </div>
  );
}

function scopeColor(scope: string): string {
  switch (scope) {
    case "global":
      return "geekblue";
    case "user":
      return "magenta";
    case "project":
      return "green";
    default:
      return "default";
  }
}

interface CreateModalProps {
  open: boolean;
  scope: MemoryScope;
  scopeId: number | null;
  onClose: () => void;
  onCreated: (m: AgentMemoryDTO) => void;
}

function CreateMemoryModal({ open, scope, scopeId, onClose, onCreated }: CreateModalProps) {
  const [key, setKey] = useState("");
  const [content, setContent] = useState("");
  const [importance, setImportance] = useState(3);
  const [tags, setTags] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) {
      setKey("");
      setContent("");
      setImportance(3);
      setTags("");
    }
  }, [open]);

  const handleSave = async () => {
    if (!key.trim() || !content.trim()) {
      message.warning("key 和 content 必填");
      return;
    }
    if (!/^[a-zA-Z0-9_-]{1,100}$/.test(key.trim())) {
      message.warning("key 仅支持字母/数字/下划线/连字符，1-100 字符");
      return;
    }
    setSaving(true);
    try {
      const created = await api.upsertMemory({
        scope,
        scope_id: scope === "global" ? null : scopeId,
        key: key.trim(),
        content: content.trim(),
        importance,
        tags: tags
          .split(",")
          .map((t) => t.trim())
          .filter(Boolean),
        created_by_agent: "ui",
      });
      onCreated(created);
    } catch (err) {
      message.error(`保存失败: ${String(err)}`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      open={open}
      onCancel={onClose}
      onOk={handleSave}
      confirmLoading={saving}
      title={`新建 / 更新记忆 (${scope})`}
      okText="保存"
      cancelText="取消"
    >
      <Space direction="vertical" style={{ width: "100%" }} size="middle">
        <div>
          <div style={{ marginBottom: 4, fontSize: 12 }}>Key（唯一，snake_case）</div>
          <Input
            placeholder="例如：pricing_basis / unit_pref"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            maxLength={100}
          />
        </div>
        <div>
          <div style={{ marginBottom: 4, fontSize: 12 }}>Content</div>
          <Input.TextArea
            placeholder="要长期记住的事实……"
            value={content}
            onChange={(e) => setContent(e.target.value)}
            autoSize={{ minRows: 3, maxRows: 8 }}
          />
        </div>
        <Space size="middle" wrap>
          <div>
            <div style={{ marginBottom: 4, fontSize: 12 }}>重要度 (1-5)</div>
            <InputNumber
              value={importance}
              onChange={(v) => setImportance(Math.max(1, Math.min(5, Number(v) || 3)))}
              min={1}
              max={5}
            />
          </div>
          <div style={{ flex: 1, minWidth: 200 }}>
            <div style={{ marginBottom: 4, fontSize: 12 }}>Tags（逗号分隔）</div>
            <Input
              placeholder="例如：pricing,concrete"
              value={tags}
              onChange={(e) => setTags(e.target.value)}
            />
          </div>
        </Space>
        <div style={{ fontSize: 12, color: "var(--text-muted, #94a3b8)" }}>
          scope = <strong>{scope}</strong>
          {scope !== "global" && <>, scope_id = <strong>{scopeId ?? "—"}</strong></>}
        </div>
      </Space>
    </Modal>
  );
}
