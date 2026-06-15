import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  Broadcast,
  CalendarBlank,
  CaretDown,
  Check,
  CircleNotch,
  Coffee,
  Code,
  Command,
  Folder,
  GitBranch,
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
  Wrench,
  X,
} from "@phosphor-icons/react";
import { coreApi } from "./core-api";

const workSessions = [];

const workNav = [
  [Tray, "Projects"],
  [CalendarBlank, "Scheduled"],
  [Broadcast, "Live artifacts"],
];

const slashCommands = [
  ["batch", "Run a group of related tasks with a shared goal."],
  ["code-review", "Review code changes for defects, regressions, and missing tests."],
  ["compact", "Compact the active conversation context."],
  ["context", "Inspect the files and tools currently in context."],
  ["debug", "Reproduce and diagnose a bug before applying a focused fix."],
  ["deep-research", "Research a topic deeply and return a sourced synthesis."],
  ["goal", "Create or update the current long-running goal."],
  ["help", "Show available NextAgent commands and shortcuts."],
  ["init", "Initialize workspace guidance for NextAgent."],
  ["plan", "Enter planning mode before implementation."],
  ["review", "Review the current workspace changes."],
  ["test", "Run the relevant test suite and summarize failures."],
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
  const status = session.status === "running" ? "Running" : session.status === "failed" ? "Failed" : session.model;
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

function startConversation(conversation, title) {
  return {
    title: conversation?.title || title,
    status: "thinking",
    turns: [...conversationTurns(conversation), { title, response: "", status: "thinking" }],
  };
}

function finishConversation(conversation, response, status = "complete") {
  const turns = conversationTurns(conversation);
  return {
    ...conversation,
    status,
    turns: turns.map((turn, index) => index === turns.length - 1 ? { ...turn, response, status } : turn),
  };
}

function chatMessages(conversation) {
  return conversationTurns(conversation).flatMap((turn) => {
    const messages = [{ role: "user", content: turn.title }];
    if (turn.response && turn.status !== "thinking") messages.push({ role: "assistant", content: turn.response });
    return messages;
  });
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
  const [permission, setPermission] = useState("Accept edits");
  const [model, setModel] = useState("deepseek-v4-flash");
  const [effort, setEffort] = useState("High");
  const [selectedWorkdir, setSelectedWorkdir] = useState("");
  const [branch, setBranch] = useState("main");
  const [worktree, setWorktree] = useState(false);
  const [codeMenu, setCodeMenu] = useState(null);
  const [attachedFiles, setAttachedFiles] = useState([]);
  const [directoryModal, setDirectoryModal] = useState(null);
  const [range, setRange] = useState("All");
  const [statsView, setStatsView] = useState("Overview");
  const [sent, setSent] = useState(false);
  const [workPage, setWorkPage] = useState("Home");
  const [modal, setModal] = useState(null);
  const [projects, setProjects] = useState([]);
  const [scheduled, setScheduled] = useState([]);
  const [artifacts, setArtifacts] = useState([]);
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
    setCoreStats(stats);
    setWorkspaceInfo(workspace);
    setSelectedWorkdir((current) => current || workspace.workdir);
    setStateLoaded(true);
    return sessionData.sessions;
  }

  useEffect(() => {
    if (!stateLoaded) return;
    const timer = window.setTimeout(() => {
      coreApi.saveState({ code: sessions, dswork: workItems, archived: archivedItems }).catch(() => {});
    }, 180);
    return () => window.clearTimeout(timer);
  }, [sessions, workItems, archivedItems, stateLoaded]);

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
      if (!isCode) return;
      if (event.ctrlKey && event.key.toLowerCase() === "n") {
        event.preventDefault();
        createItem();
      } else if (event.ctrlKey && event.key.toLowerCase() === "u") {
        event.preventDefault();
        chooseCodeFiles();
      } else if (event.ctrlKey && event.shiftKey && event.key.toLowerCase() === "m") {
        event.preventDefault();
        const modes = ["Ask permissions", "Accept edits", "Plan mode", "Bypass permissions"];
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
      const thinkingConversation = startConversation(activeCodeSession?.conversation, title);
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
          meta: "Running",
          status: "running",
          conversation: thinkingConversation,
        } : item));
        const result = await coreApi.sendMessage(sessionId, title);
        if (generation !== requestGeneration.current) return;
        const response = cleanAgentResponse(result.response);
        setCoreResponse(response);
        setSessions((current) => current.map((item) => item.id === sessionId ? {
          ...sessionFromCore(result.session),
          title: item.title,
          pinned: item.pinned,
          done: item.done,
          conversation: finishConversation(thinkingConversation, response),
        } : item));
        const stats = await coreApi.stats();
        setCoreStats(stats);
        setCoreOnline(true);
      } catch (error) {
        if (generation !== requestGeneration.current) return;
        setCoreError(error.message);
        setSessions((current) => current.map((item) => item.id === sessionId ? {
          ...item,
          meta: "Failed",
          status: "failed",
          conversation: finishConversation(thinkingConversation, error.message, "failed"),
        } : item));
      } finally {
        if (generation === requestGeneration.current) setCoreBusy(false);
      }
    } else {
      let taskId = newItemActive ? null : activeWorkItem?.id;
      const thinkingConversation = startConversation(newItemActive ? null : activeWorkItem?.conversation, title);
      if (!taskId) {
        taskId = `ds-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
        setActiveId(taskId);
        setWorkItems((current) => [{
          id: taskId,
          title,
          meta: "Active",
          conversation: thinkingConversation,
        }, ...current]);
      } else {
        setWorkItems((current) => current.map((item) => item.id === taskId ? {
          ...item,
          title: item.conversation ? item.title : title,
          meta: "Active",
          conversation: thinkingConversation,
        } : item));
      }
      setActiveId(taskId);
      try {
        setCoreBusy(true);
        setCoreError("");
        const result = await coreApi.chat(chatMessages(thinkingConversation), model, taskId);
        if (generation !== requestGeneration.current) return;
        setWorkItems((current) => current.map((item) => item.id === taskId ? {
          ...item,
          meta: "Complete",
          conversation: finishConversation(thinkingConversation, cleanAgentResponse(result.response)),
        } : item));
        const stats = await coreApi.stats();
        setCoreStats(stats);
        setCoreOnline(true);
      } catch (error) {
        if (generation !== requestGeneration.current) return;
        setCoreError(error.message);
        setWorkItems((current) => current.map((item) => item.id === taskId ? {
          ...item,
          meta: "Failed",
          conversation: finishConversation(thinkingConversation, error.message, "failed"),
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
        meta: "Stopped",
        status: "failed",
        conversation: finishConversation(item.conversation, "Response stopped.", "failed"),
      } : item));
    } else {
      setWorkItems((current) => current.map((item) => item.id === activeId ? {
        ...item,
        meta: "Stopped",
        conversation: finishConversation(item.conversation, "Response stopped.", "failed"),
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
    updateRecent(session.id, (item) => ({ ...item, done: !item.done, meta: item.done ? "Complete" : "Done" }));
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

  function RecentItem({ session }) {
    return <div className={`session-row ${recentMenu === session.id ? "menu-open" : ""}`}>
      <button className={!newItemActive && session.id === activeId ? "session active" : "session"} onClick={() => selectRecent(session)}>
        <span className={`session-dot ${session.done ? "done" : ""}`}>{session.done && <Check size={12} weight="bold" />}</span>
        <span className="session-copy"><strong>{session.title}</strong><small>{session.meta}</small></span>
      </button>
      <button className="recent-more" aria-label={`More actions for ${session.title}`} onClick={(event) => {
        event.stopPropagation();
        setRecentMenu(recentMenu === session.id ? null : session.id);
      }}><DotsThreeVertical size={17} weight="bold" /></button>
      {recentMenu === session.id && <div className="recent-menu">
        <button onClick={() => pinRecent(session)}><PushPin size={17} /> {session.pinned ? "Unpin" : "Pin"}</button>
        <button onClick={() => { setRenameTarget(session); setRecentMenu(null); }}><PencilSimple size={17} /> Rename</button>
        <span />
        <button onClick={() => markRecentDone(session)}><Check size={17} /> {session.done ? "Mark active" : "Mark done"}</button>
        <button onClick={() => archiveRecent(session)}><Tray size={17} /> Archive</button>
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

  return (
    <main className={`app-shell ${isCode ? "code-mode" : "work-mode"}`}>
      <header className="topbar">
        <button className="icon-button" aria-label="Toggle sidebar" onClick={() => setSidebarOpen(!sidebarOpen)}><List size={18} /></button>
        <button className="icon-button desktop-only" aria-label="Panel layout" onClick={() => setSidebarOpen(!sidebarOpen)}><SidebarSimple size={18} /></button>
        <button className="icon-button desktop-only" aria-label="Search" onClick={() => document.querySelector(".search-input")?.focus()}><MagnifyingGlass size={18} /></button>
        <span className="topbar-divider" />
        <button className="icon-button muted" aria-label="Back"><ArrowLeft size={18} /></button>
        <button className="icon-button muted" aria-label="Forward"><ArrowRight size={18} /></button>
        <div className="window-title"><Command size={16} weight="fill" /> {customizeOpen ? "Customize" : "NextAgent"}</div>
      </header>

      {customizeOpen ? <CustomizePage onClose={() => setCustomizeOpen(false)} navOpen={sidebarOpen} /> : <section className="workspace">
        <aside className={`sidebar ${sidebarOpen ? "open" : "closed"}`}>
          <div className="mode-switch">
            {["Dswork", "Code"].map((item) => (
              <button key={item} className={mode === item ? "selected" : ""} onClick={() => changeMode(item)}>
                {item === "Code" ? <Code size={16} /> : <SquaresFour size={16} />} {item}
              </button>
            ))}
          </div>

          <button className={`new-session ${newItemActive && (isCode || workPage === "Home") ? "active" : ""} ${!isCode && workPage !== "Home" ? "inactive" : ""}`} onClick={() => {
            if (!isCode) setWorkPage("Home");
            createItem();
          }}><Plus size={17} /> {isCode ? "New session" : "New task"} <span>Ctrl N</span></button>
          {!isCode && workNav.map(([Icon, label]) => <button className={`sidebar-link ${workPage === label ? "current" : ""}`} key={label} onClick={() => setWorkPage(label)}><Icon size={17} /> {label}</button>)}
          <button className="sidebar-link" onClick={openCustomize}><Wrench size={17} /> Customize</button>

          <label className="search-box">
            <MagnifyingGlass size={15} />
            <input className="search-input" value={query} onChange={(event) => setQuery(event.target.value)} placeholder={isCode ? "Search sessions" : "Search tasks"} />
            {query && <button onClick={() => setQuery("")} aria-label="Clear search"><X size={13} /></button>}
          </label>

          {filteredSessions.some((session) => session.pinned) && <><div className="section-title pinned-title"><span>Pinned</span></div>
            <nav className="session-list pinned-list">
              {filteredSessions.filter((session) => session.pinned).map((session) => <RecentItem key={session.id} session={session} />)}
            </nav>
          </>}
          <div className="section-title"><span>Recents</span><SlidersHorizontal size={15} /></div>
          <nav className="session-list">
            {filteredSessions.filter((session) => !session.pinned).map((session) => <RecentItem key={session.id} session={session} />)}
          </nav>
          {pinTip && <div className="pin-tip"><Hand size={20} weight="fill" /><span><strong>Tip:</strong> you can drag chats here to pin them</span></div>}

          <button className="profile">
            <span className="brand-mark"><Sparkle size={16} weight="fill" /></span>
            <span><strong>NextAgent</strong><small>{isCode ? "Code workspace" : "DeepSeek chat"}</small></span>
            <CaretDown size={14} />
          </button>
        </aside>

        <article className="main-panel">
          {isCode ? (
            codeConversation ? <CodeConversation conversation={codeConversation} /> : <CodeDashboard range={range} setRange={setRange} statsView={statsView} setStatsView={setStatsView} stats={coreStats} online={coreOnline} configured={coreConfigured} error={coreError} busy={coreBusy} response="" />
          ) : (
            workPage === "Home" ? <WorkDashboard prompt={prompt} setPrompt={setPrompt} sendPrompt={sendPrompt} queuePrompt={queuePrompt} stopResponse={stopResponse} queuedPrompt={queuedPrompt} model={model} setModel={setModel} items={workItems} setItems={setWorkItems} sent={sent} conversation={workConversation} busy={coreBusy} />
              : workPage === "Projects" ? <ProjectsPage projects={projects} setProjects={setProjects} openModal={setModal} />
                : workPage === "Scheduled" ? <ScheduledPage scheduled={scheduled} setScheduled={setScheduled} keepAwake={keepAwake} setKeepAwake={setKeepAwake} openModal={setModal} />
                  : workPage === "Live artifacts" ? <ArtifactsPage artifacts={artifacts} setArtifacts={setArtifacts} openModal={setModal} />
                    : <WorkDashboard prompt={prompt} setPrompt={setPrompt} sendPrompt={sendPrompt} queuePrompt={queuePrompt} stopResponse={stopResponse} queuedPrompt={queuedPrompt} model={model} setModel={setModel} items={workItems} setItems={setWorkItems} sent={sent} conversation={workConversation} busy={coreBusy} />
          )}

          {isCode && (
            <div className="composer-wrap">
              <div className="context-pills">
                <CodePopover open={codeMenu === "runtime"} onToggle={() => setCodeMenu(codeMenu === "runtime" ? null : "runtime")} trigger={<><Monitor size={15} /> Local</>}>
                  <span className="popover-label">Run environment</span>
                  <button className="selected"><Monitor size={15} /> Local <Check size={14} /></button>
                  <button className="muted-item" disabled>Remote environments coming later</button>
                </CodePopover>
                <CodePopover open={codeMenu === "folder"} onToggle={() => setCodeMenu(codeMenu === "folder" ? null : "folder")} trigger={<><Folder size={15} /> {(selectedWorkdir || workspaceInfo.workdir)?.split(/[\\/]/).pop() || "next-agent"}</>}>
                  <span className="popover-label">Recent</span>
                  <button className="selected"><Folder size={15} /> {(selectedWorkdir || workspaceInfo.workdir)?.split(/[\\/]/).pop()} <Check size={14} /></button>
                  <button onClick={chooseCodeFolder}><Folder size={15} /> Open folder...</button>
                </CodePopover>
                <CodePopover open={codeMenu === "branch"} onToggle={() => setCodeMenu(codeMenu === "branch" ? null : "branch")} trigger={<><GitBranch size={15} /> {branch}</>}>
                  <button className="selected" onClick={() => { setBranch("main"); setCodeMenu(null); }}>main <Check size={14} /></button>
                  <label className="branch-search"><MagnifyingGlass size={14} /><input placeholder="Search branches..." /></label>
                </CodePopover>
                <button className={worktree ? "active-pill" : ""} onClick={() => setWorktree(!worktree)}><span className="worktree-square" /> worktree</button>
                {attachedFiles.length > 0 && <button title={attachedFiles.join("\n")}><Paperclip size={15} /> {attachedFiles.length} file{attachedFiles.length > 1 ? "s" : ""}</button>}
                <button onClick={chooseCodeFolder} aria-label="Add folder to session"><Folder size={15} /><Plus size={11} /></button>
              </div>
              <div className="composer compact-composer">
                <textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); sendPrompt(); }
                }} placeholder="Describe a task or ask a question" />
                <button className="send" disabled={!prompt.trim() || coreBusy} onClick={sendPrompt} aria-label="Send task"><ArrowUp size={17} weight="bold" /></button>
              </div>
              {prompt.startsWith("/") && <SlashCommandMenu commands={filteredSlashCommands} onSelect={(command) => setPrompt(`/${command} `)} />}
              <div className="composer-footer">
                <Select value={permission} setValue={setPermission} options={["Ask permissions", "Accept edits", "Plan mode", "Bypass permissions"]} className="permission-select" />
                <button aria-label="More context options" className="code-plus-trigger" onClick={() => setCodeMenu(codeMenu === "plus" ? null : "plus")}><Plus size={16} /></button>
                {codeMenu === "plus" && <div className="code-plus-menu">
                  <button onClick={chooseCodeFiles}><Paperclip size={16} /> Add files or photos <span>Ctrl+U</span></button>
                  <button onClick={chooseCodeFolder}><Folder size={16} /> Add folder</button>
                  <button className="disabled" disabled><GitBranch size={16} /> Import GitHub issue</button>
                  <button onClick={() => { setPrompt("/"); setCodeMenu(null); }}><Code size={16} /> Slash commands</button>
                  <button onClick={() => { setDirectoryModal("Connectors"); setCodeMenu(null); }}><SquaresFour size={16} /> Add connectors</button>
                  <button onClick={() => { setDirectoryModal("Plugins"); setCodeMenu(null); }}><Plug size={16} /> Add plugins...</button>
                </div>}
                <span className="shortcut">Enter to send · Shift + Enter for new line</span>
                <Select value={model} setValue={setModel} options={["deepseek-v4-flash", "deepseek-v4-pro"]} />
                <EffortMenu value={effort} setValue={setEffort} />
              </div>
            </div>
          )}
        </article>
      </section>}
      {modal && <CreateModal type={modal} close={() => setModal(null)} onCreate={(name) => {
        if (modal === "project") setProjects((current) => [{ id: Date.now(), name, meta: "Created just now" }, ...current]);
        if (modal === "scheduled") setScheduled((current) => [{ id: Date.now(), name, meta: "Runs daily at 9:00 AM" }, ...current]);
        if (modal === "artifact") setArtifacts((current) => [{ id: Date.now(), name, meta: "Live · Updated just now" }, ...current]);
        setModal(null);
      }} />}
      {renameTarget && <RenameSessionModal session={renameTarget} close={() => setRenameTarget(null)} save={(title) => renameRecent(renameTarget.id, title)} />}
      {directoryModal && <DirectoryModal initialSection={directoryModal} close={() => setDirectoryModal(null)} />}
    </main>
  );
}

function LoadingScreen({ error, onRetry, onConfigure }) {
  return <main className="loading-screen">
    <div className="loading-orbit"><CircleNotch size={38} weight="bold" /></div>
    <strong>{error ? "Startup check failed" : "Starting NextAgent"}</strong>
    <p>{error || "Checking core files and DeepSeek API connection..."}</p>
    {error && <div className="loading-actions"><button onClick={onRetry}>Check again</button><button onClick={onConfigure}>Update API key</button></div>}
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
      <h1>Welcome to NextAgent</h1>
      <p>Connect your DeepSeek account to start coding with the local NextAgent core.</p>
      <form className="setup-card" onSubmit={submit}>
        <span className="setup-icon"><Key size={24} weight="duotone" /></span>
        <div>
          <strong>DeepSeek API Key</strong>
          <small>Your key is stored only on this Windows device.</small>
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
          <button type="button" aria-label={visible ? "Hide API key" : "Show API key"} onClick={() => setVisible(!visible)}>
            {visible ? <EyeSlash size={18} /> : <Eye size={18} />}
          </button>
        </label>
        {error && <p className="setup-error">{error}</p>}
        <button className="setup-continue" disabled={saving || !apiKey.trim()}>
          <Sparkle size={18} weight="fill" /> {saving ? "Checking..." : "Continue"}
        </button>
      </form>
      <small className="setup-footnote">Your API key never leaves the local NextAgent core.</small>
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
    ["Sessions", formatNumber(stats.sessions)],
    ["Messages", formatNumber(stats.messages)],
    ["Total tokens", formatNumber(stats.total_tokens)],
    ["Prompt tokens", formatNumber(stats.prompt_tokens)],
    ["Output tokens", formatNumber(stats.completion_tokens)],
    ["Cache hit", `${Math.round(stats.avg_hit_rate * 100)}%`],
    ["Cached tokens", formatNumber(stats.cache_hit_tokens)],
    ["Saved", `$${stats.saved_cost.toFixed(4)}`],
  ];
  const modelTotal = Object.values(stats.model_usage || {}).reduce((sum, value) => sum + value, 0);
  const modelUsage = Object.entries(stats.model_usage || {}).map(([name, tokens]) => {
    const percentage = modelTotal ? Math.round((tokens / modelTotal) * 100) : 0;
    return [name, `${percentage}%`, percentage];
  });
  return (
    <section className="code-dashboard">
      <div className="code-heading"><Sparkle size={28} weight="fill" /><h1>What's up next?</h1><span className={`core-badge ${online && configured ? "online" : ""}`}>{busy ? "Core running" : online && configured ? "Core connected" : online ? "API key needed" : "Core offline"}</span></div>
      {(error || response) && <div className={`core-message ${error ? "error" : ""}`}><strong>{error ? "Core error" : "Latest response"}</strong><p>{error || response}</p></div>}
      <div className="usage-card">
        <div className="usage-toolbar">
          <div>{["Overview", "Models"].map((item) => <button key={item} className={statsView === item ? "active" : ""} onClick={() => setStatsView(item)}>{item}</button>)}</div>
          <div>{["All", "30d", "7d"].map((item) => <button key={item} className={range === item ? "active" : ""} onClick={() => setRange(item)}>{item}</button>)}</div>
        </div>
        {statsView === "Overview" ? (
          <>
            <div className="stats-grid">{tokenStats.map(([label, value]) => <div key={label}><span>{label}</span><strong>{value}</strong></div>)}</div>
            <div className="heatmap" aria-label={`Daily token activity for ${range}`}>{activity.map((day) => <span key={day.date} data-level={day.level} title={`${day.date}: ${formatNumber(day.tokens)} tokens`} />)}</div>
            <p>NextAgent core has processed {formatNumber(stats.total_tokens)} tokens with a {Math.round(stats.avg_hit_rate * 100)}% average prefix-cache hit rate.</p>
          </>
        ) : (
          <div className="model-usage">
            {(modelUsage.length ? modelUsage : [["No model activity yet", "0%", 0]]).map(([name, value, width]) => (
              <div key={name}><span>{name}</span><strong>{value}</strong><i><b style={{ width: `${width}%` }} /></i></div>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

function CodeConversation({ conversation }) {
  return <section className="code-conversation">
    <header><Monitor size={17} /><strong>{conversation.title}</strong><CaretDown size={14} /></header>
    <div className="code-conversation-feed">
      {conversationTurns(conversation).map((turn, index) => {
        const thinking = turn.status === "thinking";
        return <div className="conversation-turn" key={`${index}-${turn.title}`}>
          <div className="user-message">{turn.title}</div>
          <div className="thought-label">{thinking ? "Working" : turn.status === "failed" ? "Task failed" : "Completed"} <CaretDown size={14} /></div>
          <div className="assistant-answer"><DeepSeekWhale working={thinking} />{thinking ? <p className="thinking-copy">DeepSeek is inspecting the workspace and working on your request...</p> : <MarkdownText text={turn.response} />}</div>
        </div>;
      })}
    </div>
  </section>;
}

function WorkDashboard({ prompt, setPrompt, sendPrompt, queuePrompt, stopResponse, queuedPrompt, model, setModel, items, setItems, sent, conversation, busy }) {
  if (conversation) {
    return <WorkConversation conversation={conversation} prompt={prompt} setPrompt={setPrompt} sendPrompt={sendPrompt} queuePrompt={queuePrompt} stopResponse={stopResponse} queuedPrompt={queuedPrompt} model={model} setModel={setModel} busy={busy} />;
  }
  return (
    <section className="work-dashboard">
      <div className="dot-field" />
      <div className="work-content">
        <div className="work-heading"><Sparkle size={34} weight="fill" /><div><h1>{sent ? "Conversation started." : "What can I help with?"}</h1><p>Chat, brainstorm, write, and explore ideas directly with DeepSeek.</p></div></div>
        <div className="work-composer">
          <textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); sendPrompt(); }
          }} placeholder="How can I help you today?" />
          <button className="attach" aria-label="Attach context"><Plus size={22} /></button>
          <button className="work-send" disabled={!prompt.trim() || busy} onClick={sendPrompt} aria-label="Send work task"><ArrowUp size={19} weight="bold" /></button>
          <div className="work-composer-footer"><span><Tray size={18} /> Work in a project</span><Select value={model} setValue={setModel} options={["deepseek-v4-flash", "deepseek-v4-pro"]} /></div>
        </div>
        <div className="active-header"><span>Active</span><button onClick={() => setItems((current) => current.filter((item) => item.meta !== "Active" && item.meta !== "Now"))}>Clear active</button></div>
        <div className="active-list">
          {items.filter((item) => item.meta === "Active" || item.meta === "Now").map((item) => (
            <button key={item.id}><span className="active-task-dot" /><span><strong>{item.title}</strong><small>{item.meta === "Now" ? "Just now" : "In progress"}</small></span><Timer size={17} /></button>
          ))}
        </div>
      </div>
    </section>
  );
}

function DeepSeekWhale({ working = false }) {
  return <span className={`deepseek-whale ${working ? "working" : ""}`} aria-label="DeepSeek">
    <span className="whale-body"><i /><b /></span><span className="whale-wave" />
  </span>;
}

function WorkConversation({ conversation, prompt, setPrompt, sendPrompt, queuePrompt, stopResponse, queuedPrompt, model, setModel, busy }) {
  return <section className="work-conversation chat-only">
    <div className="conversation-main">
      <header className="conversation-title"><strong>{conversation.title}</strong><CaretDown size={16} /></header>
      <div className="conversation-scroll">
        <div className="conversation-feed">
          {conversationTurns(conversation).map((turn, index) => {
            const turnThinking = turn.status === "thinking";
            return <div className="conversation-turn" key={`${index}-${turn.title}`}>
              <div className="user-message">{turn.title}</div>
              <div className="assistant-turn">
                <div className="assistant-answer">
                  <DeepSeekWhale working={turnThinking} />
                  {turnThinking ? <p className="thinking-copy">DeepSeek is thinking...</p> : <MarkdownText text={turn.response} />}
                </div>
              </div>
            </div>
          })}
        </div>
      </div>
      <div className="conversation-composer">
        <textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); busy ? queuePrompt() : sendPrompt(); }
        }} placeholder="Write a message..." />
        {queuedPrompt && <div className="queued-message"><span>Queued</span>{queuedPrompt}</div>}
        <div className="conversation-actions">
          <div><button className="conversation-attach" aria-label="Attach files"><Folder size={19} /><Plus size={12} /></button><button className="conversation-plus" aria-label="More options"><Plus size={21} /></button></div>
          <div><Select value={model} setValue={setModel} options={["deepseek-v4-flash", "deepseek-v4-pro"]} />{busy && <button className="conversation-stop" onClick={stopResponse} aria-label="Stop response"><span /></button>}<button className={`conversation-send ${busy ? "queue" : ""}`} disabled={!prompt.trim()} onClick={busy ? queuePrompt : sendPrompt}>{busy ? <><ArrowLeft size={17} weight="bold" /> Queue</> : <ArrowUp size={18} weight="bold" />}</button></div>
        </div>
      </div>
    </div>
  </section>;
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
      <span>Effort <strong>{activeLevel}</strong><Info size={14} /></span>
      <div><small>Faster</small><small>Smarter</small></div>
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
      </button>) : <span className="slash-empty">No matching commands</span>}
    </div>
    <div className="slash-filter"><span>/</span><span>Type to filter</span></div>
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
  return <div className="directory-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) close(); }}>
    <section className="directory-modal">
      <header><h2>Directory</h2><button aria-label="Close directory" onClick={close}><X size={16} /></button></header>
      <div className="directory-toolbar">
        <nav>
          <button className={section === "Plugins" ? "selected" : ""} onClick={() => setSection("Plugins")}><Plug size={15} /> Plugins</button>
          <button className={section === "Connectors" ? "selected" : ""} onClick={() => setSection("Connectors")}><SquaresFour size={15} /> Connectors</button>
        </nav>
        <label><MagnifyingGlass size={15} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder={`Search ${section.toLowerCase()}...`} /></label>
      </div>
      <div className="directory-empty">
        <strong>{search ? `No ${section.toLowerCase()} match "${search}"` : `No ${section.toLowerCase()} available yet`}</strong>
        <p>{section === "Plugins" ? "Local and organization plugins will appear here when the NextAgent plugin registry is connected." : "Connectors will appear here when their integrations are available."}</p>
      </div>
    </section>
  </div>;
}

function PageHeader({ title, description, action, onAction, sort, onSort }) {
  return <div className="page-header"><div><h1>{title}</h1>{description && <p>{description}</p>}</div><div className="page-actions">{sort && <button className="sort-button" onClick={onSort}>Sort by <strong>{sort}</strong><CaretDown size={15} /></button>}<button className="primary-button" onClick={onAction}>{action}<Plus size={15} /></button></div></div>;
}

function SearchBar({ placeholder, value, setValue }) {
  return <label className="page-search"><MagnifyingGlass size={19} /><input value={value} onChange={(event) => setValue(event.target.value)} placeholder={placeholder} />{value && <button onClick={() => setValue("")}><X size={15} /></button>}</label>;
}

function ProjectsPage({ projects, openModal }) {
  const [search, setSearch] = useState("");
  const [ascending, setAscending] = useState(false);
  const visible = projects.filter((item) => item.name.toLowerCase().includes(search.toLowerCase())).sort((a, b) => ascending ? a.name.localeCompare(b.name) : b.id - a.id);
  return <section className="feature-page"><PageHeader title="Projects" action="New project" sort={ascending ? "Name" : "Recent activity"} onSort={() => setAscending(!ascending)} onAction={() => openModal("project")} /><SearchBar placeholder="Search projects..." value={search} setValue={setSearch} />{projects.length ? <ItemGrid items={visible} icon={Folder} emptyLabel="No matching projects" /> : <EmptyState icon={SquaresFour} title="Looking to start a project?" body="Give NextAgent a folder you already work from" action="New project" onAction={() => openModal("project")} />}</section>;
}

function ScheduledPage({ scheduled, setScheduled, keepAwake, setKeepAwake, openModal }) {
  const [search, setSearch] = useState("");
  const [ascending, setAscending] = useState(false);
  function addTemplate(name) { setScheduled((current) => [{ id: Date.now(), name, meta: name === "Daily brief" ? "Runs daily at 9:00 AM" : "Runs Fridays at 4:00 PM" }, ...current]); }
  const visible = scheduled.filter((item) => item.name.toLowerCase().includes(search.toLowerCase())).sort((a, b) => ascending ? a.name.localeCompare(b.name) : b.id - a.id);
  return <section className="feature-page"><PageHeader title="Scheduled tasks" description={<>Run tasks on a schedule or whenever you need them. Type <code>/schedule</code> in any existing task to set one up.</>} action="New task" sort={ascending ? "Name" : "Next run"} onSort={() => setAscending(!ascending)} onAction={() => openModal("scheduled")} /><SearchBar placeholder="Search scheduled tasks..." value={search} setValue={setSearch} /><div className="awake-banner"><span><Info size={18} /> Scheduled tasks only run while your computer is awake.</span><button className={`toggle ${keepAwake ? "on" : ""}`} onClick={() => setKeepAwake(!keepAwake)}><Sun size={18} /> Keep awake <i /></button></div>{scheduled.length ? <ItemGrid items={visible} icon={CalendarBlank} emptyLabel="No matching scheduled tasks" /> : <EmptyState icon={Timer} title="Create your first scheduled task" actions={<><button onClick={() => addTemplate("Daily brief")}><Coffee size={18} /> Daily brief</button><button onClick={() => addTemplate("Weekly review")}><Check size={18} /> Weekly review</button></>} />}</section>;
}

function ArtifactsPage({ artifacts, openModal }) {
  return <section className="feature-page"><PageHeader title="Live artifacts" description={<>Create dynamic artifacts that stay up-to-date using live data from <u>your connectors</u>.</>} action="New artifact" onAction={() => openModal("artifact")} />{artifacts.length ? <ItemGrid items={artifacts} icon={Broadcast} /> : <EmptyState icon={Package} title="Create your first artifact" action="What needs my attention" onAction={() => openModal("artifact")} />}</section>;
}

function CustomizePage({ onClose, navOpen }) {
  const [section, setSection] = useState("Overview");
  const [connected, setConnected] = useState(false);
  const [skillCreated, setSkillCreated] = useState(false);
  return <section className={`customize-page ${navOpen ? "" : "nav-closed"}`}><aside className="customize-nav"><button onClick={onClose}><ArrowLeft size={16} /> Back to workspace</button><button className={section === "Skills" ? "current" : ""} onClick={() => setSection("Skills")}><Package size={18} /> Skills</button><button className={section === "Connectors" ? "current" : ""} onClick={() => setSection("Connectors")}><SquaresFour size={18} /> Connectors</button><div><span>Personal plugins</span><button onClick={() => setSection("Plugins")}><Plus size={18} /></button></div><p>Give NextAgent role-level expertise with plugins</p><button className="outline-button" onClick={() => setSection("Plugins")}>Browse plugins</button></aside><div className="customize-main"><Wrench size={72} /><h1>{section === "Overview" ? "Customize NextAgent" : section}</h1><p>Skills, connectors, and plugins shape how NextAgent works with you.</p><div className="customize-cards"><button onClick={() => { setSection("Connectors"); setConnected(true); }}><SquaresFour size={22} /><span><strong>{connected ? "Apps connected" : "Connect your apps"}</strong><small>{connected ? "GitHub and Linear are ready to use." : "Let NextAgent read and write to the tools you already use."}</small></span></button><button onClick={() => { setSection("Skills"); setSkillCreated(true); }}><Package size={22} /><span><strong>{skillCreated ? "First skill created" : "Create new skills"}</strong><small>Teach NextAgent your processes, team norms, and expertise.</small></span></button><button onClick={() => setSection("Plugins")}><Plug size={22} /><span><strong>Browse plugins</strong><small>Add pre-built knowledge for your field.</small></span></button></div></div></section>;
}

function EmptyState({ icon: Icon, title, body, action, onAction, actions }) {
  return <div className="empty-state"><Icon size={88} weight="thin" /><strong>{title}</strong>{body && <p>{body}</p>}<div className="empty-actions">{actions || <button onClick={onAction}>{action}</button>}</div></div>;
}

function ItemGrid({ items, icon: Icon, emptyLabel = "No items" }) {
  const [expanded, setExpanded] = useState(null);
  if (!items.length) return <div className="filtered-empty">{emptyLabel}</div>;
  return <div className="item-grid">{items.map((item) => <button className={expanded === item.id ? "expanded" : ""} onClick={() => setExpanded(expanded === item.id ? null : item.id)} key={item.id}><Icon size={23} /><span><strong>{item.name}</strong><small>{expanded === item.id ? "Details ready for Next core integration" : item.meta}</small></span><CaretDown size={15} /></button>)}</div>;
}

function CreateModal({ type, close, onCreate }) {
  const labels = { project: "project", scheduled: "scheduled task", artifact: "live artifact" };
  const [name, setName] = useState("");
  return <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) close(); }}><div className="create-modal"><button className="modal-close" onClick={close}><X size={18} /></button><span className="modal-icon"><Plus size={22} /></span><h2>Create {labels[type]}</h2><p>Name it now. The Next core integration can provide the real setup flow later.</p><input autoFocus value={name} onChange={(event) => setName(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && name.trim()) onCreate(name.trim()); }} placeholder={`Name your ${labels[type]}`} /><div><button className="outline-button" onClick={close}>Cancel</button><button className="primary-button" disabled={!name.trim()} onClick={() => onCreate(name.trim())}>Create</button></div></div></div>;
}

function RenameSessionModal({ session, close, save }) {
  const [name, setName] = useState(session.title);
  return <div className="modal-backdrop rename-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) close(); }}>
    <form className="rename-session-modal" onSubmit={(event) => { event.preventDefault(); if (name.trim()) save(name.trim()); }}>
      <h2>Rename session</h2>
      <input autoFocus value={name} onChange={(event) => setName(event.target.value)} onFocus={(event) => event.target.select()} />
      <div><button type="button" className="outline-button" onClick={close}>Cancel</button><button type="submit" className="rename-save" disabled={!name.trim()}>Save</button></div>
    </form>
  </div>;
}
