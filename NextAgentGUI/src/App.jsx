import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  ArrowClockwise,
  ArrowUp,
  Broadcast,
  CalendarBlank,
  CaretDown,
  Check,
  CircleNotch,
  Coffee,
  Code,
  Command,
  Cpu,
  Folder,
  Gear,
  GitBranch,
  Globe,
  Eye,
  EyeSlash,
  Info,
  List,
  MagnifyingGlass,
  Monitor,
  Key,
  Package,
  Paperclip,
  PencilSimple,
  Plug,
  Plus,
  PushPin,
  DotsThreeVertical,
  Hand,
  SidebarSimple,
  SlidersHorizontal,
  Sparkle,
  SquaresFour,
  Sun,
  Timer,
  Tray,
  Trash,
  Wrench,
  X,
} from "@phosphor-icons/react";
import { coreApi } from "./core-api";
import zh from "./zh-CN.js";
import en from "./en.js";

let _lang = "en";
export function t(key, ...args) {
  if (_lang === "zh" && zh[key]) {
    const v = zh[key];
    return typeof v === "function" ? v(...args) : v;
  }
  // English fallback
  if (en[key]) {
    const v = en[key];
    return typeof v === "function" ? v(...args) : v;
  }
  return args.length ? `${key}(${args.join(",")})` : key;
}

const workSessions = [];

const defaultSettings = {
  launchMode: "Dswork",
  enterToSend: true,
  showRecentDetails: true,
  conversationMemory: true,
  userMemory: true,
  localUsageStats: true,
  agentMode: true,
  background: "Warm",
  density: "Comfortable",
  reduceMotion: false,
};

const capabilitySkills = [
  ["代码审查", "查找缺陷、回归和缺失的测试。"],
  ["错误定位", "重现问题并应用针对性修复。"],
  ["前端优化", "改进视觉一致性和响应式状态。"],
  ["发布说明", "准备简洁的面向用户的发布摘要。"],
  ["持久记忆", "记住有用的偏好和项目经验。"],
];

const workNav = [
  [Tray, "项目"],
  [CalendarBlank, "定时任务"],
  [Broadcast, "实时组件"],
];

const slashCommands = [
  ["batch", "运行一组具有共享目标的相关任务。"],
  ["code-review", "审查代码更改，查找缺陷、回归和缺失的测试。"],
  ["compact", "压缩当前对话上下文。"],
  ["context", "检查当前上下文中的文件和工具。"],
  ["debug", "重现并诊断错误，然后应用针对性修复。"],
  ["deep-research", "深入研究一个主题并返回有来源的综合分析。"],
  ["goal", "创建或更新当前长期目标。"],
  ["help", "显示可用的 NextAgent 命令和快捷键。"],
  ["init", "为 NextAgent 初始化工作区指引。"],
  ["plan", "在实施之前进入规划模式。"],
  ["review", "审查当前工作区的更改。"],
  ["test", "运行相关测试套件并汇总失败信息。"],
];

const emptyCoreStats = {
  sessions: 0,
  messages: 0,
  total_tokens: 0,
  prompt_tokens: 0,
  completion_tokens: 0,
  cache_hit_tokens: 0,
  cache_miss_tokens: 0,
  saved_cost: 0,
  avg_hit_rate: 0,
  models: [],
  model_usage: {},
  rounds: [],
};

function formatNumber(value) {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  return new Intl.NumberFormat().format(value || 0);
}

function sessionFromCore(session) {
  const map = { running: "运行中", failed: "失败", stopped: "已停止", idle: "空闲", completed: "完成" };
  const status = map[session.status] || session.model;
  return { ...session, meta: status };
}

function cleanAgentResponse(response = "") {
  return response.split(/\n\s*[✓✔]\s*Done\b/i)[0].trim();
}

function conversationTurns(conversation) {
  if (!conversation) return [];
  if (conversation.turns) return conversation.turns;
  return [{ title: conversation.title, response: conversation.response, status: conversation.status }];
}

function startConversation(conversation, title, mode = "dswork") {
  return {
    title: conversation?.title || title,
    status: "thinking",
    turns: [...conversationTurns(conversation), { title, response: "", status: "thinking", mode, trace: [] }],
  };
}

function finishConversation(conversation, response, status = "complete", trace = []) {
  const turns = conversationTurns(conversation);
  return {
    ...conversation,
    status,
    turns: turns.map((turn, index) => index === turns.length - 1 ? { ...turn, response, status, trace } : turn),
  };
}

function chatMessages(conversation) {
  return conversationTurns(conversation).flatMap((turn) => {
    const messages = [{ role: "user", content: turn.title }];
    if (turn.response && turn.status !== "thinking") messages.push({ role: "assistant", content: turn.response });
    return messages;
  });
}

function traceLabel(event) {
  if (!event) return "";
  if (event.type === "tool") return event.name || t("toolCall");
  return event.label || t("thinkingStage");
}

function dsworkThoughts(turn, thinking) {
  if (thinking) {
    return [
      t("stageUnderstanding"),
      t("stageContext"),
      t("stageComposing"),
    ];
  }
  const trace = Array.isArray(turn.trace) ? turn.trace : [];
  const stages = trace.filter((event) => event.type !== "tool").slice(0, 3).map(traceLabel);
  return stages.length ? stages : [
    t("stageUnderstanding"),
    t("stageContext"),
    t("stageResponse"),
  ];
}

function codeTraceItems(turn, thinking) {
  const trace = Array.isArray(turn.trace) ? turn.trace : [];
  if (thinking && !trace.length) {
    return [{ type: "stage", label: t("traceRunning"), detail: t("deepseekInspecting"), status: "running" }];
  }
  if (!trace.length) {
    return [{ type: "stage", label: t("traceNoTools"), detail: t("traceNoToolsDesc"), status: "complete" }];
  }
  return trace;
}

