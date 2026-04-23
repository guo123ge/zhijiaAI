import { useEffect, useMemo, useState } from "react";
import { Card, Input, Select, Table, Tag, Statistic, Row, Col, Spin, message } from "antd";
import type { ColumnsType } from "antd/es/table";
import type { QuotaItemDTO, QuotaChapterStat } from "../api";
import { api } from "../api";
import PageBreadcrumb from "../components/PageBreadcrumb";

const PAGE_SIZE = 20;

const CHAPTER_COLORS: Record<string, string> = {
  "土石方工程": "#d4a017",
  "地基与桩基工程": "#8b6914",
  "砌筑工程": "#cd853f",
  "混凝土工程": "#4a90d9",
  "钢筋工程": "#5b8def",
  "模板工程": "#7b68ee",
  "防水工程": "#20b2aa",
  "保温工程": "#3cb371",
  "装饰装修-抹灰": "#daa520",
  "装饰装修-墙面": "#db7093",
  "装饰装修-吊顶": "#da70d6",
  "楼地面工程": "#bc8f8f",
  "门窗工程": "#6495ed",
  "给排水-管道": "#1e90ff",
  "给排水-附件设备": "#4169e1",
  "电气-配管": "#ffa500",
  "电气-线缆": "#ff8c00",
  "电气-设备器具": "#ff7f50",
  "暖通空调工程": "#ff6347",
  "消防工程": "#dc143c",
  "弱电智能化": "#9370db",
  "室外工程": "#2e8b57",
  "脚手架及措施": "#708090",
  "拆除工程": "#a0522d",
  "钢结构工程": "#4682b4",
  "涂料涂装工程": "#deb887",
  "电梯安装工程": "#5f9ea0",
  "管道保温防腐": "#66cdaa",
  "预制装配式": "#7b68ee",
};

