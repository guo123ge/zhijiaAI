import { useCallback, useEffect, useRef, useState } from "react";
import { Select, Input, Slider, Drawer, Tag, Button, Empty, Spin, message, Popconfirm, Modal, Form, ColorPicker } from "antd";
import * as d3 from "d3";
import { api } from "../api";
import type {
  GraphNode,
  GraphDataOut,
  TagOut,
  KnowledgeNoteOut,
  KnowledgeLinkOut,
  Project,
} from "../api";

// ─── Constants ───────────────────────────────────────────────────

const NODE_COLORS: Record<string, string> = {
  project: "#3b82f6",
  boq_item: "#10b981",
  quota_item: "#f59e0b",
  material_price: "#ef4444",
  rule_package: "#8b5cf6",
  tag: "#ec4899",
};

const NODE_ICONS: Record<string, string> = {
  project: "apartment",
  boq_item: "receipt_long",
  quota_item: "functions",
  material_price: "payments",
  rule_package: "gavel",
  tag: "label",
};

const NODE_LABELS_ZH: Record<string, string> = {
  project: "项目",
  boq_item: "清单项",
  quota_item: "定额",
  material_price: "材料价格",
  rule_package: "规则包",
  tag: "标签",
};

const EDGE_STYLES: Record<string, { color: string; dash: string }> = {
  fk: { color: "#475569", dash: "" },
  binding: { color: "#3b82f6", dash: "" },
  resource: { color: "#ef4444", dash: "" },
  tag: { color: "#ec4899", dash: "4,3" },
  knowledge_link: { color: "#f59e0b", dash: "6,3" },
};

const LINK_TYPES = [
  { value: "similar", label: "类似项" },
  { value: "alternative", label: "替代方案" },
  { value: "derived_from", label: "派生自" },
  { value: "compare", label: "对比" },
  { value: "related", label: "相关" },
];

// ─── D3 Simulation Types ─────────────────────────────────────────

interface SimNode extends d3.SimulationNodeDatum {
  id: string;
  type: string;
  label: string;
  properties: Record<string, unknown>;
  tags: string[];
  radius: number;
}

interface SimLink extends d3.SimulationLinkDatum<SimNode> {
  type: string;
  label: string;
}

// ─── Component ───────────────────────────────────────────────────