export function App() {
  const [setupState, setSetupState] = useState("loading");
  const [startupError, setStartupError] = useState("");
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [mode, setMode] = useState("Dswork");
  const [sessions, setSessions] = useState([]);
  const [workItems, setWorkItems] = useState(workSessions);
  const [activeId, setActiveId] = useState(null);
  const [query, setQuery] = useState("");
  const [prompt, setPrompt] = useState("");
  const [permission, setPermission] = useState("acceptEdits");
  const [model, setModel] = useState("deepseek-v4-flash");
  const [effort, setEffort] = useState("High");
  const [selectedWorkdir, setSelectedWorkdir] = useState("");
  const [branch, setBranch] = useState("main");
  const [worktree, setWorktree] = useState(false);
  const [codeMenu, setCodeMenu] = useState(null);
  const [attachedFiles, setAttachedFiles] = useState([]);
  const [directoryModal, setDirectoryModal] = useState(null);
  const [range, setRange] = useState("All");
  const [statsView, setStatsView] = useState("overview");
  const [sent, setSent] = useState(false);
  const [workPage, setWorkPage] = useState("Home");
  const [modal, setModal] = useState(null);
  const [projects, setProjects] = useState([]);
  const [scheduled, setScheduled] = useState([]);
  const [artifacts, setArtifacts] = useState([]);
  const [connectors, setConnectors] = useState([]);
  const [plugins, setPlugins] = useState([]);
  const [skills, setSkills] = useState([]);
  const [keepAwake, setKeepAwake] = useState(false);
  const [customizeOpen, setCustomizeOpen] = useState(false);
  const [coreOnline, setCoreOnline] = useState(false);
  const [coreConfigured, setCoreConfigured] = useState(false);
  const [coreError, setCoreError] = useState("");
  const [coreBusy, setCoreBusy] = useState(false);
  const [queuedPrompt, setQueuedPrompt] = useState("");
  const requestGeneration = useRef(0);
  const [recentMenu, setRecentMenu] = useState(null);
  const [renameTarget, setRenameTarget] = useState(null);
  const [archivedItems, setArchivedItems] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem("nextagent-archive-bin") || "[]");
    } catch {
      return [];
    }
  });
  const [pinTip, setPinTip] = useState(false);
  const [coreResponse, setCoreResponse] = useState("");
  const [newItemActive, setNewItemActive] = useState(false);
  const [coreStats, setCoreStats] = useState(emptyCoreStats);
  const [workspaceInfo, setWorkspaceInfo] = useState({ workdir: "next-agent" });
  const [stateLoaded, setStateLoaded] = useState(false);
  const [profileMenu, setProfileMenu] = useState(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settings, setSettings] = useState(() => {
    try {
      return { ...defaultSettings, ...JSON.parse(localStorage.getItem("nextagent-settings") || "{}") };
    } catch {
      return defaultSettings;
    }
  });
  const [resetOpen, setResetOpen] = useState(false);
  const [resetCountdown, setResetCountdown] = useState(null);
  const [notice, setNotice] = useState("");
  const [lang, setLang] = useState(() => {
    try { return localStorage.getItem("nextagent-lang") || "en"; } catch { return "en"; }
  });

  useEffect(() => {
    localStorage.setItem("nextagent-lang", lang);
    document.documentElement.lang = lang === "zh" ? "zh-CN" : "en";
    _lang = lang;
  }, [lang]);

  const isCode = mode === "Code";
  const slashQuery = prompt.startsWith("/") ? prompt.slice(1).toLowerCase() : "";
  const filteredSlashCommands = slashCommands.filter(([name]) => name.includes(slashQuery));
  const visibleSessions = isCode ? sessions : workItems;
  const activeCodeSession = sessions.find((session) => session.id === activeId);
  const activeWorkItem = workItems.find((item) => item.id === activeId);
  const codeConversation = activeCodeSession?.conversation || null;
  const workConversation = activeWorkItem?.conversation || null;
  const filteredSessions = useMemo(
    () => visibleSessions.filter((session) => session.title.toLowerCase().includes(query.toLowerCase())),
    [query, visibleSessions],
  );

  useEffect(() => {
    localStorage.setItem("nextagent-settings", JSON.stringify(settings));
    document.documentElement.dataset.motion = settings.reduceMotion ? "reduced" : "full";
  }, [settings]);

  useEffect(() => {
    if (settings.launchMode === "Code" && settings.agentMode) setMode("Code");
  }, []);

  useEffect(() => {
    if (!settings.agentMode && mode === "Code") setMode("Dswork");
  }, [settings.agentMode, mode]);

  async function refreshCore() {
    const [health, sessionData, stats, workspace, savedState] = await Promise.all([
      coreApi.health(),
      coreApi.sessions(),
      coreApi.stats(),
      coreApi.workspace(),
      coreApi.state(),
    ]);
    setCoreOnline(Boolean(health.ok));
    const configured = Boolean(health.provider_configured);
    setCoreConfigured(configured);
    setCoreError("");
    setSessions(sessionData.sessions.map((session) => {
      const previous = savedState.code.find((item) => item.id === session.id);
      return {
        ...sessionFromCore(session),
        title: previous?.title || session.title,
        conversation: previous?.conversation || session.conversation || null,
        pinned: previous?.pinned || false,
        done: previous?.done || false,
      };
    }));
    setWorkItems(savedState.dswork || []);
    setArchivedItems(savedState.archived || []);
    setProjects(savedState.projects || []);
    setScheduled(savedState.scheduled || []);
    setArtifacts(savedState.artifacts || []);
    setConnectors(savedState.connectors || []);
    setPlugins(savedState.plugins || []);
    coreApi.skills().then((result) => setSkills(result.skills || [])).catch(() => setSkills([]));
    setCoreStats(stats);
    setWorkspaceInfo(workspace);
    setSelectedWorkdir((current) => current || workspace.workdir);
    setStateLoaded(true);
    return sessionData.sessions;
  }

  useEffect(() => {
    if (!stateLoaded) return;
    const timer = window.setTimeout(() => {
      coreApi.saveState({ code: sessions, dswork: workItems, archived: archivedItems, projects, scheduled, artifacts, connectors, plugins }).catch(() => {});
    }, 180);
    return () => window.clearTimeout(timer);
  }, [sessions, workItems, archivedItems, projects, scheduled, artifacts, connectors, plugins, stateLoaded]);

  useEffect(() => {
    let active = true;
    async function connect() {
      try {
        const health = await coreApi.health();
        if (!health.provider_configured) {
          if (active) {
            setCoreOnline(Boolean(health.ok));
            setCoreConfigured(false);
            setSetupState("required");
          }
          return;
        }
        const preflight = await coreApi.preflight();
        if (!preflight.ok) throw new Error(preflight.error || "NextAgent core preflight failed.");
        if (active) await enterWorkspace();
      } catch (error) {
        if (active) {
          setCoreOnline(false);
          setStartupError(error.message);
          setSetupState("error");
        }
      }
    }
    connect();
    return () => { active = false; };
  }, []);

  useEffect(() => {
    function handleShortcut(event) {
      if (event.ctrlKey && event.key === ",") {
        event.preventDefault();
        setSettingsOpen(true);
        setProfileMenu(null);
        return;
      }
      if (!isCode) return;
      if (event.ctrlKey && event.key.toLowerCase() === "n") {
        event.preventDefault();
        createItem();
      } else if (event.ctrlKey && event.key.toLowerCase() === "u") {
        event.preventDefault();
        chooseCodeFiles();
      } else if (event.ctrlKey && event.shiftKey && event.key.toLowerCase() === "m") {
        event.preventDefault();
        const modes = [t("askPermissions"), t("acceptEdits"), t("planMode"), t("bypassPermissions")];
        setPermission((current) => modes[(modes.indexOf(current) + 1) % modes.length]);
      }
    }
    window.addEventListener("keydown", handleShortcut);
    return () => window.removeEventListener("keydown", handleShortcut);
  }, [isCode]);

  async function enterWorkspace() {
    await refreshCore();
    setActiveId(null);
    setNewItemActive(true);
    window.pywebview?.api?.enter_workspace?.();
    setSetupState("ready");
  }

  async function completeSetup(apiKey) {
    await coreApi.saveConfig(apiKey);
    setCoreConfigured(true);
    setStartupError("");
    setSetupState("loading");
    const preflight = await coreApi.preflight();
    if (!preflight.ok) {
      setStartupError(preflight.error || "DeepSeek API connection check failed.");
      setSetupState("error");
      return;
    }
    await enterWorkspace();
  }

  async function retryStartup() {
    try {
      setStartupError("");
      setSetupState("loading");
      const preflight = await coreApi.preflight();
      if (!preflight.provider_configured) {
        setSetupState("required");
        return;
      }
      if (!preflight.ok) throw new Error(preflight.error || "NextAgent core preflight failed.");
      await enterWorkspace();
    } catch (error) {
      setStartupError(error.message);
      setSetupState("error");
    }
  }

  function changeMode(nextMode) {
    setMode(nextMode);
    setQuery("");
    setPrompt("");
    setSent(false);
    setNewItemActive(true);
    setActiveId(null);
    if (nextMode === "Dswork") setWorkPage("Home");
  }

  function createItem() {
    setActiveId(null);
    setNewItemActive(true);
    setPrompt("");
    setSent(false);
    setCoreError("");
    setCoreResponse("");
  }

  function openCustomize() {
    setSidebarOpen(true);
    setCustomizeOpen(true);
  }

  async function chooseCodeFolder() {
    setCodeMenu(null);
    const path = await window.pywebview?.api?.choose_folder?.();
    if (path) setSelectedWorkdir(path);
  }

  async function chooseCodeFiles() {
    setCodeMenu(null);
    const files = await window.pywebview?.api?.choose_files?.();
    if (files?.length) setAttachedFiles(files);
  }

  async function chooseFolder() {
    return await window.pywebview?.api?.choose_folder?.() || "";
  }

  function openLocalPath(path) {
    if (path) window.pywebview?.api?.open_path?.(path);
  }

  async function sendPrompt(messageOverride) {
    const message = typeof messageOverride === "string" ? messageOverride : prompt;
    if (!message.trim()) return;
    const generation = ++requestGeneration.current;
    const title = message.trim();
    setPrompt("");
    setSent(true);
    setNewItemActive(false);
    if (isCode) {
      let sessionId = activeId;
      const thinkingConversation = startConversation(activeCodeSession?.conversation, title, "code");
      try {
        setCoreBusy(true);
        setCoreError("");
        if (!sessions.some((item) => item.id === sessionId)) {
          const { session } = await coreApi.createSession({ title, model, workdir: selectedWorkdir || workspaceInfo.workdir });
          sessionId = session.id;
          setActiveId(sessionId);
          setSessions((current) => [{ ...sessionFromCore(session), conversation: thinkingConversation }, ...current]);
        }
        setSessions((current) => current.map((item) => item.id === sessionId ? {
          ...item,
          title: item.conversation ? item.title : title,
          meta: t("running"),
          status: "running",
          conversation: thinkingConversation,
        } : item));
        const result = await coreApi.sendMessage(sessionId, title, model, effort);
        if (generation !== requestGeneration.current) return;
        const response = cleanAgentResponse(result.response);
        if (result.model) setModel(result.model);
        if (result.effort) setEffort(result.effort.charAt(0).toUpperCase() + result.effort.slice(1));
        setCoreResponse(response);
        setSessions((current) => current.map((item) => item.id === sessionId ? {
          ...sessionFromCore(result.session),
          title: item.title,
          pinned: item.pinned,
          done: item.done,
          conversation: finishConversation(thinkingConversation, response, "complete", result.trace || []),
        } : item));
        const stats = await coreApi.stats();
        setCoreStats(stats);
        setCoreOnline(true);
      } catch (error) {
        if (generation !== requestGeneration.current) return;
        setCoreError(error.message);
        setSessions((current) => current.map((item) => item.id === sessionId ? {
          ...item,
          meta: t("failed"),
          status: "failed",
          conversation: finishConversation(thinkingConversation, error.message, "failed", [{ type: "stage", label: t("taskFailed"), detail: error.message, status: "failed" }]),
        } : item));
      } finally {
        if (generation === requestGeneration.current) setCoreBusy(false);
      }
    } else {
      let taskId = newItemActive ? null : activeWorkItem?.id;
      const thinkingConversation = startConversation(newItemActive ? null : activeWorkItem?.conversation, title, "dswork");
      if (!taskId) {
        taskId = `ds-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
        setActiveId(taskId);
        setWorkItems((current) => [{
          id: taskId,
          title,
          meta: t("active"),
          conversation: thinkingConversation,
        }, ...current]);
      } else {
        setWorkItems((current) => current.map((item) => item.id === taskId ? {
          ...item,
          title: item.conversation ? item.title : title,
          meta: t("active"),
          conversation: thinkingConversation,
        } : item));
      }
      setActiveId(taskId);
      try {
        setCoreBusy(true);
        setCoreError("");
        const result = await coreApi.chat(chatMessages(thinkingConversation), model, taskId, effort);
        if (generation !== requestGeneration.current) return;
        if (result.model) setModel(result.model);
        if (result.effort) setEffort(result.effort.charAt(0).toUpperCase() + result.effort.slice(1));
        setWorkItems((current) => current.map((item) => item.id === taskId ? {
          ...item,
          meta: t("complete"),
          conversation: finishConversation(thinkingConversation, cleanAgentResponse(result.response), "complete", result.trace || []),
        } : item));
        const stats = await coreApi.stats();
        setCoreStats(stats);
        setCoreOnline(true);
      } catch (error) {
        if (generation !== requestGeneration.current) return;
        setCoreError(error.message);
        setWorkItems((current) => current.map((item) => item.id === taskId ? {
          ...item,
          meta: t("failed"),
          conversation: finishConversation(thinkingConversation, error.message, "failed", [{ type: "stage", label: t("taskFailed"), detail: error.message, status: "failed" }]),
        } : item));
      } finally {
        if (generation === requestGeneration.current) setCoreBusy(false);
      }
    }
  }

  function queuePrompt() {
    const next = prompt.trim();
    if (!next) return;
    setQueuedPrompt(next);
    setPrompt("");
  }

  function stopResponse() {
    requestGeneration.current += 1;
    setCoreBusy(false);
    if (isCode) {
      setSessions((current) => current.map((item) => item.id === activeId ? {
        ...item,
        meta: t("stopped"),
        status: "failed",
        conversation: finishConversation(item.conversation, t("responseStopped"), "failed"),
      } : item));
    } else {
      setWorkItems((current) => current.map((item) => item.id === activeId ? {
        ...item,
        meta: t("stopped"),
        conversation: finishConversation(item.conversation, t("responseStopped"), "failed"),
      } : item));
    }
  }

  function updateRecent(id, updater) {
    const setter = isCode ? setSessions : setWorkItems;
    setter((current) => current.map((item) => item.id === id ? updater(item) : item));
  }

  function pinRecent(session) {
    updateRecent(session.id, (item) => ({ ...item, pinned: !item.pinned }));
    setRecentMenu(null);
    if (!session.pinned && !localStorage.getItem("nextagent-pin-tip-seen")) {
      localStorage.setItem("nextagent-pin-tip-seen", "1");
      setPinTip(true);
      window.setTimeout(() => setPinTip(false), 4800);
    }
  }

  function markRecentDone(session) {
    updateRecent(session.id, (item) => ({ ...item, done: !item.done, meta: item.done ? t("complete") : t("markDone") }));
    setRecentMenu(null);
  }

  function archiveRecent(session) {
    setArchivedItems((current) => {
      const next = [{ ...session, archivedAt: Date.now(), source: mode }, ...current];
      localStorage.setItem("nextagent-archive-bin", JSON.stringify(next));
      return next;
    });
    const setter = isCode ? setSessions : setWorkItems;
    setter((current) => current.filter((item) => item.id !== session.id));
    if (activeId === session.id) createItem();
    setRecentMenu(null);
  }

  function renameRecent(id, title) {
    updateRecent(id, (item) => ({ ...item, title }));
    setRenameTarget(null);
  }

  function selectRecent(session) {
    setActiveId(session.id);
    setNewItemActive(false);
    setPrompt("");
    setSent(Boolean(session.conversation));
    setRecentMenu(null);
    if (!isCode) setWorkPage("Home");
  }

  function showNotice(message) {
    setNotice(message);
    window.setTimeout(() => setNotice(""), 3200);
  }

  function openDeepSeek() {
    const url = "https://www.deepseek.com/";
    if (window.pywebview?.api?.open_external) window.pywebview.api.open_external(url);
    else window.open(url, "_blank", "noopener,noreferrer");
    setProfileMenu(null);
  }

  function beginResetCountdown() {
    setResetOpen(false);
    setResetCountdown(3);
  }

  useEffect(() => {
    if (resetCountdown === null) return;
    if (resetCountdown > 0) {
      const timer = window.setTimeout(() => setResetCountdown((current) => current - 1), 1000);
      return () => window.clearTimeout(timer);
    }
    let active = true;
    async function finishReset() {
      try {
        await coreApi.reset();
        localStorage.clear();
        if (!active) return;
        setSessions([]);
        setWorkItems([]);
        setActiveId(null);
        setCoreConfigured(false);
        setCoreOnline(false);
        setResetCountdown(null);
        setSetupState("required");
        window.pywebview?.api?.enter_setup?.();
      } catch (error) {
        if (!active) return;
        setResetCountdown(null);
        showNotice(error.message || "NextAgent could not be reset.");
      }
    }
    finishReset();
    return () => { active = false; };
  }, [resetCountdown]);

  function RecentItem({ session }) {
    return <div className={`session-row ${recentMenu === session.id ? "menu-open" : ""}`}>
      <button className={!newItemActive && session.id === activeId ? "session active" : "session"} onClick={() => selectRecent(session)}>
        <span className={`session-dot ${session.done ? "done" : ""}`}>{session.done && <Check size={12} weight="bold" />}</span>
        <span className="session-copy"><strong>{session.title}</strong>{settings.showRecentDetails && <small>{session.meta}</small>}</span>
      </button>
      <button className="recent-more" aria-label={`${t("moreActions")} ${session.title}`} onClick={(event) => {
        event.stopPropagation();
        setRecentMenu(recentMenu === session.id ? null : session.id);
      }}><DotsThreeVertical size={17} weight="bold" /></button>
      {recentMenu === session.id && <div className="recent-menu">
        <button onClick={() => pinRecent(session)}><PushPin size={17} /> {session.pinned ? t("unpin") : t("pin")}</button>
        <button onClick={() => { setRenameTarget(session); setRecentMenu(null); }}><PencilSimple size={17} /> {t("rename")}</button>
        <span />
        <button onClick={() => markRecentDone(session)}><Check size={17} /> {session.done ? t("markActive") : t("markDone")}</button>
        <button onClick={() => archiveRecent(session)}><Tray size={17} /> {t("archive")}</button>
      </div>}
    </div>;
  }

  useEffect(() => {
    if (coreBusy || !queuedPrompt) return;
    const next = queuedPrompt;
    setQueuedPrompt("");
    sendPrompt(next);
  }, [coreBusy, queuedPrompt]);

  if (setupState === "loading" || setupState === "error") {
    return <LoadingScreen error={startupError} onRetry={retryStartup} onConfigure={() => setSetupState("required")} />;
  }
  if (setupState === "required") {
    return <SetupScreen onContinue={completeSetup} />;
  }
  if (resetCountdown !== null) {
    return <ResetRelaunchScreen seconds={resetCountdown} cancel={() => setResetCountdown(null)} />;
  }

  return (
    <main className={`app-shell ${isCode ? "code-mode" : "work-mode"} theme-${settings.background.toLowerCase().replace(" ", "-")} density-${settings.density.toLowerCase()}`}>
      <header className="topbar">
        <button className="icon-button" aria-label={t("toggleSidebar")} onClick={() => setSidebarOpen(!sidebarOpen)}><List size={18} /></button>
        <button className="icon-button desktop-only" aria-label={t("panelLayout")} onClick={() => setSidebarOpen(!sidebarOpen)}><SidebarSimple size={18} /></button>
        <button className="icon-button desktop-only" aria-label={t("search")} onClick={() => document.querySelector(".search-input")?.focus()}><MagnifyingGlass size={18} /></button>
        <span className="topbar-divider" />
        <button className="icon-button muted" aria-label={t("back")}><ArrowLeft size={18} /></button>
        <button className="icon-button muted" aria-label={t("forward")}><ArrowRight size={18} /></button>
        <div className="window-title"><Command size={16} weight="fill" /> {settingsOpen ? t("settings") : customizeOpen ? t("customize") : "NextAgent"}</div>
      </header>

      {settingsOpen ? <SettingsPage settings={settings} setSettings={setSettings} configured={coreConfigured} close={() => setSettingsOpen(false)} /> : customizeOpen ? <CustomizePage onClose={() => setCustomizeOpen(false)} navOpen={sidebarOpen} skills={skills} setSkills={setSkills} connectors={connectors} setConnectors={setConnectors} plugins={plugins} setPlugins={setPlugins} showNotice={showNotice} /> : <section className="workspace">
        <aside className={`sidebar ${sidebarOpen ? "open" : "closed"}`}>
          <div className="mode-switch">
            {["Dswork", "Code"].map((item) => (
              <button key={item} disabled={item === "Code" && !settings.agentMode} title={item === "Code" && !settings.agentMode ? t("enableAgentMode") : ""} className={mode === item ? "selected" : ""} onClick={() => changeMode(item)}>
                {item === "Code" ? <Code size={16} /> : <SquaresFour size={16} />} {item === "Code" ? t("code") : t("dswork")}
              </button>
            ))}
          </div>

          <button className={`new-session ${newItemActive && (isCode || workPage === "Home") ? "active" : ""} ${!isCode && workPage !== "Home" ? "inactive" : ""}`} onClick={() => {
            if (!isCode) setWorkPage("Home");
            createItem();
          }}><Plus size={17} /> {isCode ? t("newSession") : t("newTask")} <span>Ctrl N</span></button>
          {!isCode && workNav.map(([Icon, label], i) => {
            const [pageName, tKey] = i === 0 ? ["Projects", "projects"] : i === 1 ? ["Scheduled", "scheduled"] : ["Live artifacts", "liveArtifacts"];
            return <button className={`sidebar-link ${workPage === pageName ? "current" : ""}`} key={label} onClick={() => setWorkPage(pageName)}><Icon size={17} /> {t(tKey)}</button>;
          })}
          <button className="sidebar-link" onClick={openCustomize}><Wrench size={17} /> {t("customize")}</button>

          <label className="search-box">
            <MagnifyingGlass size={15} />
            <input className="search-input" value={query} onChange={(event) => setQuery(event.target.value)} placeholder={isCode ? t("searchSessions") : t("searchTasks")} />
            {query && <button onClick={() => setQuery("")} aria-label={t("clearSearch")}><X size={13} /></button>}
          </label>

          {filteredSessions.some((session) => session.pinned) && <div className="section-title pinned-title"><span>{t("pinned")}</span></div>}
          {filteredSessions.some((session) => session.pinned) && <nav className="session-list pinned-list">
            {filteredSessions.filter((session) => session.pinned).map((session) => <RecentItem key={session.id} session={session} />)}
          </nav>}
          <div className="section-title"><span>{t("recents")}</span><SlidersHorizontal size={15} /></div>
          <div className="sidebar-scroll">
            <nav className="session-list">
              {filteredSessions.filter((session) => !session.pinned).map((session) => <RecentItem key={session.id} session={session} />)}
            </nav>
            {pinTip && <div className="pin-tip"><Hand size={20} weight="fill" /><span><strong>Tip:</strong> {t("tip")}</span></div>}
          </div>

          <div className="profile-area">
            {profileMenu && <div className="profile-menu">
              <span className="profile-menu-title">NextAgent</span>
              <button onClick={() => { setSettingsOpen(true); setProfileMenu(null); }}><Gear size={17} /> {t("settings")} <small>Ctrl,</small></button>
              <button onClick={() => setProfileMenu(profileMenu === "language" ? "main" : "language")}><Globe size={17} /> {t("language")} <CaretDown className={profileMenu === "language" ? "submenu-caret open" : "submenu-caret"} size={14} /></button>
              {profileMenu === "language" && <div className="language-submenu">
                <button onClick={() => { _lang = "en"; setLang("en"); setProfileMenu("main"); }}>{lang === "en" ? <Check size={15} weight="bold" /> : <span style={{width:15}} />} English</button>
                <button onClick={() => { _lang = "zh"; setLang("zh"); setProfileMenu("main"); }}>{lang === "zh" ? <Check size={15} weight="bold" /> : <span style={{width:15}} />} 中文（简体）</button>
                <span>{t("moreLanguagesSoon")}</span>
              </div>}
              <button className="disabled-menu-item" disabled><Cpu size={17} /> {t("thirdPartyModels")} <small>{t("comingSoon")}</small></button>
              <i />
              <button onClick={() => { showNotice(t("latestVersion")); setProfileMenu(null); }}><ArrowClockwise size={17} /> {t("checkUpdates")}</button>
              <button onClick={openDeepSeek}><Info size={17} /> {t("learnDeepSeek")}</button>
              <i />
              <button className="danger-menu-item" onClick={() => { setResetOpen(true); setProfileMenu(null); }}><Trash size={17} /> {t("resetNextAgent")}</button>
            </div>}
            <button className="profile" onClick={() => setProfileMenu(profileMenu ? null : "main")}>
              <span className="brand-mark"><Sparkle size={16} weight="fill" /></span>
              <span><strong>NextAgent</strong><small>{isCode ? t("codeWorkspace") : t("deepseekChat")}</small></span>
              <CaretDown className={profileMenu ? "profile-caret open" : "profile-caret"} size={14} />
            </button>
          </div>
        </aside>

        <article className="main-panel">
          {isCode ? (
            codeConversation ? (
              <div className="code-layout">
                <CodeConversation conversation={codeConversation} />
                {isCode && (
                  <div className="composer-wrap">
              <div className="context-pills">
                <CodePopover open={codeMenu === "runtime"} onToggle={() => setCodeMenu(codeMenu === "runtime" ? null : "runtime")} trigger={<><Monitor size={15} /> {t("local")}</>}>
                  <span className="popover-label">{t("runEnvironment")}</span>
                  <button className="selected"><Monitor size={15} /> {t("local")} <Check size={14} /></button>
                  <button className="muted-item" disabled>{t("remoteLater")}</button>
                </CodePopover>
                <CodePopover open={codeMenu === "folder"} onToggle={() => setCodeMenu(codeMenu === "folder" ? null : "folder")} trigger={<><Folder size={15} /> {(selectedWorkdir || workspaceInfo.workdir)?.split(/[\\/]/).pop() || "next-agent"}</>}>
                  <span className="popover-label">{t("recent")}</span>
                  <button className="selected"><Folder size={15} /> {(selectedWorkdir || workspaceInfo.workdir)?.split(/[\\/]/).pop()} <Check size={14} /></button>
                  <button onClick={chooseCodeFolder}><Folder size={15} /> {t("openFolder")}...</button>
                </CodePopover>
                <CodePopover open={codeMenu === "branch"} onToggle={() => setCodeMenu(codeMenu === "branch" ? null : "branch")} trigger={<><GitBranch size={15} /> {branch}</>}>
                  <button className="selected" onClick={() => { setBranch("main"); setCodeMenu(null); }}>main <Check size={14} /></button>
                  <label className="branch-search"><MagnifyingGlass size={14} /><input placeholder={t("searchBranches")} /></label>
                </CodePopover>
                <button className={worktree ? "active-pill" : ""} onClick={() => setWorktree(!worktree)}><span className="worktree-square" /> {t("worktree")}</button>
                {attachedFiles.length > 0 && <button title={attachedFiles.join("\n")}><Paperclip size={15} /> {attachedFiles.length} {attachedFiles.length > 1 ? t("files") : t("file")}</button>}
                <button onClick={chooseCodeFolder} aria-label={t("addFolderToSession")}><Folder size={15} /><Plus size={11} /></button>
              </div>
              <div className="composer compact-composer">
                <DeepSeekWhale className="composer-whale" swimming working={coreBusy} />
                <textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} onKeyDown={(event) => {
                  if (settings.enterToSend && event.key === "Enter" && !event.shiftKey) { event.preventDefault(); sendPrompt(); }
                }} placeholder={t("describeTask")} />
                {coreBusy
                  ? <button className="send code-stop" onClick={stopResponse} aria-label={t("stopResponse")}><span /></button>
                  : <button className="send" disabled={!prompt.trim()} onClick={sendPrompt} aria-label={t("sendTask")}><ArrowUp size={17} weight="bold" /></button>}
              </div>
              {prompt.startsWith("/") && <SlashCommandMenu commands={filteredSlashCommands} onSelect={(command) => setPrompt(`/${command} `)} />}
              <div className="composer-footer">
                <Select value={permission} setValue={setPermission} options={[t("askPermissions"), t("acceptEdits"), t("planMode"), t("bypassPermissions")]} className="permission-select" />
                <button aria-label={t("moreOptions")} className="code-plus-trigger" onClick={() => setCodeMenu(codeMenu === "plus" ? null : "plus")}><Plus size={16} /></button>
                {codeMenu === "plus" && <div className="code-plus-menu">
                  <button onClick={chooseCodeFiles}><Paperclip size={16} /> {t("addFilesOrPhotos")} <span>Ctrl+U</span></button>
                  <button onClick={chooseCodeFolder}><Folder size={16} /> {t("addFolder")}</button>
                  <button className="disabled" disabled><GitBranch size={16} /> {t("importGitHub")}</button>
                  <button onClick={() => { setPrompt("/"); setCodeMenu(null); }}><Code size={16} /> {t("slashCommands")}</button>
                  <button onClick={() => { setDirectoryModal("Connectors"); setCodeMenu(null); }}><SquaresFour size={16} /> {t("addConnectors")}</button>
                  <button onClick={() => { setDirectoryModal("Plugins"); setCodeMenu(null); }}><Plug size={16} /> {t("addPlugins")}</button>
                </div>}
                <span className="shortcut">{t("enterToSendHint")}</span>
                <Select value={model} setValue={setModel} options={["deepseek-v4-flash", "deepseek-v4-pro"]} />
                <EffortMenu value={effort} setValue={setEffort} />
              </div>
            </div>
          )}
          </div>
        ) : <CodeDashboard range={range} setRange={setRange} statsView={statsView} setStatsView={setStatsView} stats={coreStats} online={coreOnline} configured={coreConfigured} error={coreError} busy={coreBusy} response="" />
      ) : (
        workPage === "Home" ? <WorkDashboard prompt={prompt} setPrompt={setPrompt} sendPrompt={sendPrompt} queuePrompt={queuePrompt} stopResponse={stopResponse} queuedPrompt={queuedPrompt} model={model} setModel={setModel} items={workItems} setItems={setWorkItems} sent={sent} conversation={workConversation} busy={coreBusy} enterToSend={settings.enterToSend} />
          : workPage === "Projects" ? <ProjectsPage projects={projects} setProjects={setProjects} openModal={setModal} chooseFolder={chooseFolder} openPath={openLocalPath} setWorkPage={setWorkPage} setSelectedWorkdir={setSelectedWorkdir} />
            : workPage === "Scheduled" ? <ScheduledPage scheduled={scheduled} setScheduled={setScheduled} keepAwake={keepAwake} setKeepAwake={setKeepAwake} openModal={setModal} showNotice={showNotice} />
              : workPage === "Live artifacts" ? <ArtifactsPage artifacts={artifacts} setArtifacts={setArtifacts} openModal={setModal} />
                : <WorkDashboard prompt={prompt} setPrompt={setPrompt} sendPrompt={sendPrompt} queuePrompt={queuePrompt} stopResponse={stopResponse} queuedPrompt={queuedPrompt} model={model} setModel={setModel} items={workItems} setItems={setWorkItems} sent={sent} conversation={workConversation} busy={coreBusy} enterToSend={settings.enterToSend} />
      )}
    </article>
      </section>}
      {modal && <CreateModal type={modal} chooseFolder={chooseFolder} close={() => setModal(null)} onCreate={(item) => {
        if (modal === "project") setProjects((current) => [{ id: Date.now(), ...item, meta: item.path || "Local project", updatedAt: Date.now() }, ...current]);
        if (modal === "scheduled") setScheduled((current) => [{ id: Date.now(), ...item, enabled: true, lastRun: "", meta: item.schedule }, ...current]);
        if (modal === "artifact") setArtifacts((current) => [{ id: Date.now(), ...item, versions: [], meta: "Live · Updated just now", updatedAt: Date.now() }, ...current]);
        setModal(null);
      }} />}
      {renameTarget && <RenameSessionModal session={renameTarget} close={() => setRenameTarget(null)} save={(title) => renameRecent(renameTarget.id, title)} />}
      {directoryModal && <DirectoryModal initialSection={directoryModal} close={() => setDirectoryModal(null)} />}
      {resetOpen && <ResetModal close={() => setResetOpen(false)} reset={beginResetCountdown} />}
      {notice && <div className="app-notice"><Check size={17} weight="bold" /> {notice}</div>}
    </main>
  );
}

function LoadingScreen({ error, onRetry, onConfigure }) {
  return <main className="loading-screen">
    <div className="loading-orbit"><CircleNotch size={38} weight="bold" /></div>
    <strong>{error ? t("startupFailed") : t("starting")}</strong>
    <p>{error || t("checkingCore")}</p>
    {error && <div className="loading-actions"><button onClick={onRetry}>{t("checkAgain")}</button><button onClick={onConfigure}>{t("updateApiKey")}</button></div>}
  </main>;
}

function SetupScreen({ onContinue }) {
  const [apiKey, setApiKey] = useState("");
  const [visible, setVisible] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function submit(event) {
    event.preventDefault();
    if (!apiKey.trim()) return;
    try {
      setSaving(true);
      setError("");
      await onContinue(apiKey);
    } catch (submitError) {
      setError(submitError.message);
      setSaving(false);
    }
  }

  return <main className="setup-screen">
    <div className="setup-mark"><Sparkle size={22} weight="fill" /></div>
    <section className="setup-content">
      <span className="setup-kicker">NextAgent for DeepSeek</span>
      <h1>{t("welcome")}</h1>
      <p>{t("setupDesc")}</p>
      <form className="setup-card" onSubmit={submit}>
        <span className="setup-icon"><Key size={24} weight="duotone" /></span>
        <div>
          <strong>{t("apiKey")}</strong>
          <small>{t("keyStoredLocal")}</small>
        </div>
        <label className="setup-input">
          <input
            autoFocus
            disabled={saving}
            type={visible ? "text" : "password"}
            value={apiKey}
            onChange={(event) => setApiKey(event.target.value)}
            placeholder="sk-..."
            autoComplete="off"
          />
          <button type="button" aria-label={visible ? t("hideKey") : t("showKey")} onClick={() => setVisible(!visible)}>
            {visible ? <EyeSlash size={18} /> : <Eye size={18} />}
          </button>
        </label>
        {error && <p className="setup-error">{error}</p>}
        <button className="setup-continue" disabled={saving || !apiKey.trim()}>
          <Sparkle size={18} weight="fill" /> {saving ? t("checking") : t("continue")}
        </button>
      </form>
      <small className="setup-footnote">{t("keyNeverLeaves")}</small>
    </section>
  </main>;
}

function CodeDashboard({ range, setRange, statsView, setStatsView, stats, online, configured, error, busy, response }) {
  const rangeDays = range === "7d" ? 7 : range === "30d" ? 30 : 140;
  const dailyTokens = new Map();
  const localDayKey = (date) => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
  stats.rounds.forEach((round) => {
    const timestamp = Number(round.timestamp);
    const date = Number.isFinite(timestamp) ? new Date(timestamp * 1000) : new Date();
    const key = localDayKey(date);
    dailyTokens.set(key, (dailyTokens.get(key) || 0) + (round.prompt_tokens || 0) + (round.completion_tokens || 0));
  });
  const today = new Date();
  today.setHours(12, 0, 0, 0);
  const chartEnd = new Date(today);
  chartEnd.setDate(today.getDate() + (6 - today.getDay()));
  const activity = Array.from({ length: 140 }, (_, index) => {
    const date = new Date(chartEnd);
    date.setDate(chartEnd.getDate() - (139 - index));
    const dayOffset = Math.round((today - date) / 86_400_000);
    const tokens = dayOffset >= 0 && dayOffset < rangeDays ? dailyTokens.get(localDayKey(date)) || 0 : 0;
    const level = tokens > 100000 ? 3 : tokens > 20000 ? 2 : tokens > 0 ? 1 : 0;
    return { date: localDayKey(date), tokens, level };
  });
  const tokenStats = [
    [t("sessions"), formatNumber(stats.sessions)],
    [t("messages"), formatNumber(stats.messages)],
    [t("totalTokens"), formatNumber(stats.total_tokens)],
    [t("promptTokens"), formatNumber(stats.prompt_tokens)],
    [t("outputTokens"), formatNumber(stats.completion_tokens)],
    [t("cacheHit"), `${Math.round(stats.avg_hit_rate * 100)}%`],
    [t("cachedTokens"), formatNumber(stats.cache_hit_tokens)],
    [t("saved"), `$${stats.saved_cost.toFixed(4)}`],
  ];
  const modelTotal = Object.values(stats.model_usage || {}).reduce((sum, value) => sum + value, 0);
  const modelUsage = Object.entries(stats.model_usage || {}).map(([name, tokens]) => {
    const percentage = modelTotal ? Math.round((tokens / modelTotal) * 100) : 0;
    return [name, `${percentage}%`, percentage];
  });
  return (
    <section className="code-dashboard">
      <div className="code-heading"><Sparkle size={28} weight="fill" /><h1>{t("whatsNext")}</h1><span className={`core-badge ${online && configured ? "online" : ""}`}>{busy ? t("coreRunning") : online && configured ? t("coreConnected") : online ? t("apiKeyNeeded") : t("coreOffline")}</span></div>
      {(error || response) && <div className={`core-message ${error ? "error" : ""}`}><strong>{error ? t("coreError") : t("latestResponse")}</strong><p>{error || response}</p></div>}
      <div className="usage-card">
        <div className="usage-toolbar">
          <div>{[t("overview"), t("models")].map((item) => <button key={item} className={statsView === item ? "active" : ""} onClick={() => setStatsView(item)}>{item}</button>)}</div>
          <div>{["All", "30d", "7d"].map((item) => <button key={item} className={range === item ? "active" : ""} onClick={() => setRange(item)}>{item}</button>)}</div>
        </div>
        {statsView === t("overview") ? (
          <>
            <div className="stats-grid">{tokenStats.map(([label, value]) => <div key={label}><span>{label}</span><strong>{value}</strong></div>)}</div>
            <div className="heatmap" aria-label={`Daily token activity for ${range}`}>{activity.map((day) => <span key={day.date} data-level={day.level} title={`${day.date}: ${formatNumber(day.tokens)} tokens`} />)}</div>
            <p>{t("statsParagraph", formatNumber(stats.total_tokens), Math.round(stats.avg_hit_rate * 100))}</p>
          </>
        ) : (
          <div className="model-usage">
            {(modelUsage.length ? modelUsage : [[t("noModelActivity"), "0%", 0]]).map(([name, value, width]) => (
              <div key={name}><span>{name}</span><strong>{value}</strong><i><b style={{ width: `${width}%` }} /></i></div>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

function CodeConversation({ conversation }) {
  const scrollRef = useRef(null);
  const turns = conversationTurns(conversation);
  const lastTurn = turns[turns.length - 1];

  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el) return undefined;
    const scroll = () => { el.scrollTop = el.scrollHeight; };
    scroll();
    const frame = requestAnimationFrame(() => requestAnimationFrame(scroll));
    return () => cancelAnimationFrame(frame);
  }, [turns.length, lastTurn?.response, lastTurn?.status]);

  return <section className="code-conversation" ref={scrollRef}>
    <header><Monitor size={17} /><strong>{conversation.title}</strong><CaretDown size={14} /></header>
    <div className="code-conversation-feed">
      {turns.map((turn, index) => {
        const thinking = turn.status === "thinking";
        return <div className="conversation-turn" key={`${index}-${turn.title}`}>
          <div className="user-message">{turn.title}</div>
          <ThoughtPanel variant="code" turn={turn} thinking={thinking} />
          <div className="assistant-answer"><DeepSeekWhale working={thinking} />{thinking ? <p className="thinking-copy">{t("deepseekInspecting")}</p> : <MarkdownText text={turn.response} />}</div>
        </div>;
      })}
    </div>
  </section>;
}

function WorkDashboard({ prompt, setPrompt, sendPrompt, queuePrompt, stopResponse, queuedPrompt, model, setModel, items, setItems, sent, conversation, busy, enterToSend }) {
  if (conversation) {
    return <WorkConversation conversation={conversation} prompt={prompt} setPrompt={setPrompt} sendPrompt={sendPrompt} queuePrompt={queuePrompt} stopResponse={stopResponse} queuedPrompt={queuedPrompt} model={model} setModel={setModel} busy={busy} enterToSend={enterToSend} />;
  }
  return (
    <section className="work-dashboard">
      <div className="dot-field" />
      <div className="work-content">
        <div className="work-heading"><Sparkle size={34} weight="fill" /><div><h1>{sent ? t("conversationStarted") : t("whatCanIHelp")}</h1><p>{t("homeDesc")}</p></div></div>
        <div className="work-composer">
          <textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} onKeyDown={(event) => {
            if (enterToSend && event.key === "Enter" && !event.shiftKey) { event.preventDefault(); sendPrompt(); }
          }} placeholder={t("howCanIHelp")} />
          <button className="attach" aria-label={t("attachContext")}><Plus size={22} /></button>
          <button className="work-send" disabled={!prompt.trim() || busy} onClick={sendPrompt} aria-label={t("sendTask")}><ArrowUp size={19} weight="bold" /></button>
          <div className="work-composer-footer"><span><Tray size={18} /> {t("workInProject")}</span><Select value={model} setValue={setModel} options={["deepseek-v4-flash", "deepseek-v4-pro"]} /></div>
        </div>
        <div className="active-header"><span>{t("active")}</span><button onClick={() => setItems((current) => current.filter((item) => item.meta !== t("active") && item.meta !== "Now"))}>{t("clearActive")}</button></div>
        <div className="active-list">
          {items.filter((item) => item.meta === t("active") || item.meta === "Now").map((item) => (
            <button key={item.id}><span className="active-task-dot" /><span><strong>{item.title}</strong><small>{item.meta === "Now" ? t("justNow") : t("inProgress")}</small></span><Timer size={17} /></button>
          ))}
        </div>
      </div>
    </section>
  );
}

function DeepSeekWhale({ working = false, swimming = false, className = "" }) {
  return <span className={`deepseek-whale ${working ? "working" : ""} ${swimming ? "swimming" : ""} ${className}`} aria-label="DeepSeek" aria-hidden="true">
    <img src="/deepseek-whale.svg" alt="" />
    <span className="whale-bubble bubble-one" />
    <span className="whale-bubble bubble-two" />
  </span>;
}

function WorkConversation({ conversation, prompt, setPrompt, sendPrompt, queuePrompt, stopResponse, queuedPrompt, model, setModel, busy, enterToSend }) {
  const scrollRef = useRef(null);
  const turns = conversationTurns(conversation);
  const lastTurn = turns[turns.length - 1];

  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el) return undefined;
    const scroll = () => { el.scrollTop = el.scrollHeight; };
    scroll();
    const frame = requestAnimationFrame(() => requestAnimationFrame(scroll));
    return () => cancelAnimationFrame(frame);
  }, [turns.length, lastTurn?.response, lastTurn?.status]);

  return <section className="work-conversation chat-only">
    <div className="conversation-main">
      <header className="conversation-title"><strong>{conversation.title}</strong><CaretDown size={16} /></header>
      <div className="conversation-scroll" ref={scrollRef}>
        <div className="conversation-feed">
          {turns.map((turn, index) => {
            const turnThinking = turn.status === "thinking";
            return <div className="conversation-turn" key={`${index}-${turn.title}`}>
              <div className="user-message">{turn.title}</div>
              <div className="assistant-turn">
                <ThoughtPanel variant="work" turn={turn} thinking={turnThinking} />
                <div className="assistant-answer">
                  <DeepSeekWhale working={turnThinking} />
                  {turnThinking ? <p className="thinking-copy">{t("thinking")}</p> : <MarkdownText text={turn.response} />}
                </div>
              </div>
            </div>
          })}
        </div>
      </div>
      <div className="conversation-composer">
        <textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} onKeyDown={(event) => {
          if (enterToSend && event.key === "Enter" && !event.shiftKey) { event.preventDefault(); busy ? queuePrompt() : sendPrompt(); }
        }} placeholder={t("writeMessage")} />
        {queuedPrompt && <div className="queued-message"><span>{t("queued")}</span>{queuedPrompt}</div>}
        <div className="conversation-actions">
          <div><button className="conversation-attach" aria-label={t("attachFiles")}><Folder size={19} /><Plus size={12} /></button><button className="conversation-plus" aria-label={t("moreOptions")}><Plus size={21} /></button></div>
          <div><Select value={model} setValue={setModel} options={["deepseek-v4-flash", "deepseek-v4-pro"]} />{busy && <button className="conversation-stop" onClick={stopResponse} aria-label={t("stopResponse")}><span /></button>}<button className={`conversation-send ${busy ? "queue" : ""}`} disabled={!prompt.trim()} onClick={busy ? queuePrompt : sendPrompt}>{busy ? <><ArrowLeft size={17} weight="bold" /> {t("queue")}</> : <ArrowUp size={18} weight="bold" />}</button></div>
        </div>
      </div>
    </div>
  </section>;
}

function ThoughtPanel({ variant, turn, thinking }) {
  const isCodeTrace = variant === "code";
  const title = thinking ? (isCodeTrace ? t("working") : t("thinking")) : turn.status === "failed" ? t("taskFailed") : t("completed");
  if (!isCodeTrace) {
    return <details className="thought-panel thought-panel-compact">
      <summary>{title}<CaretDown size={14} /></summary>
      <div className="thought-steps">
        {dsworkThoughts(turn, thinking).map((step, index) => <span key={`${step}-${index}`}><Check size={13} /> {step}</span>)}
      </div>
    </details>;
  }
  const items = codeTraceItems(turn, thinking);
  return <details className="thought-panel thought-panel-code">
    <summary>{title}<CaretDown size={14} /></summary>
    <div className="trace-list">
      {items.map((event, index) => (
        <div className={`trace-item ${event.type === "tool" ? "tool-event" : "stage-event"} ${event.status || ""}`} key={`${traceLabel(event)}-${index}`}>
          <span className="trace-dot">{event.type === "tool" ? <Wrench size={13} /> : <Check size={12} />}</span>
          <div>
            <strong>{event.type === "tool" ? t("traceTool", event.name || t("toolCall")) : traceLabel(event)}</strong>
            {event.detail && <p>{event.detail}</p>}
            {event.arguments && <code>{event.arguments}</code>}
            {event.result && <small>{event.result}</small>}
          </div>
        </div>
      ))}
    </div>
  </details>;
}

function MarkdownText({ text = "" }) {
  const lines = text.replace(/\r/g, "").split("\n");
  const blocks = [];
  let list = [];
  const flushList = () => {
    if (!list.length) return;
    blocks.push(<ul key={`list-${blocks.length}`}>{list.map((item, index) => <li key={index}>{inlineMarkdown(item)}</li>)}</ul>);
    list = [];
  };
  lines.forEach((line) => {
    const trimmed = line.trim();
    const bullet = trimmed.match(/^[-*]\s+(.+)/);
    if (bullet) {
      list.push(bullet[1]);
      return;
    }
    flushList();
    if (!trimmed) return;
    if (trimmed.startsWith("### ")) blocks.push(<h4 key={blocks.length}>{inlineMarkdown(trimmed.slice(4))}</h4>);
    else if (trimmed.startsWith("## ")) blocks.push(<h3 key={blocks.length}>{inlineMarkdown(trimmed.slice(3))}</h3>);
    else if (trimmed.startsWith("# ")) blocks.push(<h2 key={blocks.length}>{inlineMarkdown(trimmed.slice(2))}</h2>);
    else blocks.push(<p key={blocks.length}>{inlineMarkdown(trimmed)}</p>);
  });
  flushList();
  return <div className="markdown-answer">{blocks}</div>;
}

function inlineMarkdown(text) {
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).filter(Boolean).map((part, index) => {
    if (part.startsWith("**")) return <strong key={index}>{part.slice(2, -2)}</strong>;
    if (part.startsWith("`")) return <code key={index}>{part.slice(1, -1)}</code>;
    return part;
  });
}