export default function QuotaLibrary() {
  const [items, setItems] = useState<QuotaItemDTO[]>([]);
  const [total, setTotal] = useState(0);
  const [stats, setStats] = useState<QuotaChapterStat[]>([]);
  const [statsTotal, setStatsTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [keyword, setKeyword] = useState("");
  const [chapter, setChapter] = useState<string | undefined>(undefined);
  const [searchText, setSearchText] = useState("");

  // Load stats once
  useEffect(() => {
    api.getQuotaStats().then((res) => {
      setStats(res.chapters);
      setStatsTotal(res.total);
    }).catch(() => message.error("加载统计失败"));
  }, []);

  // Load items on filter/page change
  useEffect(() => {
    setLoading(true);
    api.listQuotaItems({
      skip: (page - 1) * PAGE_SIZE,
      limit: PAGE_SIZE,
      chapter,
      keyword: keyword || undefined,
    }).then((res) => {
      setItems(res.items);
      setTotal(res.total);
    }).catch(() => message.error("加载定额失败"))
      .finally(() => setLoading(false));
  }, [page, keyword, chapter]);

  // Reset page when filter changes
  useEffect(() => { setPage(1); }, [keyword, chapter]);

  const chapterOptions = useMemo(() =>
    stats.map((s) => ({ label: `${s.chapter} (${s.count})`, value: s.chapter })),
    [stats]
  );

  const columns: ColumnsType<QuotaItemDTO> = [
    {
      title: "编码",
      dataIndex: "quota_code",
      width: 120,
      render: (v: string) => <span style={{ fontFamily: "monospace", color: "#60a5fa" }}>{v}</span>,
    },
    {
      title: "名称",
      dataIndex: "name",
      ellipsis: true,
    },
    {
      title: "单位",
      dataIndex: "unit",
      width: 70,
      align: "center",
    },
    {
      title: "章节",
      dataIndex: "chapter",
      width: 160,
      render: (v: string) => (
        <Tag
          color={CHAPTER_COLORS[v] || "#555"}
          style={{ cursor: "pointer", fontSize: 12 }}
          onClick={() => { setChapter(v); }}
        >
          {v}
        </Tag>
      ),
    },
    {
      title: "人工",
      dataIndex: "labor_qty",
      width: 80,
      align: "right",
      render: (v: number) => v > 0 ? v.toFixed(2) : "-",
    },
    {
      title: "材料",
      dataIndex: "material_qty",
      width: 80,
      align: "right",
      render: (v: number) => v > 0 ? v.toFixed(2) : "-",
    },
    {
      title: "机械",
      dataIndex: "machine_qty",
      width: 80,
      align: "right",
      render: (v: number) => v > 0 ? v.toFixed(2) : "-",
    },
  ];

  return (
    <div className="page-container" style={{ padding: 24, maxWidth: 1400 }}>
      <PageBreadcrumb items={[{ label: "定额库" }]} />

      {/* Stats Row */}
      <Row gutter={16} style={{ marginBottom: 20 }}>
        <Col span={6}>
          <Card size="small" style={{ background: "rgba(20, 86, 184, 0.08)", border: "1px solid #1e293b" }}>
            <Statistic title="定额总数" value={statsTotal} valueStyle={{ color: "#60a5fa", fontSize: 28 }} />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small" style={{ background: "rgba(32, 178, 170, 0.08)", border: "1px solid #1e293b" }}>
            <Statistic title="章节分类" value={stats.length} valueStyle={{ color: "#20b2aa", fontSize: 28 }} />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small" style={{ background: "rgba(218, 165, 32, 0.08)", border: "1px solid #1e293b" }}>
            <Statistic
              title="当前筛选"
              value={total}
              suffix="条"
              valueStyle={{ color: "#daa520", fontSize: 28 }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small" style={{ background: "rgba(123, 104, 238, 0.08)", border: "1px solid #1e293b" }}>
            <Statistic
              title="最大章节"
              value={stats.length > 0 ? stats[0].chapter : "-"}
              valueStyle={{ color: "#7b68ee", fontSize: 16, lineHeight: "32px" }}
            />
          </Card>
        </Col>
      </Row>

      {/* Filters */}
      <Card
        size="small"
        style={{ marginBottom: 16, border: "1px solid #1e293b" }}
        bodyStyle={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}
      >
        <span className="material-symbols-outlined" style={{ color: "#94a3b8", fontSize: 20 }}>search</span>
        <Input.Search
          placeholder="搜索定额名称..."
          allowClear
          value={searchText}
          onChange={(e) => setSearchText(e.target.value)}
          onSearch={(v) => setKeyword(v)}
          style={{ width: 280 }}
        />
        <Select
          placeholder="选择章节"
          allowClear
          showSearch
          optionFilterProp="label"
          value={chapter}
          onChange={(v) => setChapter(v)}
          options={chapterOptions}
          style={{ minWidth: 240 }}
        />
        {(keyword || chapter) && (
          <a
            style={{ color: "#60a5fa", cursor: "pointer", fontSize: 13 }}
            onClick={() => { setKeyword(""); setSearchText(""); setChapter(undefined); }}
          >
            清除筛选
          </a>
        )}
      </Card>

      {/* Chapter Tag Cloud */}
      <Card
        size="small"
        style={{ marginBottom: 16, border: "1px solid #1e293b" }}
        bodyStyle={{ display: "flex", gap: 6, flexWrap: "wrap" }}
      >
        {stats.map((s) => (
          <Tag
            key={s.chapter}
            color={chapter === s.chapter ? CHAPTER_COLORS[s.chapter] || "#555" : undefined}
            style={{
              cursor: "pointer",
              opacity: chapter && chapter !== s.chapter ? 0.4 : 1,
              transition: "opacity 0.2s",
            }}
            onClick={() => setChapter(chapter === s.chapter ? undefined : s.chapter)}
          >
            {s.chapter} ({s.count})
          </Tag>
        ))}
      </Card>

      {/* Table */}
      <Spin spinning={loading}>
        <Table
          dataSource={items}
          columns={columns}
          rowKey="id"
          size="small"
          pagination={{
            current: page,
            pageSize: PAGE_SIZE,
            total,
            showSizeChanger: false,
            showTotal: (t) => `共 ${t} 条`,
            onChange: (p) => setPage(p),
          }}
          scroll={{ y: 480 }}
          style={{ border: "1px solid #1e293b", borderRadius: 8, overflow: "hidden" }}
        />
      </Spin>
    </div>
  );
}
