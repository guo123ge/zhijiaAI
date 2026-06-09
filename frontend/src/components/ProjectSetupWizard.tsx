import { useEffect, useRef, useState } from "react";
import {
  Button,
  Card,
  Input,
  message,
  Space,
  Steps,
  Tag,
} from "antd";
import {
  RocketOutlined,
  FileTextOutlined,
  CheckCircleOutlined,
  LoadingOutlined,
  ThunderboltOutlined,
  ClockCircleOutlined,
} from "@ant-design/icons";
import { API_BASE } from "../api";

interface Props {
  projectId: number;
  onComplete?: () => void;
}

type Stage = "input" | "running" | "done";

interface StepEvent {
  type: string;
  content?: string;
  tool_name?: string;
  tool_args?: string;
  tool_result?: string;
  answer?: string;
  error?: string;
}

const TEMPLATES = [
  {
    label: "住宅楼",
    text: "5层框架结构住宅楼，建筑面积约3000m²，地下1层车库。基础采用独立基础，主体C30混凝土、HRB400钢筋。外墙面砖，内墙乳胶漆，铝合金门窗。",
  },
  {
    label: "办公楼",
    text: "10层框架-剪力墙结构办公楼，建筑面积约8000m²。基础为筏板基础，主体C35混凝土、HRB400钢筋。玻璃幕墙外立面，精装修交付。",
  },
  {
    label: "商业综合体",
    text: "地上4层地下2层商业综合体，总建筑面积约15000m²。钢筋混凝土框架结构，C40混凝土，大跨度梁。地面石材铺装，吊顶装修，自动扶梯4部。",
  },
];

const BASE = API_BASE;