function CodePopover({ open, onToggle, trigger, children }) {
  return <span className={`code-popover ${open ? "open" : ""}`}>
    <button type="button" onClick={onToggle}>{trigger}</button>
    {open && <span className="code-popover-panel">{children}</span>}
  </span>;
}

function EffortMenu({ value, setValue }) {
  const [open, setOpen] = useState(false);
  const levels = ["Low", "Medium", "High", "Max"];
  const [position, setPosition] = useState(Math.max(0, levels.indexOf(value)));
  useEffect(() => {
    const next = levels.indexOf(value);
    if (next >= 0) setPosition(next);
  }, [value]);
  const activeLevel = levels[Math.round(position)];
  const pixelProgress = Math.max(0, Math.min(1, position - 2));
  const pixelRightEdge = (2 + pixelProgress) / 3;
  const pixelLeftEdge = Math.max(0, pixelRightEdge - pixelProgress);
  const gridColumns = 66;
  const gridRows = 5;
  const gridCells = useMemo(() => Array.from({ length: gridColumns * gridRows }, (_, index) => ({
    index,
    column: index % gridColumns,
    row: Math.floor(index / gridColumns),
    delay: `${-((index * 37) % 1900)}ms`,
    duration: `${920 + ((index * 71) % 1100)}ms`,
  })), []);
  function commitPosition(event) {
    const currentPosition = Number(event?.currentTarget?.value ?? position);
    const snapped = Math.round(currentPosition);
    setPosition(snapped);
    setValue(levels[snapped]);
  }
  return <span className={`effort-menu ${open ? "open" : ""}`}>
    <button type="button" onClick={() => setOpen(!open)}>{value}</button>
    {open && <span className="effort-panel">
      <span>{t("effort")} <strong>{activeLevel}</strong><Info size={14} /></span>
      <div><small>{t("faster")}</small><small>{t("smarter")}</small></div>
      <span
        className={`effort-track ${position > 2 ? "pixel-active" : ""} ${position > 2.985 ? "max-energy" : ""}`}
        style={{
          "--effort-position": `${(position / 3) * 100}%`,
        }}
      >
        <span className="effort-pixels" aria-hidden="true">
          {gridCells.map((cell) => <i
              key={cell.index}
              className="effort-pixel"
              style={{
                "--pixel-opacity": (() => {
                  const x = cell.column / (gridColumns - 1);
                  if (x < pixelLeftEdge || x > pixelRightEdge || pixelProgress === 0) return 0;
                  const localProgress = (x - pixelLeftEdge) / Math.max(.001, pixelRightEdge - pixelLeftEdge);
                  return Math.max(.02, Math.min(.92, localProgress ** 1.7));
                })(),
                "--pixel-delay": cell.delay,
                "--pixel-duration": cell.duration,
              }}
            />)}
        </span>
        <input
          aria-label="Effort level"
          type="range"
          min="0"
          max="3"
          step="0.001"
          value={position}
          onChange={(event) => setPosition(Number(event.target.value))}
          onInput={(event) => setPosition(Number(event.currentTarget.value))}
          onMouseUp={commitPosition}
          onPointerUp={commitPosition}
          onKeyUp={commitPosition}
        />
        <span className="effort-knob" />
        {levels.map((level, index) => <i key={level} className={`effort-dot ${Math.abs(position - index) < 0.2 ? "active" : ""}`} />)}
      </span>
    </span>}
  </span>;
}