export default function KnowledgeGraph() {
  const svgRef = useRef<SVGSVGElement>(null);
  const simRef = useRef<d3.Simulation<SimNode, SimLink> | null>(null);

  const [graphData, setGraphData] = useState<GraphDataOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [projects, setProjects] = useState<Project[]>([]);
  const [allTags, setAllTags] = useState<TagOut[]>([]);

  // Filters
  const [scopeProject, setScopeProject] = useState<number | undefined>(undefined);
  const [depth, setDepth] = useState(2);
  const [typeFilter, setTypeFilter] = useState<string[]>([]);
  const [searchText, setSearchText] = useState("");

  // Detail drawer
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [nodeNotes, setNodeNotes] = useState<KnowledgeNoteOut[]>([]);
  const [nodeLinks, setNodeLinks] = useState<KnowledgeLinkOut[]>([]);

  // Create tag modal
  const [tagModalOpen, setTagModalOpen] = useState(false);
  const [newTagName, setNewTagName] = useState("");
  const [newTagColor, setNewTagColor] = useState("#3b82f6");
  const [newTagCategory, setNewTagCategory] = useState("");

  // Create link modal
  const [linkModalOpen, setLinkModalOpen] = useState(false);
  const [linkForm] = Form.useForm();

  // ── Data fetching ──────────────────────────────────────────────

  const fetchGraph = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, unknown> = { depth };
      if (scopeProject) {
        params.scope = "project";
        params.project_id = scopeProject;
      }
      if (typeFilter.length > 0) {
        params.types = typeFilter.join(",");
      }
      const data = await api.getGraphData(params as Parameters<typeof api.getGraphData>[0]);
      setGraphData(data);
    } catch (e) {
      console.error("Failed to fetch graph data:", e);
      message.error("加载图谱数据失败");
    } finally {
      setLoading(false);
    }
  }, [scopeProject, depth, typeFilter]);

  useEffect(() => {
    api.listProjects().then((res) => setProjects(res.items)).catch(() => {});
    api.listTags().then(setAllTags).catch(() => {});
    fetchGraph();
  }, [fetchGraph]);

  // ── D3 rendering ───────────────────────────────────────────────

  useEffect(() => {
    if (!graphData || !svgRef.current) return;

    const svg = d3.select(svgRef.current);
    const width = svgRef.current.clientWidth || 1200;
    const height = svgRef.current.clientHeight || 800;

    svg.selectAll("*").remove();

    // Filter by search
    let filteredNodes = graphData.nodes;
    if (searchText.trim()) {
      const lower = searchText.toLowerCase();
      const matchIds = new Set(
        graphData.nodes
          .filter((n) => n.label.toLowerCase().includes(lower) || n.type.includes(lower))
          .map((n) => n.id)
      );
      filteredNodes = graphData.nodes.filter((n) => matchIds.has(n.id));
    }

    const nodeIds = new Set(filteredNodes.map((n) => n.id));
    const filteredEdges = graphData.edges.filter(
      (e) => nodeIds.has(e.source) && nodeIds.has(e.target)
    );

    if (filteredNodes.length === 0) return;

    // Build sim data
    const simNodes: SimNode[] = filteredNodes.map((n) => ({
      ...n,
      radius: n.type === "project" ? 28 : n.type === "tag" ? 16 : 20,
    }));

    const nodeMap = new Map(simNodes.map((n) => [n.id, n]));

    const simLinks: SimLink[] = filteredEdges
      .filter((e) => nodeMap.has(e.source) && nodeMap.has(e.target))
      .map((e) => ({
        source: e.source,
        target: e.target,
        type: e.type,
        label: e.label,
      }));

    // Container group with zoom
    const g = svg.append("g");
    const zoom = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.1, 4])
      .on("zoom", (event) => g.attr("transform", event.transform));
    svg.call(zoom);

    // Arrow markers
    const defs = svg.append("defs");
    Object.entries(EDGE_STYLES).forEach(([key, style]) => {
      defs.append("marker")
        .attr("id", `arrow-${key}`)
        .attr("viewBox", "0 0 10 6")
        .attr("refX", 28)
        .attr("refY", 3)
        .attr("markerWidth", 8)
        .attr("markerHeight", 6)
        .attr("orient", "auto")
        .append("path")
        .attr("d", "M0,0L10,3L0,6Z")
        .attr("fill", style.color);
    });

    // Links
    const linkG = g.append("g").attr("class", "links");
    const link = linkG
      .selectAll("line")
      .data(simLinks)
      .join("line")
      .attr("stroke", (d) => EDGE_STYLES[d.type]?.color ?? "#475569")
      .attr("stroke-width", 1.5)
      .attr("stroke-dasharray", (d) => EDGE_STYLES[d.type]?.dash ?? "")
      .attr("stroke-opacity", 0.6)
      .attr("marker-end", (d) => `url(#arrow-${d.type})`);

    // Link labels
    const linkLabelG = g.append("g").attr("class", "link-labels");
    const linkLabel = linkLabelG
      .selectAll("text")
      .data(simLinks.filter((l) => l.label))
      .join("text")
      .text((d) => d.label)
      .attr("font-size", 10)
      .attr("fill", "#94a3b8")
      .attr("text-anchor", "middle")
      .attr("dy", -4);

    // Nodes
    const nodeG = g.append("g").attr("class", "nodes");
    const node = nodeG
      .selectAll<SVGGElement, SimNode>("g")
      .data(simNodes)
      .join("g")
      .attr("cursor", "pointer")
      .call(
        d3.drag<SVGGElement, SimNode>()
          .on("start", (event, d) => {
            if (!event.active) sim.alphaTarget(0.3).restart();
            d.fx = d.x;
            d.fy = d.y;
          })
          .on("drag", (event, d) => {
            d.fx = event.x;
            d.fy = event.y;
          })
          .on("end", (event, d) => {
            if (!event.active) sim.alphaTarget(0);
            d.fx = null;
            d.fy = null;
          })
      );

    // Node circles
    node
      .append("circle")
      .attr("r", (d) => d.radius)
      .attr("fill", (d) => NODE_COLORS[d.type] ?? "#64748b")
      .attr("fill-opacity", 0.15)
      .attr("stroke", (d) => NODE_COLORS[d.type] ?? "#64748b")
      .attr("stroke-width", 2);

    // Node icon (Material Symbols text)
    node
      .append("text")
      .attr("text-anchor", "middle")
      .attr("dominant-baseline", "central")
      .attr("font-family", "Material Symbols Outlined")
      .attr("font-size", (d) => (d.type === "project" ? 20 : 16))
      .attr("fill", (d) => NODE_COLORS[d.type] ?? "#64748b")
      .text((d) => NODE_ICONS[d.type] ?? "circle");

    // Node label
    node
      .append("text")
      .attr("text-anchor", "middle")
      .attr("dy", (d) => d.radius + 14)
      .attr("font-size", 11)
      .attr("fill", "#cbd5e1")
      .attr("pointer-events", "none")
      .text((d) => (d.label.length > 16 ? d.label.slice(0, 15) + "..." : d.label));

    // Click → detail drawer
    node.on("click", (_event, d) => {
      const original = graphData.nodes.find((n) => n.id === d.id);
      if (original) {
        setSelectedNode(original);
        setDrawerOpen(true);
        loadNodeDetails(original);
      }
    });

    // Hover highlight
    node
      .on("mouseenter", function (_event, d) {
        const connected = new Set<string>();
        simLinks.forEach((l) => {
          const src = typeof l.source === "object" ? (l.source as SimNode).id : String(l.source);
          const tgt = typeof l.target === "object" ? (l.target as SimNode).id : String(l.target);
          if (src === d.id) connected.add(tgt);
          if (tgt === d.id) connected.add(src);
        });
        connected.add(d.id);
        node.attr("opacity", (n) => (connected.has(n.id) ? 1 : 0.15));
        link.attr("stroke-opacity", (l) => {
          const src = typeof l.source === "object" ? (l.source as SimNode).id : String(l.source);
          const tgt = typeof l.target === "object" ? (l.target as SimNode).id : String(l.target);
          return src === d.id || tgt === d.id ? 0.9 : 0.05;
        });
      })
      .on("mouseleave", () => {
        node.attr("opacity", 1);
        link.attr("stroke-opacity", 0.6);
      });

    // Simulation
    const sim = d3
      .forceSimulation(simNodes)
      .force(
        "link",
        d3.forceLink<SimNode, SimLink>(simLinks).id((d) => d.id).distance(120)
      )
      .force("charge", d3.forceManyBody().strength(-300))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force("collide", d3.forceCollide<SimNode>().radius((d) => d.radius + 10))
      .on("tick", () => {
        link
          .attr("x1", (d) => (d.source as SimNode).x!)
          .attr("y1", (d) => (d.source as SimNode).y!)
          .attr("x2", (d) => (d.target as SimNode).x!)
          .attr("y2", (d) => (d.target as SimNode).y!);

        linkLabel
          .attr("x", (d) => ((d.source as SimNode).x! + (d.target as SimNode).x!) / 2)
          .attr("y", (d) => ((d.source as SimNode).y! + (d.target as SimNode).y!) / 2);

        node.attr("transform", (d) => `translate(${d.x},${d.y})`);
      });

    simRef.current = sim;

    // Initial zoom to fit
    setTimeout(() => {
      const bounds = g.node()?.getBBox();
      if (bounds && bounds.width > 0) {
        const pad = 60;
        const scale = Math.min(
          (width - pad * 2) / bounds.width,
          (height - pad * 2) / bounds.height,
          1.5
        );
        const tx = width / 2 - (bounds.x + bounds.width / 2) * scale;
        const ty = height / 2 - (bounds.y + bounds.height / 2) * scale;
        svg.transition().duration(500).call(
          zoom.transform,
          d3.zoomIdentity.translate(tx, ty).scale(scale)
        );
      }
    }, 800);

    return () => {
      sim.stop();
    };
  }, [graphData, searchText]);

  // ── Node detail loading ────────────────────────────────────────

  const loadNodeDetails = async (node: GraphNode) => {
    const [type, idStr] = node.id.split(":");
    const id = parseInt(idStr);
    try {
      const [notes, links] = await Promise.all([
        api.listKnowledgeNotes({ entity_type: type, entity_id: id }),
        api.listKnowledgeLinks({ entity_type: type, entity_id: id }),
      ]);
      setNodeNotes(notes);
      setNodeLinks(links);
    } catch {
      setNodeNotes([]);
      setNodeLinks([]);
    }
  };

  // ── Tag operations ─────────────────────────────────────────────

  const handleCreateTag = async () => {
    if (!newTagName.trim()) return;
    try {
      const tag = await api.createTag({ name: newTagName, color: newTagColor, category: newTagCategory });
      setAllTags((prev) => [...prev, tag]);
      setTagModalOpen(false);
      setNewTagName("");
      message.success("标签创建成功");
    } catch {
      message.error("标签创建失败");
    }
  };

  const handleAttachTag = async (tagId: number) => {
    if (!selectedNode) return;
    const [type, idStr] = selectedNode.id.split(":");
    try {
      await api.attachTag({ tag_id: tagId, entity_type: type, entity_id: parseInt(idStr) });
      message.success("标签已关联");
      fetchGraph();
    } catch {
      message.error("关联失败");
    }
  };

  // ── Link operations ────────────────────────────────────────────

  const handleCreateLink = async (values: { target_node: string; link_type: string; label: string }) => {
    if (!selectedNode) return;
    const [srcType, srcIdStr] = selectedNode.id.split(":");
    const [tgtType, tgtIdStr] = values.target_node.split(":");
    try {
      await api.createKnowledgeLink({
        source_type: srcType,
        source_id: parseInt(String(srcIdStr)),
        target_type: tgtType,
        target_id: parseInt(String(tgtIdStr)),
        link_type: values.link_type,
        label: values.label || "",
      });
      message.success("关联创建成功");
      setLinkModalOpen(false);
      linkForm.resetFields();
      fetchGraph();
      if (selectedNode) loadNodeDetails(selectedNode);
    } catch {
      message.error("创建关联失败");
    }
  };

  const handleDeleteLink = async (linkId: number) => {
    try {
      await api.deleteKnowledgeLink(linkId);
      message.success("关联已删除");
      if (selectedNode) loadNodeDetails(selectedNode);
      fetchGraph();
    } catch {
      message.error("删除失败");
    }
  };

  // ── Render ─────────────────────────────────────────────────────

  const nodeTypeOptions = Object.entries(NODE_LABELS_ZH).map(([k, v]) => ({ value: k, label: v }));

  return (
    <div className="kg-page">
      {/* Toolbar */}
      <div className="kg-toolbar">
        <div className="kg-toolbar-left">
          <span className="material-symbols-outlined" style={{ fontSize: 22, color: "#3b82f6" }}>hub</span>
          <h2>造价数据图谱</h2>
        </div>
        <div className="kg-toolbar-filters">
          <Select
            allowClear
            placeholder="筛选项目"
            style={{ width: 180 }}
            value={scopeProject}
            onChange={setScopeProject}
            options={projects.map((p) => ({ value: p.id, label: p.name }))}
          />
          <Select
            mode="multiple"
            allowClear
            placeholder="节点类型"
            style={{ width: 220 }}
            value={typeFilter}
            onChange={setTypeFilter}
            options={nodeTypeOptions}
          />
          <div className="kg-depth-control">
            <span>深度:</span>
            <Slider
              min={1}
              max={3}
              value={depth}
              onChange={setDepth}
              style={{ width: 80 }}
              tooltip={{ formatter: (v) => `${v}层` }}
            />
          </div>
          <Input.Search
            placeholder="搜索节点..."
            allowClear
            style={{ width: 200 }}
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
          />
          <Button onClick={() => setTagModalOpen(true)} icon={<span className="material-symbols-outlined" style={{ fontSize: 16 }}>new_label</span>}>
            新建标签
          </Button>
        </div>
      </div>

      {/* Legend */}
      <div className="kg-legend">
        {Object.entries(NODE_LABELS_ZH).map(([type, label]) => (
          <span key={type} className="kg-legend-item">
            <span className="kg-legend-dot" style={{ background: NODE_COLORS[type] }} />
            {label}
          </span>
        ))}
        <span className="kg-legend-divider" />
        <span className="kg-legend-item"><span className="kg-legend-line solid" /> FK关系</span>
        <span className="kg-legend-item"><span className="kg-legend-line dashed" /> 知识关联</span>
        <span className="kg-legend-item"><span className="kg-legend-line dotted" /> 标签</span>
      </div>

      {/* Graph Canvas */}
      <div className="kg-canvas-wrapper">
        {loading ? (
          <div className="kg-loading"><Spin size="large" description="加载图谱数据..." /></div>
        ) : graphData && graphData.nodes.length === 0 ? (
          <div className="kg-empty"><Empty description="暂无图谱数据，请先创建项目和清单" /></div>
        ) : (
          <svg ref={svgRef} className="kg-canvas" />
        )}
      </div>

      {/* Stats bar */}
      {graphData && (
        <div className="kg-stats">
          <span>节点: {graphData.nodes.length}</span>
          <span>关系: {graphData.edges.length}</span>
          {scopeProject && <span>项目范围</span>}
        </div>
      )}

      {/* Detail Drawer */}
      <Drawer
        title={selectedNode ? selectedNode.label : "节点详情"}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        width={420}
        className="kg-drawer"
      >
        {selectedNode && (
          <div className="kg-detail">
            {/* Type badge */}
            <div className="kg-detail-type">
              <span
                className="kg-type-badge"
                style={{ background: NODE_COLORS[selectedNode.type] + "22", color: NODE_COLORS[selectedNode.type], borderColor: NODE_COLORS[selectedNode.type] }}
              >
                <span className="material-symbols-outlined" style={{ fontSize: 14 }}>
                  {NODE_ICONS[selectedNode.type]}
                </span>
                {NODE_LABELS_ZH[selectedNode.type] || selectedNode.type}
              </span>
              <span className="kg-detail-id">{selectedNode.id}</span>
            </div>

            {/* Properties */}
            <div className="kg-detail-section">
              <h4>属性</h4>
              <div className="kg-props">
                {Object.entries(selectedNode.properties).map(([k, v]) => (
                  <div key={k} className="kg-prop-row">
                    <span className="kg-prop-key">{k}</span>
                    <span className="kg-prop-val">{String(v)}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Tags */}
            <div className="kg-detail-section">
              <h4>
                标签
                <Select
                  size="small"
                  placeholder="+ 添加标签"
                  style={{ marginLeft: 8, width: 140 }}
                  value={undefined}
                  onChange={handleAttachTag}
                  options={allTags.map((t) => ({ value: t.id, label: t.name }))}
                />
              </h4>
              <div className="kg-tags">
                {selectedNode.tags.length > 0
                  ? selectedNode.tags.map((t) => (
                      <Tag key={t} color="blue">{t}</Tag>
                    ))
                  : <span className="kg-empty-hint">无标签</span>}
              </div>
            </div>

            {/* Knowledge Links */}
            <div className="kg-detail-section">
              <h4>
                知识关联
                <Button size="small" type="link" onClick={() => setLinkModalOpen(true)}>
                  + 新建
                </Button>
              </h4>
              {nodeLinks.length > 0 ? (
                <div className="kg-links-list">
                  {nodeLinks.map((lk) => (
                    <div key={lk.id} className="kg-link-item">
                      <span className="kg-link-type">{lk.link_type}</span>
                      <span className="kg-link-target">
                        {lk.source_type}:{lk.source_id} → {lk.target_type}:{lk.target_id}
                      </span>
                      {lk.label && <span className="kg-link-label">{lk.label}</span>}
                      <Popconfirm title="确认删除?" onConfirm={() => handleDeleteLink(lk.id)}>
                        <Button size="small" type="text" danger>
                          <span className="material-symbols-outlined" style={{ fontSize: 14 }}>delete</span>
                        </Button>
                      </Popconfirm>
                    </div>
                  ))}
                </div>
              ) : (
                <span className="kg-empty-hint">无知识关联</span>
              )}
            </div>

            {/* Notes */}
            <div className="kg-detail-section">
              <h4>知识笔记</h4>
              {nodeNotes.length > 0 ? (
                <div className="kg-notes-list">
                  {nodeNotes.map((n) => (
                    <div key={n.id} className="kg-note-item">
                      <strong>{n.title || "无标题"}</strong>
                      <p>{n.content.slice(0, 200)}{n.content.length > 200 ? "..." : ""}</p>
                      <span className="kg-note-time">{n.updated_at.slice(0, 10)}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <span className="kg-empty-hint">无笔记</span>
              )}
            </div>
          </div>
        )}
      </Drawer>

      {/* Create Tag Modal */}
      <Modal
        title="新建标签"
        open={tagModalOpen}
        onCancel={() => setTagModalOpen(false)}
        onOk={handleCreateTag}
        okText="创建"
        cancelText="取消"
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <Input placeholder="标签名称" value={newTagName} onChange={(e) => setNewTagName(e.target.value)} />
          <Input placeholder="分类（可选）" value={newTagCategory} onChange={(e) => setNewTagCategory(e.target.value)} />
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span>颜色：</span>
            <ColorPicker value={newTagColor} onChange={(_, hex) => setNewTagColor(hex)} />
          </div>
        </div>
      </Modal>

      {/* Create Link Modal */}
      <Modal
        title="新建知识关联"
        open={linkModalOpen}
        onCancel={() => { setLinkModalOpen(false); linkForm.resetFields(); }}
        onOk={() => linkForm.submit()}
        okText="创建"
        cancelText="取消"
      >
        <Form form={linkForm} layout="vertical" onFinish={handleCreateLink}>
          <Form.Item label="目标节点" name="target_node" rules={[{ required: true, message: "请选择目标节点" }]}>
            <Select
              showSearch
              placeholder="选择目标节点"
              options={graphData?.nodes
                .filter((n) => n.id !== selectedNode?.id)
                .map((n) => ({ value: n.id, label: `${NODE_LABELS_ZH[n.type] || n.type}: ${n.label}` })) ?? []}
              filterOption={(input, option) =>
                (option?.label as string)?.toLowerCase().includes(input.toLowerCase()) ?? false
              }
            />
          </Form.Item>
          <Form.Item label="关联类型" name="link_type" rules={[{ required: true }]} initialValue="related">
            <Select options={LINK_TYPES} />
          </Form.Item>
          <Form.Item label="标签说明" name="label">
            <Input placeholder="关联描述（可选）" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