export default function ProjectSetupWizard({ projectId, onComplete }: Props) {
  const [stage, setStage] = useState<Stage>("input");
  const [description, setDescription] = useState("");
  const [steps, setSteps] = useState<StepEvent[]>([]);
  const [finalAnswer, setFinalAnswer] = useState("");
  const [error, setError] = useState("");
  const [elapsed, setElapsed] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const logRef = useRef<HTMLDivElement>(null);

  // Elapsed timer
  useEffect(() => {
    if (stage === "running") {
      setElapsed(0);
      timerRef.current = setInterval(() => setElapsed((s) => s + 1), 1000);
    } else if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [stage]);

  // Auto-scroll log
  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [steps]);

  const toolCallCount = steps.filter((s) => s.tool_name).length;

  const handleStart = async () => {
    if (!description.trim()) {
      message.warning("请输入工程描述");
      return;
    }

    setStage("running");
    setSteps([]);
    setFinalAnswer("");
    setError("");

    try {
      const instruction = `智能开项：${description.trim()}`;
      const resp = await fetch(`${BASE}/projects/${projectId}/orchestrate/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ instruction }),
      });

      if (!resp.ok) {
        throw new Error(`API error: ${resp.status}`);
      }

      const reader = resp.body?.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (reader) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          try {
            const evt: StepEvent = JSON.parse(line.slice(6));
            if (evt.type === "done") {
              setFinalAnswer(evt.answer || "");
              if (evt.error) setError(evt.error);
              setStage("done");
            } else {
              setSteps((prev) => [...prev, evt]);
            }
          } catch {
            // ignore parse errors
          }
        }
      }
    } catch (e: any) {
      setError(e.message);
      setStage("done");
    }
  };

  const formatElapsed = (s: number) => {
    const m = Math.floor(s / 60);
    const sec = s % 60;
    return m > 0 ? `${m}m ${sec}s` : `${sec}s`;
  };

  const currentStep = stage === "input" ? 0 : stage === "running" ? 1 : 2;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <Steps
        current={currentStep}
        size="small"
        items={[
          { title: "工程描述", icon: <FileTextOutlined /> },
          {
            title: stage === "running" ? `AI 生成中 (${formatElapsed(elapsed)})` : "AI 生成",
            icon: stage === "running" ? <LoadingOutlined /> : <RocketOutlined />,
          },
          { title: "完成", icon: <CheckCircleOutlined /> },
        ]}
      />

      {stage === "input" && (
        <Card size="small" title="描述你的工程">
          {/* Quick templates */}
          <div style={{ marginBottom: 10 }}>
            <span style={{ fontSize: 12, color: "var(--text-muted)", marginRight: 8 }}>
              快速模板：
            </span>
            <Space size={4} wrap>
              {TEMPLATES.map((t) => (
                <Tag
                  key={t.label}
                  style={{ cursor: "pointer" }}
                  color={description === t.text ? "blue" : undefined}
                  onClick={() => setDescription(t.text)}
                >
                  <ThunderboltOutlined /> {t.label}
                </Tag>
              ))}
            </Space>
          </div>

          <Input.TextArea
            rows={6}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder={
              "请描述工程信息，例如：\n\n" +
              "5层框架结构住宅楼，建筑面积约3000m²，地下1层车库，\n" +
              "基础采用独立基础，主体为C30混凝土，HRB400钢筋，\n" +
              "外墙面砖，内墙乳胶漆，铝合金门窗。"
            }
          />
          <div style={{ marginTop: 12, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
              {description.length > 0 ? `${description.length} 字` : ""}
            </span>
            <Button
              type="primary"
              icon={<RocketOutlined />}
              onClick={handleStart}
              disabled={!description.trim()}
            >
              开始智能开项
            </Button>
          </div>
        </Card>
      )}

      {(stage === "running" || stage === "done") && (
        <>
          {/* Steps log */}
          <Card
            size="small"
            title={
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span>
                  {stage === "running" ? <LoadingOutlined style={{ marginRight: 8 }} /> : null}
                  执行日志
                </span>
                <Space size={12} style={{ fontSize: 12, color: "var(--text-muted)" }}>
                  <span><ClockCircleOutlined /> {formatElapsed(elapsed)}</span>
                  <span>工具调用: {toolCallCount}</span>
                </Space>
              </div>
            }
          >
            <div ref={logRef} style={{ maxHeight: 280, overflow: "auto" }}>
              {steps.map((s, i) => (
                <div
                  key={i}
                  style={{
                    padding: "4px 0",
                    borderBottom: "1px solid rgba(255,255,255,0.06)",
                    fontSize: 12,
                  }}
                >
                  {s.tool_name && (
                    <Tag color="blue" style={{ fontSize: 11 }}>
                      {s.tool_name}
                    </Tag>
                  )}
                  <span style={{ color: "var(--text-secondary)" }}>
                    {s.content?.slice(0, 200) || s.tool_result?.slice(0, 200) || s.type}
                  </span>
                </div>
              ))}
              {steps.length === 0 && stage === "running" && (
                <div style={{ color: "var(--text-muted)", padding: 12 }}>等待 AI 响应...</div>
              )}
            </div>
          </Card>

          {/* Final result */}
          {stage === "done" && (
            <Card
              size="small"
              title={error ? "❌ 执行出错" : `✅ 智能开项完成 (${formatElapsed(elapsed)}, ${toolCallCount} 次工具调用)`}
              style={{
                borderColor: error ? "rgba(255,77,79,0.3)" : "rgba(82,196,26,0.3)",
              }}
            >
              {error && (
                <div style={{ color: "#ff7875", marginBottom: 8 }}>{error}</div>
              )}
              <div
                style={{
                  whiteSpace: "pre-wrap",
                  fontSize: 13,
                  lineHeight: 1.7,
                  color: "var(--text-primary)",
                }}
              >
                {finalAnswer || "（无回复）"}
              </div>
              <div style={{ marginTop: 12, display: "flex", gap: 8 }}>
                <Button onClick={() => { setStage("input"); setSteps([]); }}>
                  重新开项
                </Button>
                {onComplete && (
                  <Button type="primary" onClick={onComplete}>
                    查看清单
                  </Button>
                )}
              </div>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