function SlashCommandMenu({ commands, onSelect }) {
  const [hovered, setHovered] = useState(commands[0] || null);
  return <div className="slash-command-menu">
    <div className="slash-command-list">
      {commands.length ? commands.map(([name, description]) => <button key={name} onMouseEnter={() => setHovered([name, description])} onClick={() => onSelect(name)}>
        <span>{name}</span>
      </button>) : <span className="slash-empty">{t("noMatchingCmds")}</span>}
    </div>
    <div className="slash-filter"><span>/</span><span>{t("typeToFilter")}</span></div>
    {hovered && <div className="slash-command-help"><strong>/{hovered[0]}</strong><span>{hovered[1]}</span></div>}
  </div>;
}

function Select({ value, setValue, options, className = "" }) {
  const [open, setOpen] = useState(false);
  return <span className={`menu-select ${className} ${open ? "open" : ""}`}>
    <button type="button" className="menu-select-trigger" aria-expanded={open} onClick={() => setOpen(!open)}>{value}<CaretDown size={13} /></button>
    {open && <span className="menu-select-popover">{options.map((option) => <button type="button" key={option} className={value === option ? "selected" : ""} onClick={() => { setValue(option); setOpen(false); }}>{option}{value === option && <Check size={14} />}</button>)}</span>}
  </span>;
}

