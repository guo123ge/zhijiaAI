import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { Form, Input, InputNumber, Modal, Popconfirm, Select, Spin, message } from "antd";
import type { Project, ProjectListParams } from "../api";
import { api } from "../api";

type StatusFilter = "all" | "draft" | "ongoing" | "completed" | "archived";

const TYPE_OPTIONS = ["住宅", "商业", "工业", "公共建筑", "市政"];
const STATUS_LABELS: Record<string, string> = {
  draft: "草稿", ongoing: "进行中", completed: "已完成", archived: "已归档",
};
const STATUS_ICONS: Record<string, string> = {
  draft: "edit_note", ongoing: "sync", completed: "check_circle", archived: "inventory_2",
};
const currencyFmt = new Intl.NumberFormat("zh-CN", { style: "currency", currency: "CNY", maximumFractionDigits: 0 });

export default function ProjectList() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(1);
  const [loading, setLoading] = useState(true);
  const [createOpen, setCreateOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [editingProject, setEditingProject] = useState<Project | null>(null);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [typeFilter, setTypeFilter] = useState<string>("");
  const [regionFilter, setRegionFilter] = useState<string>("");
  const [filterPanelOpen, setFilterPanelOpen] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(10);
  const [searchText, setSearchText] = useState("");
  const [sortBy, setSortBy] = useState("created_at");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("desc");
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [actionMenuId, setActionMenuId] = useState<number | null>(null);
  const actionMenuRef = useRef<HTMLDivElement>(null);
  const [createForm] = Form.useForm();
  const [editForm] = Form.useForm();
  const location = useLocation();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  useEffect(() => {
    if (location.state?.openCreate) {
      setCreateOpen(true);
      window.history.replaceState({}, "");
    }
  }, [location.state]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params: ProjectListParams = {
        page,
        page_size: pageSize,
        sort_by: sortBy,
        sort_order: sortOrder,
      };
      const q = searchText.trim() || searchParams.get("q") || "";
      if (q) params.q = q;
      if (statusFilter !== "all") params.status = statusFilter;
      if (typeFilter) params.project_type = typeFilter;
      if (regionFilter) params.region = regionFilter;
      const res = await api.listProjects(params);
      setProjects(res.items);
      setTotal(res.total);
      setTotalPages(res.total_pages);
    } catch {
      message.error("加载项目失败");
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, sortBy, sortOrder, searchText, searchParams, statusFilter, typeFilter, regionFilter]);

  useEffect(() => { load(); }, [load]);

  // Close action menu on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (actionMenuRef.current && !actionMenuRef.current.contains(e.target as Node)) {
        setActionMenuId(null);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  // Summary stats from current page data
  const summary = useMemo(() => {
    const totalBudget = projects.reduce((sum, p) => sum + (p.budget || 0), 0);
    const draftCount = projects.filter((p) => p.status === "draft").length;
    const ongoingCount = projects.filter((p) => p.status === "ongoing").length;
    const completedCount = projects.filter((p) => p.status === "completed").length;
    return { totalBudget, draftCount, ongoingCount, completedCount };
  }, [projects]);

  const pageStart = (page - 1) * pageSize;

  // ── Handlers ──
  const handleSearch = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      setPage(1);
      if (searchText.trim()) navigate(`/projects?q=${encodeURIComponent(searchText.trim())}`);
    }
  };

  const handleSort = (field: string) => {
    if (sortBy === field) {
      setSortOrder((o) => (o === "asc" ? "desc" : "asc"));
    } else {
      setSortBy(field);
      setSortOrder("asc");
    }
    setPage(1);
  };

  const sortIcon = (field: string) => {
    if (sortBy !== field) return "unfold_more";
    return sortOrder === "asc" ? "arrow_upward" : "arrow_downward";
  };

  const onCreate = async () => {
    try {
      const values = await createForm.validateFields();
      await api.createProject(values);
      message.success("项目已创建");
      setCreateOpen(false);
      createForm.resetFields();
      load();
    } catch {
      message.error("创建失败");
    }
  };

  const openEdit = (p: Project) => {
    setEditingProject(p);
    editForm.setFieldsValue({
      name: p.name,
      description: p.description,
      region: p.region,
      project_type: p.project_type,
      budget: p.budget,
      owner: p.owner,
      standard_type: p.standard_type,
      language: p.language,
      currency: p.currency,
    });
    setEditOpen(true);
    setActionMenuId(null);
  };

  const onEdit = async () => {
    if (!editingProject) return;
    try {
      const values = await editForm.validateFields();
      await api.updateProject(editingProject.id, values);
      message.success("项目已更新");
      setEditOpen(false);
      setEditingProject(null);
      editForm.resetFields();
      load();
    } catch {
      message.error("更新失败");
    }
  };

  const handleDelete = async (pid: number) => {
    try {
      await api.deleteProject(pid);
      message.success("项目已删除");
      setActionMenuId(null);
      load();
    } catch {
      message.error("删除失败");
    }
  };

  const handleArchive = async (pid: number) => {
    try {
      await api.archiveProject(pid);
      message.success("项目已归档");
      setActionMenuId(null);
      load();
    } catch {
      message.error("归档失败");
    }
  };

  const handleDuplicate = async (pid: number) => {
    try {
      await api.duplicateProject(pid);
      message.success("项目已复制");
      setActionMenuId(null);
      load();
    } catch {
      message.error("复制失败");
    }
  };

  const handleBatchArchive = async () => {
    if (selectedIds.size === 0) return;
    try {
      await api.batchArchiveProjects([...selectedIds]);
      message.success(`已归档 ${selectedIds.size} 个项目`);
      setSelectedIds(new Set());
      load();
    } catch {
      message.error("批量归档失败");
    }
  };

  const handleBatchDelete = async () => {
    if (selectedIds.size === 0) return;
    try {
      await api.batchDeleteProjects([...selectedIds]);
      message.success(`已删除 ${selectedIds.size} 个项目`);
      setSelectedIds(new Set());
      load();
    } catch {
      message.error("批量删除失败");
    }
  };

  const toggleSelect = (id: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const toggleSelectAll = () => {
    if (selectedIds.size === projects.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(projects.map((p) => p.id)));
    }
  };

  const handleExportCsv = () => {
    const header = ["ID", "名称", "类型", "地区", "状态", "预算", "负责人", "创建时间"];
    const rows = projects.map((p) => [
      p.id, p.name, p.project_type, p.region, STATUS_LABELS[p.status] || p.status,
      p.budget ?? "", p.owner ?? "", p.created_at ?? "",
    ]);
    const csv = [header, ...rows].map((r) => r.map((v) => `"${v}"`).join(",")).join("\n");
    const blob = new Blob(["\uFEFF" + csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `projects_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
    message.success("导出成功");
  };

  const handleStatusChange = (filter: StatusFilter) => {
    setStatusFilter(filter);
    setPage(1);
  };

  const clearFilters = () => {
    setTypeFilter("");
    setRegionFilter("");
    setFilterPanelOpen(false);
    setPage(1);
  };

  // ── Form shared fields (reused in create & edit) ──
  const projectFormFields = (
    <>
      <Form.Item name="name" label="项目名称" rules={[{ required: true, message: "请输入项目名称" }]}>
        <Input placeholder="例如：某住宅小区地下室工程" />
      </Form.Item>
      <Form.Item name="description" label="项目描述">
        <Input.TextArea placeholder="简要描述项目内容..." rows={2} />
      </Form.Item>
      <Form.Item name="region" label="所在地区" rules={[{ required: true, message: "请输入地区" }]} extra="用于匹配地区定额及材料价格">
        <Input placeholder="如 西安 / 北京 / 上海 / Hong Kong" />
      </Form.Item>
      <div style={{ display: "flex", gap: 12 }}>
        <Form.Item name="project_type" label="项目类型" style={{ flex: 1 }}>
          <Select>
            {TYPE_OPTIONS.map((t) => <Select.Option key={t} value={t}>{t}</Select.Option>)}
          </Select>
        </Form.Item>
        <Form.Item name="budget" label="预算 (元)" style={{ flex: 1 }}>
          <InputNumber style={{ width: "100%" }} min={0} placeholder="项目总预算" />
        </Form.Item>
      </div>
      <Form.Item name="owner" label="项目负责人">
        <Input placeholder="负责人姓名" />
      </Form.Item>
      <Form.Item name="standard_type" label="计价标准">
        <Select>
          <Select.Option value="GB50500">GB50500 (中国大陆)</Select.Option>
          <Select.Option value="HKSMM4">HKSMM4 (香港)</Select.Option>
        </Select>
      </Form.Item>
      <div style={{ display: "flex", gap: 12 }}>
        <Form.Item name="language" label="语言" style={{ flex: 1 }}>
          <Select>
            <Select.Option value="zh">中文</Select.Option>
            <Select.Option value="en">English</Select.Option>
            <Select.Option value="bilingual">双语 Bilingual</Select.Option>
          </Select>
        </Form.Item>
        <Form.Item name="currency" label="币种" style={{ flex: 1 }}>
          <Select>
            <Select.Option value="CNY">CNY ¥</Select.Option>
            <Select.Option value="HKD">HKD HK$</Select.Option>
          </Select>
        </Form.Item>
      </div>
    </>
  );

  return (
    <div className="pmc-root">
      {/* ── Page Header ── */}
      <header className="pmc-header">
        <div className="pmc-header-left">
          <h2 className="pmc-header-title">项目管理中心</h2>
          <span className="pmc-live">LIVE</span>
        </div>
        <div className="pmc-header-right">
          <div className="pmc-search">
            <span className="material-symbols-outlined">search</span>
            <input
              placeholder="搜索项目名称、地区、负责人..."
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
              onKeyDown={handleSearch}
            />
          </div>
          <button className="pmc-notify-btn">
            <span className="material-symbols-outlined">notifications</span>
            <span className="pmc-notify-dot" />
          </button>
          <button className="pmc-create-btn" onClick={() => setCreateOpen(true)}>
            <span className="material-symbols-outlined">add</span>
            新建项目
          </button>
        </div>
      </header>

      {/* ── Summary Cards ── */}
      <div className="pmc-summary-grid">
        {[
          { icon: "assignment", iconClass: "blue", label: "项目总数", value: total.toString(), trend: `${total} 个`, trendUp: true },
          { icon: "payments", iconClass: "emerald", label: "总预算规模", value: currencyFmt.format(summary.totalBudget), trend: `${summary.completedCount} 已完成`, trendUp: true },
          { icon: "engineering", iconClass: "amber", label: "进行中", value: summary.ongoingCount.toString(), trend: `${summary.draftCount} 草稿`, trendUp: true },
          { icon: "inventory_2", iconClass: "rose", label: "已完成", value: summary.completedCount.toString(), trend: `${summary.completedCount} 项`, trendUp: summary.completedCount > 0 },
        ].map((card) => (
          <div key={card.label} className="pmc-summary-card">
            <div className="pmc-summary-head">
              <span className={`pmc-summary-icon ${card.iconClass}`}>
                <span className="material-symbols-outlined">{card.icon}</span>
              </span>
              <span className={`pmc-chip ${card.trendUp ? "pmc-chip-up" : "pmc-chip-down"}`}>
                {card.trend}
                <span className="material-symbols-outlined">{card.trendUp ? "trending_up" : "trending_down"}</span>
              </span>
            </div>
            <p className="pmc-summary-label">{card.label}</p>
            <h3 className="pmc-summary-value">{card.value}</h3>
          </div>
        ))}
      </div>

      {/* ── Batch Actions Bar ── */}
      {selectedIds.size > 0 && (
        <div className="pmc-batch-bar">
          <span>已选择 {selectedIds.size} 个项目</span>
          <button className="pmc-action-btn" onClick={handleBatchArchive}>
            <span className="material-symbols-outlined">inventory_2</span>
            批量归档
          </button>
          <Popconfirm title="确认批量删除？此操作不可撤销" onConfirm={handleBatchDelete} okText="删除" cancelText="取消">
            <button className="pmc-action-btn" style={{ color: "#f87171" }}>
              <span className="material-symbols-outlined">delete</span>
              批量删除
            </button>
          </Popconfirm>
          <button className="pmc-action-btn" onClick={() => setSelectedIds(new Set())}>
            取消选择
          </button>
        </div>
      )}

      {/* ── Projects Panel ── */}
      <section className="pmc-panel">
        <div className="pmc-panel-head">
          <div className="pmc-tabs">
            {([
              { key: "all" as StatusFilter, label: "全部项目" },
              { key: "draft" as StatusFilter, label: "草稿" },
              { key: "ongoing" as StatusFilter, label: "进行中" },
              { key: "completed" as StatusFilter, label: "已完成" },
              { key: "archived" as StatusFilter, label: "已归档" },
            ]).map((tab) => (
              <button
                key={tab.key}
                className={`pmc-tab ${statusFilter === tab.key ? "active" : ""}`}
                onClick={() => handleStatusChange(tab.key)}
              >
                {tab.label}
              </button>
            ))}
          </div>
          <div className="pmc-panel-actions">
            <button className={`pmc-action-btn ${filterPanelOpen ? "active" : ""}`} onClick={() => setFilterPanelOpen(!filterPanelOpen)}>
              <span className="material-symbols-outlined">filter_list</span>
              筛选{(typeFilter || regionFilter) ? " ●" : ""}
            </button>
            <button className="pmc-action-btn" onClick={handleExportCsv}>
              <span className="material-symbols-outlined">download</span>
              导出
            </button>
          </div>
        </div>

        {/* ── Filter Panel ── */}
        {filterPanelOpen && (
          <div className="pmc-filter-panel">
            <div className="pmc-filter-row">
              <label>项目类型</label>
              <select value={typeFilter} onChange={(e) => { setTypeFilter(e.target.value); setPage(1); }}>
                <option value="">全部</option>
                {TYPE_OPTIONS.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>
            <div className="pmc-filter-row">
              <label>地区</label>
              <input placeholder="输入地区关键词..." value={regionFilter} onChange={(e) => { setRegionFilter(e.target.value); setPage(1); }} />
            </div>
            <button className="pmc-action-btn" onClick={clearFilters} style={{ marginLeft: "auto" }}>
              <span className="material-symbols-outlined">clear_all</span>
              清除筛选
            </button>
          </div>
        )}

        {/* ── Table ── */}
        <div className="pmc-table-wrap">
          {loading ? (
            <div className="pmc-loading">
              <Spin size="large" />
              <p>加载项目中...</p>
            </div>
          ) : projects.length === 0 ? (
            <div className="pmc-empty">
              <span className="material-symbols-outlined">inventory_2</span>
              <p>当前筛选下暂无项目数据</p>
              <button className="pmc-create-btn" onClick={() => setCreateOpen(true)}>
                <span className="material-symbols-outlined">add</span>
                新建项目
              </button>
            </div>
          ) : (
            <table className="pmc-table">
              <thead>
                <tr>
                  <th style={{ width: 40 }}>
                    <input type="checkbox" checked={selectedIds.size === projects.length && projects.length > 0} onChange={toggleSelectAll} />
                  </th>
                  <th onClick={() => handleSort("name")} style={{ cursor: "pointer" }}>
                    项目名称 <span className="material-symbols-outlined" style={{ fontSize: 14, verticalAlign: "middle" }}>{sortIcon("name")}</span>
                  </th>
                  <th>类型</th>
                  <th onClick={() => handleSort("budget")} style={{ cursor: "pointer" }}>
                    预算 <span className="material-symbols-outlined" style={{ fontSize: 14, verticalAlign: "middle" }}>{sortIcon("budget")}</span>
                  </th>
                  <th onClick={() => handleSort("status")} style={{ cursor: "pointer" }}>
                    状态 <span className="material-symbols-outlined" style={{ fontSize: 14, verticalAlign: "middle" }}>{sortIcon("status")}</span>
                  </th>
                  <th>负责人</th>
                  <th onClick={() => handleSort("created_at")} style={{ cursor: "pointer" }}>
                    创建时间 <span className="material-symbols-outlined" style={{ fontSize: 14, verticalAlign: "middle" }}>{sortIcon("created_at")}</span>
                  </th>
                  <th style={{ width: 80 }}></th>
                </tr>
              </thead>
              <tbody>
                {projects.map((p) => (
                  <tr key={p.id} className={selectedIds.has(p.id) ? "pmc-row-selected" : ""}>
                    <td>
                      <input type="checkbox" checked={selectedIds.has(p.id)} onChange={() => toggleSelect(p.id)} />
                    </td>
                    <td>
                      <div className="pmc-project-name-cell">
                        <strong>{p.name}</strong>
                        <span>ID: PRJ-{p.id.toString().padStart(4, "0")} · {p.region}</span>
                      </div>
                    </td>
                    <td>
                      <span className={`pmc-type-badge ${p.project_type}`}>{p.project_type}</span>
                    </td>
                    <td>
                      <span className="pmc-budget">{p.budget != null ? currencyFmt.format(p.budget) : "—"}</span>
                    </td>
                    <td>
                      <span className={`pmc-status pmc-status-${p.status}`}>
                        <span className="material-symbols-outlined">{STATUS_ICONS[p.status] || "help"}</span>
                        {STATUS_LABELS[p.status] || p.status}
                      </span>
                    </td>
                    <td>{p.owner || "—"}</td>
                    <td style={{ fontSize: 12, color: "var(--text-muted)" }}>
                      {p.created_at ? new Date(p.created_at).toLocaleDateString("zh-CN") : "—"}
                    </td>
                    <td>
                      <div style={{ display: "flex", gap: 4, position: "relative" }}>
                        <Link to={`/projects/${p.id}`} className="pmc-link-btn" title="查看详情">
                          <span className="material-symbols-outlined">arrow_forward</span>
                        </Link>
                        <button
                          className="pmc-link-btn"
                          title="更多操作"
                          onClick={(e) => { e.stopPropagation(); setActionMenuId(actionMenuId === p.id ? null : p.id); }}
                        >
                          <span className="material-symbols-outlined">more_vert</span>
                        </button>
                        {actionMenuId === p.id && (
                          <div className="pmc-action-menu" ref={actionMenuRef}>
                            <button onClick={() => openEdit(p)}>
                              <span className="material-symbols-outlined">edit</span>编辑
                            </button>
                            <button onClick={() => handleDuplicate(p.id)}>
                              <span className="material-symbols-outlined">content_copy</span>复制
                            </button>
                            {p.status !== "archived" && (
                              <button onClick={() => handleArchive(p.id)}>
                                <span className="material-symbols-outlined">inventory_2</span>归档
                              </button>
                            )}
                            <Popconfirm
                              title="确认删除此项目？"
                              description="此操作不可撤销，项目所有数据将被永久删除"
                              onConfirm={() => handleDelete(p.id)}
                              okText="删除"
                              cancelText="取消"
                              okButtonProps={{ danger: true }}
                            >
                              <button style={{ color: "#f87171" }}>
                                <span className="material-symbols-outlined">delete</span>删除
                              </button>
                            </Popconfirm>
                          </div>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* ── Pagination ── */}
        {!loading && total > 0 && (
          <div className="pmc-pagination">
            <span className="pmc-pagination-info">
              显示 {pageStart + 1}-{Math.min(pageStart + pageSize, total)} / {total} 个项目
            </span>
            <div className="pmc-pagination-actions">
              <button className="pmc-page-btn" disabled={page <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))}>
                <span className="material-symbols-outlined">chevron_left</span>
              </button>
              {Array.from({ length: Math.min(totalPages, 5) }, (_, i) => {
                const start = Math.max(1, Math.min(page - 2, totalPages - 4));
                return start + i;
              }).filter((n) => n >= 1 && n <= totalPages).map((n) => (
                <button key={n} className={`pmc-page-btn ${page === n ? "active" : ""}`} onClick={() => setPage(n)}>
                  {n}
                </button>
              ))}
              <button className="pmc-page-btn" disabled={page >= totalPages} onClick={() => setPage((p) => Math.min(totalPages, p + 1))}>
                <span className="material-symbols-outlined">chevron_right</span>
              </button>
            </div>
          </div>
        )}
      </section>

      {/* ── Create Modal ── */}
      <Modal
        title={
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <div className="pmc-modal-icon">
              <span className="material-symbols-outlined" style={{ fontSize: 18 }}>add_business</span>
            </div>
            <span>新建项目</span>
          </div>
        }
        open={createOpen}
        onOk={onCreate}
        onCancel={() => { setCreateOpen(false); createForm.resetFields(); }}
        okText="创建项目"
        width={520}
      >
        <Form form={createForm} layout="vertical" style={{ marginTop: 20 }} initialValues={{ project_type: "住宅", standard_type: "GB50500", language: "zh", currency: "CNY" }}>
          {projectFormFields}
        </Form>
      </Modal>

      {/* ── Edit Modal ── */}
      <Modal
        title={
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <div className="pmc-modal-icon">
              <span className="material-symbols-outlined" style={{ fontSize: 18 }}>edit</span>
            </div>
            <span>编辑项目</span>
          </div>
        }
        open={editOpen}
        onOk={onEdit}
        onCancel={() => { setEditOpen(false); setEditingProject(null); editForm.resetFields(); }}
        okText="保存修改"
        width={520}
      >
        <Form form={editForm} layout="vertical" style={{ marginTop: 20 }}>
          {projectFormFields}
        </Form>
      </Modal>
    </div>
  );
}