function DirectoryModal({ initialSection, close }) {
  const [section, setSection] = useState(initialSection);
  const [search, setSearch] = useState("");
  const sectionLabel = section === "Plugins" ? t("plugins") : t("connectors");
  return <div className="directory-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) close(); }}>
    <section className="directory-modal">
      <header><h2>{t("directory")}</h2><button aria-label={t("closeDirectory")} onClick={close}><X size={16} /></button></header>
      <div className="directory-toolbar">
        <nav>
          <button className={section === "Plugins" ? "selected" : ""} onClick={() => setSection("Plugins")}><Plug size={15} /> {t("plugins")}</button>
          <button className={section === "Connectors" ? "selected" : ""} onClick={() => setSection("Connectors")}><SquaresFour size={15} /> {t("connectors")}</button>
        </nav>
        <label><MagnifyingGlass size={15} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder={t("searchSection", sectionLabel)} /></label>
      </div>
      <div className="directory-empty">
        <strong>{search ? t("noMatch", sectionLabel, search) : t("notAvailable", sectionLabel)}</strong>
        <p>{section === "Plugins" ? t("pluginsDesc") : t("connectorsDesc")}</p>
      </div>
    </section>
  </div>;
}

function PageHeader({ title, description, action, onAction, sort, onSort }) {
  return <div className="page-header"><div><h1>{title}</h1>{description && <p>{description}</p>}</div><div className="page-actions">{sort && <button className="sort-button" onClick={onSort}>{t("sortBy")} <strong>{sort}</strong><CaretDown size={15} /></button>}<button className="primary-button" onClick={onAction}>{action}<Plus size={15} /></button></div></div>;
}

function SearchBar({ placeholder, value, setValue }) {
  return <label className="page-search"><MagnifyingGlass size={19} /><input value={value} onChange={(event) => setValue(event.target.value)} placeholder={placeholder} />{value && <button onClick={() => setValue("")}><X size={15} /></button>}</label>;
}

function ProjectsPage({ projects, setProjects, openModal, openPath, setWorkPage, setSelectedWorkdir }) {
  const [search, setSearch] = useState("");
  const [ascending, setAscending] = useState(false);
  const visible = projects.filter((item) => item.name.toLowerCase().includes(search.toLowerCase())).sort((a, b) => ascending ? a.name.localeCompare(b.name) : b.id - a.id);
  const remove = (id) => setProjects((current) => current.filter((item) => item.id !== id));
  const start = (item) => { setSelectedWorkdir(item.path); setWorkPage("Home"); };
  return <section className="feature-page"><PageHeader title={t("projects")} action={t("newProject")} sort={ascending ? t("name") : t("recentActivity")} onSort={() => setAscending(!ascending)} onAction={() => openModal("project")} /><SearchBar placeholder={t("searchProjects")} value={search} setValue={setSearch} />{projects.length ? <ItemGrid items={visible} icon={Folder} emptyLabel={t("noMatchingProjects")} actions={(item) => <><button onClick={() => start(item)}>{t("newTask")}</button><button onClick={() => openPath(item.path)}>{t("openFolder")}</button><button className="danger" onClick={() => remove(item.id)}>{t("delete")}</button></>} /> : <EmptyState icon={SquaresFour} title={t("startProjectTitle")} body={t("startProjectBody")} action={t("newProject")} onAction={() => openModal("project")} />}</section>;
}

function ScheduledPage({ scheduled, setScheduled, keepAwake, setKeepAwake, openModal, showNotice }) {
  const [search, setSearch] = useState("");
  const [ascending, setAscending] = useState(false);
  function addTemplate(kind) {
    const daily = kind === "daily";
    const name = daily ? t("dailyBrief") : t("weeklyReview");
    const schedule = daily ? "Daily at 9:00 AM" : "Fridays at 4:00 PM";
    setScheduled((current) => [{ id: Date.now(), name, prompt: name, schedule, enabled: true, lastRun: "", meta: schedule }, ...current]);
  }
  function update(id, changes) { setScheduled((current) => current.map((item) => item.id === id ? { ...item, ...changes } : item)); }
  async function run(item) {
    update(item.id, { meta: t("runningNow") });
    try {
      await coreApi.chat([{ role: "user", content: item.prompt || item.name }], "deepseek-v4-flash", `scheduled-${item.id}`);
      update(item.id, { lastRun: new Date().toLocaleString(), meta: t("lastRan", new Date().toLocaleTimeString()) });
      showNotice(t("runNotice", item.name));
    } catch (error) {
      update(item.id, { meta: t("failedWith", error.message) });
    }
  }
  const visible = scheduled.filter((item) => item.name.toLowerCase().includes(search.toLowerCase())).sort((a, b) => ascending ? a.name.localeCompare(b.name) : b.id - a.id);
  return <section className="feature-page"><PageHeader title={t("scheduled")} description={<><span>{t("scheduledDesc").split("/schedule")[0]}</span><code>/schedule</code><span>{t("scheduledDesc").split("/schedule")[1]}</span></>} action={t("newTask")} sort={ascending ? t("name") : t("nextRun")} onSort={() => setAscending(!ascending)} onAction={() => openModal("scheduled")} /><SearchBar placeholder={t("searchScheduledTasks")} value={search} setValue={setSearch} /><div className="awake-banner"><span><Info size={18} /> {t("awakeOnly")}</span><button className={`toggle ${keepAwake ? "on" : ""}`} onClick={() => setKeepAwake(!keepAwake)}><Sun size={18} /> {t("keepAwake")} <i /></button></div>{scheduled.length ? <ItemGrid items={visible} icon={CalendarBlank} emptyLabel={t("noMatchingScheduledTasks")} status={(item) => item.enabled ? t("enabled") : t("paused")} actions={(item) => <><button onClick={() => run(item)}>{t("runNow")}</button><button onClick={() => update(item.id, { enabled: !item.enabled })}>{item.enabled ? t("pause") : t("enable")}</button><button className="danger" onClick={() => setScheduled((current) => current.filter((entry) => entry.id !== item.id))}>{t("delete")}</button></>} /> : <EmptyState icon={Timer} title={t("createFirst", t("scheduledLabel"))} actions={<><button onClick={() => addTemplate("daily")}><Coffee size={18} /> {t("dailyBrief")}</button><button onClick={() => addTemplate("weekly")}><Check size={18} /> {t("weeklyReview")}</button></>} />}</section>;
}

function ArtifactsPage({ artifacts, setArtifacts, openModal }) {
  const [active, setActive] = useState(null);
  function remove(id) { setArtifacts((current) => current.filter((item) => item.id !== id)); }
  function refresh(item) {
    setArtifacts((current) => current.map((entry) => entry.id === item.id ? { ...entry, versions: [...(entry.versions || []), entry.html], updatedAt: Date.now(), meta: "Live · Updated just now" } : entry));
  }
  return <section className="feature-page"><PageHeader title={t("liveArtifacts")} description={t("liveArtifactsDesc")} action={t("newArtifact")} onAction={() => openModal("artifact")} />{artifacts.length ? <ItemGrid items={artifacts} icon={Broadcast} emptyLabel={t("noMatchingArtifacts")} actions={(item) => <><button onClick={() => setActive(item)}>{t("openLiveView")}</button><button onClick={() => refresh(item)}>{t("refresh")}</button><button className="danger" onClick={() => remove(item.id)}>{t("delete")}</button></>} /> : <EmptyState icon={Package} title={t("createFirstArtifact")} action={t("whatNeedsAttention")} onAction={() => openModal("artifact")} />}{active && <ArtifactModal artifact={artifacts.find((item) => item.id === active.id) || active} close={() => setActive(null)} save={(html) => setArtifacts((current) => current.map((item) => item.id === active.id ? { ...item, versions: [...(item.versions || []), item.html], html, updatedAt: Date.now(), meta: "Live · Updated just now" } : item))} />}</section>;
}

function CustomizePage({ onClose, navOpen, skills, setSkills, connectors, setConnectors, plugins, setPlugins, showNotice }) {
  const [section, setSection] = useState("Overview");
  const [editor, setEditor] = useState(null);
  const catalog = ["GitHub workflow", "Release notes", "Frontend polish", "Research assistant"];
  const sectionLabels = { Overview: t("customize"), Skills: t("skills"), Connectors: t("connectors"), Plugins: t("plugins") };
  function togglePlugin(name) {
    setPlugins((current) => current.some((item) => item.name === name) ? current.filter((item) => item.name !== name) : [...current, { id: Date.now(), name, installed: true }]);
  }
  return <section className={`customize-page ${navOpen ? "" : "nav-closed"}`}><aside className="customize-nav"><button onClick={onClose}><ArrowLeft size={16} /> {t("backToWorkspace")}</button><button className={section === "Skills" ? "current" : ""} onClick={() => setSection("Skills")}><Package size={18} /> {t("skills")}</button><button className={section === "Connectors" ? "current" : ""} onClick={() => setSection("Connectors")}><SquaresFour size={18} /> {t("connectors")}</button><div><span>{t("personalPlugins")}</span><button onClick={() => setSection("Plugins")}><Plus size={18} /></button></div><p>{t("giveExpertise")}</p><button className="outline-button" onClick={() => setSection("Plugins")}>{t("browsePlugins")}</button></aside><div className={`customize-main ${section !== "Overview" ? "directory-view" : ""}`}><Wrench size={section === "Overview" ? 72 : 42} /><h1>{section === "Overview" ? t("customizeNextAgent") : sectionLabels[section]}</h1><p>{t("customizeDesc")}</p>{section === "Overview" ? <div className="customize-cards"><button onClick={() => setSection("Connectors")}><SquaresFour size={22} /><span><strong>{t("connectApps")}</strong><small>{t("connectAppsDesc")}</small></span></button><button onClick={() => setEditor("skill")}><Package size={22} /><span><strong>{t("createSkills")}</strong><small>{t("createSkillsDesc")}</small></span></button><button onClick={() => setSection("Plugins")}><Plug size={22} /><span><strong>{t("browsePlugins")}</strong><small>{t("browsePluginsDesc")}</small></span></button></div> : <div className="customize-directory"><div className="directory-heading"><strong>{sectionLabels[section]}</strong><button className="primary-button" onClick={() => section === "Skills" ? setEditor("skill") : section === "Connectors" ? setEditor("connector") : togglePlugin(t("customPlugin"))}><Plus size={15} /> {t("add", sectionLabels[section])}</button></div>{section === "Skills" && skills.map((item) => <DirectoryRow key={item.name} title={item.name} description={item.description || item.trigger || t("localSkill")} />)}{section === "Connectors" && connectors.map((item) => <DirectoryRow key={item.id} title={item.name} description={item.url} enabled={item.enabled !== false} toggle={() => setConnectors((current) => current.map((entry) => entry.id === item.id ? { ...entry, enabled: entry.enabled === false } : entry))} remove={() => setConnectors((current) => current.filter((entry) => entry.id !== item.id))} />)}{section === "Plugins" && catalog.map((name) => <DirectoryRow key={name} title={name} description={t("localPluginDesc")} enabled={plugins.some((item) => item.name === name)} toggle={() => togglePlugin(name)} />)}{((section === "Skills" && !skills.length) || (section === "Connectors" && !connectors.length)) && <div className="filtered-empty">{t("noneYet", sectionLabels[section])}</div>}</div>}</div>{editor && <CustomizeEditor type={editor} close={() => setEditor(null)} save={async (payload) => { if (editor === "skill") { const result = await coreApi.createSkill(payload); setSkills((current) => [...current, result.skill]); showNotice(t("createdSkillNotice", payload.name)); } else { setConnectors((current) => [...current, { id: Date.now(), enabled: true, ...payload }]); showNotice(t("connectedNotice", payload.name)); } setEditor(null); }} />}</section>;
}

function EmptyState({ icon: Icon, title, body, action, onAction, actions }) {
  return <div className="empty-state"><Icon size={88} weight="thin" /><strong>{title}</strong>{body && <p>{body}</p>}<div className="empty-actions">{actions || <button onClick={onAction}>{action}</button>}</div></div>;
}

function ItemGrid({ items, icon: Icon, emptyLabel = "No items", actions, status }) {
  const [expanded, setExpanded] = useState(null);
  if (!items.length) return <div className="filtered-empty">{emptyLabel}</div>;
  return <div className="item-grid">{items.map((item) => <article className={expanded === item.id ? "expanded" : ""} key={item.id}><button className="item-grid-main" onClick={() => setExpanded(expanded === item.id ? null : item.id)}><Icon size={23} /><span><strong>{item.name}</strong><small>{status?.(item) || item.meta}</small></span><CaretDown size={15} /></button>{expanded === item.id && <div className="item-grid-actions">{actions?.(item)}</div>}</article>)}</div>;
}

function CreateModal({ type, close, onCreate, chooseFolder }) {
  const labels = { project: t("projectLabel"), scheduled: t("scheduledLabel"), artifact: t("artifactLabel") };
  const [name, setName] = useState("");
  const [detail, setDetail] = useState(type === "scheduled" ? "Daily at 9:00 AM" : "");
  const [html, setHtml] = useState(t("liveArtifactDefaultHtml"));
  async function pickFolder() { const path = await chooseFolder(); if (path) { setDetail(path); if (!name) setName(path.split(/[\\/]/).pop()); } }
  const submit = () => onCreate(type === "project" ? { name, path: detail } : type === "scheduled" ? { name, prompt: name, schedule: detail } : { name, html });
  return <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) close(); }}><div className="create-modal feature-create-modal"><button className="modal-close" onClick={close}><X size={18} /></button><span className="modal-icon"><Plus size={22} /></span><h2>{t("createLabel", labels[type])}</h2><p>{type === "project" ? t("projectCreateDesc") : type === "scheduled" ? t("scheduledCreateDesc") : t("artifactCreateDesc")}</p><label>{t("name")}<input autoFocus value={name} onChange={(event) => setName(event.target.value)} placeholder={t("nameYour", labels[type])} /></label>{type === "project" && <label>{t("localFolder")}<div className="field-with-button"><input value={detail} readOnly placeholder={t("chooseExistingFolder")} /><button className="outline-button" onClick={pickFolder}>{t("choose")}</button></div></label>}{type === "scheduled" && <label>{t("schedule")}<input value={detail} onChange={(event) => setDetail(event.target.value)} placeholder="Daily at 9:00 AM" /></label>}{type === "artifact" && <label>{t("html")}<textarea value={html} onChange={(event) => setHtml(event.target.value)} /></label>}<div><button className="outline-button" onClick={close}>{t("cancel")}</button><button className="primary-button" disabled={!name.trim() || (type === "project" && !detail)} onClick={submit}>{t("create")}</button></div></div></div>;
}

function ArtifactModal({ artifact, close, save }) {
  const [html, setHtml] = useState(artifact.html || "");
  return <div className="modal-backdrop artifact-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) close(); }}><section className="artifact-modal"><header><div><Broadcast size={20} /><strong>{artifact.name}</strong><small>{t("savedVersions", artifact.versions?.length || 0)}</small></div><button onClick={close}><X size={18} /></button></header><div className="artifact-workbench"><textarea value={html} onChange={(event) => setHtml(event.target.value)} /><iframe title={`${artifact.name} preview`} sandbox="allow-scripts" srcDoc={html} /></div><footer><button className="outline-button" onClick={close}>{t("close")}</button><button className="primary-button" onClick={() => save(html)}>{t("saveNewVersion")}</button></footer></section></div>;
}

function DirectoryRow({ title, description, enabled, toggle, remove }) {
  return <div className="directory-row"><div><strong>{title}</strong><small>{description}</small></div><span>{toggle && <button className={`setting-switch ${enabled ? "on" : ""}`} onClick={toggle}><span /></button>}{remove && <button className="directory-delete" onClick={remove}><Trash size={16} /></button>}</span></div>;
}

function CustomizeEditor({ type, close, save }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [content, setContent] = useState("");
  return <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) close(); }}><form className="create-modal feature-create-modal" onSubmit={(event) => { event.preventDefault(); save(type === "skill" ? { name, description, content, trigger: description } : { name, url: description }); }}><button type="button" className="modal-close" onClick={close}><X size={18} /></button><h2>{type === "skill" ? t("createSkill") : t("addConnector")}</h2><p>{type === "skill" ? t("skillEditorDesc") : t("connectorEditorDesc")}</p><label>{t("name")}<input autoFocus value={name} onChange={(event) => setName(event.target.value)} /></label><label>{type === "skill" ? t("description") : t("connectorUrl")}<input value={description} onChange={(event) => setDescription(event.target.value)} placeholder={type === "skill" ? t("skillPlaceholder") : "https://..."} /></label>{type === "skill" && <label>{t("instructions")}<textarea value={content} onChange={(event) => setContent(event.target.value)} placeholder={t("instructionPlaceholder")} /></label>}<div><button type="button" className="outline-button" onClick={close}>{t("cancel")}</button><button className="primary-button" disabled={!name.trim() || !description.trim() || (type === "skill" && !content.trim())}>{t("save")}</button></div></form></div>;
}

function RenameSessionModal({ session, close, save }) {
  const [name, setName] = useState(session.title);
  return <div className="modal-backdrop rename-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) close(); }}>
    <form className="rename-session-modal" onSubmit={(event) => { event.preventDefault(); if (name.trim()) save(name.trim()); }}>
      <h2>{t("rename")}</h2>
      <input autoFocus value={name} onChange={(event) => setName(event.target.value)} onFocus={(event) => event.target.select()} />
      <div><button type="button" className="outline-button" onClick={close}>{t("cancel")}</button><button type="submit" className="rename-save" disabled={!name.trim()}>{t("save")}</button></div>
    </form>
  </div>;
}

function SettingSwitch({ value, onChange, label }) {
  return <button type="button" aria-label={label} aria-pressed={value} className={`setting-switch ${value ? "on" : ""}`} onClick={() => onChange(!value)}><span /></button>;
}

function SettingChoice({ value, options, onChange }) {
  const labels = {
    Warm: t("warm"),
    White: t("white"),
    "Blue mist": t("blueMist"),
    Comfortable: t("comfortable"),
    Compact: t("compact"),
  };
  return <div className="setting-choice">{options.map((option) => <button key={option} className={value === option ? "selected" : ""} onClick={() => onChange(option)}>{labels[option] || option}</button>)}</div>;
}

function SettingsPage({ settings, setSettings, configured, close }) {
  const [section, setSection] = useState("general");
  const update = (key, value) => setSettings((current) => ({ ...current, [key]: value }));
  const sections = ["general", "privacy", "capabilities", "nextAgent", "collaboration"];
  const descriptions = {
    general: t("settingsGeneralDesc"),
    privacy: t("settingsPrivacyDesc"),
    capabilities: t("settingsCapabilitiesDesc"),
    nextAgent: t("settingsNextAgentDesc"),
    collaboration: t("settingsCollaborationDesc"),
  };

  return <section className="settings-page">
    <aside className="settings-nav">
      <button className="settings-back" onClick={close}><ArrowLeft size={17} /> {t("backToWorkspace")}</button>
      <span>{t("settings")}</span>
      {sections.map((item) => <button key={item} className={section === item ? "current" : ""} onClick={() => setSection(item)}>{t(item)}{item === "collaboration" && <small>{t("comingSoon")}</small>}</button>)}
      <div className="settings-connection"><span className={configured ? "online" : ""} /><div><strong>{t("deepseekConnection")}</strong><small>{configured ? t("connectedLocally") : t("notConfigured")}</small></div></div>
    </aside>
    <div className="settings-content">
      <header><h1>{t(section)}</h1><p>{descriptions[section]}</p></header>
      {section === "general" && <>
        <SettingsGroup title={t("behavior")}>
          <SettingsLine title={t("launchMode")} description={t("launchModeDesc")}><SettingChoice value={settings.launchMode} options={["Dswork", "Code"]} onChange={(value) => update("launchMode", value)} /></SettingsLine>
          <SettingsLine title={t("enterToSend")} description={t("enterToSendDesc")}><SettingSwitch label={t("enterToSend")} value={settings.enterToSend} onChange={(value) => update("enterToSend", value)} /></SettingsLine>
          <SettingsLine title={t("recentDetails")} description={t("recentDetailsDesc")}><SettingSwitch label={t("recentDetails")} value={settings.showRecentDetails} onChange={(value) => update("showRecentDetails", value)} /></SettingsLine>
          <SettingsLine title={t("interfaceLanguage")} description={t("interfaceLanguageDesc")}><b>{t("currentLanguage")}</b></SettingsLine>
        </SettingsGroup>
      </>}
      {section === "privacy" && <>
        <SettingsGroup title={t("localMemory")}>
          <SettingsLine title={t("conversationMemory")} description={t("conversationMemoryDesc")}><SettingSwitch label={t("conversationMemory")} value={settings.conversationMemory} onChange={(value) => update("conversationMemory", value)} /></SettingsLine>
          <SettingsLine title={t("userMemory")} description={t("userMemoryDesc")}><SettingSwitch label={t("userMemory")} value={settings.userMemory} onChange={(value) => update("userMemory", value)} /></SettingsLine>
          <SettingsLine title={t("localTokenStats")} description={t("localTokenStatsDesc")}><SettingSwitch label={t("localTokenStats")} value={settings.localUsageStats} onChange={(value) => update("localUsageStats", value)} /></SettingsLine>
        </SettingsGroup>
        <div className="privacy-note"><Info size={18} /><span><strong>{t("localByDefault")}</strong><small>{t("localByDefaultDesc")}</small></span></div>
      </>}
      {section === "capabilities" && <>
        <SettingsGroup title={t("agent")}>
          <SettingsLine title={t("agentMode")} description={t("agentModeDesc")}><SettingSwitch label={t("agentMode")} value={settings.agentMode} onChange={(value) => update("agentMode", value)} /></SettingsLine>
        </SettingsGroup>
        <SettingsGroup title={t("skillsSettings")} subtitle={t("skillsSettingsDesc")}>
          <div className="skill-settings-list">{capabilitySkills.map(([name, description]) => <div key={name}><span className="skill-symbol"><Package size={17} /></span><span><strong>{name}</strong><small>{description}</small></span><b>{t("activeSkill")}</b></div>)}</div>
        </SettingsGroup>
      </>}
      {section === "nextAgent" && <>
        <SettingsGroup title={t("appearance")}>
          <SettingsLine title={t("background")} description={t("backgroundDesc")}><SettingChoice value={settings.background} options={["Warm", "White", "Blue mist"]} onChange={(value) => update("background", value)} /></SettingsLine>
          <SettingsLine title={t("density")} description={t("densityDesc")}><SettingChoice value={settings.density} options={["Comfortable", "Compact"]} onChange={(value) => update("density", value)} /></SettingsLine>
          <SettingsLine title={t("reduceMotion")} description={t("reduceMotionDesc")}><SettingSwitch label={t("reduceMotion")} value={settings.reduceMotion} onChange={(value) => update("reduceMotion", value)} /></SettingsLine>
        </SettingsGroup>
        <div className={`settings-preview theme-${settings.background.toLowerCase().replace(" ", "-")}`}><Sparkle size={25} weight="fill" /><div><strong>{t("appearancePreview")}</strong><small>{t("appearancePreviewDesc")}</small></div></div>
      </>}
      {section === "collaboration" && <div className="collaboration-placeholder"><SquaresFour size={50} /><h2>{t("collaborationComing")}</h2><p>{t("collaborationDesc")}</p><span>{t("notYetAvailable")}</span></div>}
    </div>
  </section>;
}

function SettingsGroup({ title, subtitle, children }) {
  return <section className="settings-group"><header><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</header>{children}</section>;
}

function SettingsLine({ title, description, children }) {
  return <div className="settings-line"><span><strong>{title}</strong><small>{description}</small></span><div>{children}</div></div>;
}

function ResetModal({ close, reset }) {
  return <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) close(); }}>
    <section className="reset-modal">
      <span className="reset-icon"><Trash size={23} /></span>
      <h2>{t("resetTitle")}</h2>
      <p>{t("resetDesc")}</p>
      <div><button className="outline-button" onClick={close}>{t("cancel")}</button><button className="reset-confirm" onClick={reset}>{t("resetBtn")}</button></div>
    </section>
  </div>;
}

function ResetRelaunchScreen({ seconds, cancel }) {
  return <main className="reset-relaunch-screen">
    <div className="reset-relaunch-orbit">
      <Sparkle size={47} weight="fill" />
      <CircleNotch size={76} weight="regular" />
    </div>
    <h1>{t("relaunching", seconds)}</h1>
    <p>{seconds > 0 ? t("relaunchClearing") : t("relaunchPreparing")}</p>
    {seconds > 0 && <button onClick={cancel}>{t("cancel")}</button>}
  </main>;
}
