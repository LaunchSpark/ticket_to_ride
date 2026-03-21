import { Fragment, RUN_TRANSITION, h, useEffect, useMemo, useState } from "./runtime.jsx";
import { StatusScreen } from "./atoms/StatusScreen.jsx";
import { BotsDashboard } from "./dashboard/BotsDashboard.jsx";
import { ReplayDashboard } from "./dashboard/ReplayDashboard.jsx";
import { NavBar } from "./layout/Sidebar.jsx";
import { deriveTopBarStatus } from "./model/replay-model.jsx";
import { movePlaybackCursor } from "./model/playback.jsx";
import { loadMatchPayload } from "./services/match-data.jsx";
import { loadRouteSvgMarkup } from "./services/route-svg.jsx";
import { buildStatusState, readParams, writeMatchParams } from "./services/url-utils.jsx";

function normalizeAppPath(pathname) {
  if (!pathname || pathname === "/") {
    return "/";
  }

  const normalizedPath = pathname.endsWith("/") ? pathname.slice(0, -1) : pathname;
  return normalizedPath === "/bots" ? normalizedPath : "/";
}

function buildPageHref(pathname, apiBase, matchId) {
  const query = new URLSearchParams();
  if (apiBase) {
    query.set("api_base", apiBase);
  }
  if (matchId) {
    query.set("match_id", matchId);
  }

  const search = query.toString();
  return search ? `${pathname}?${search}` : pathname;
}

function App() {
  const initialParams = useMemo(readParams, []);
  const currentPath = normalizeAppPath(window.location.pathname);
  const isReplayRoute = currentPath === "/";
  const [isSidebarOpen, setSidebarOpen] = useState(window.innerWidth >= 980);
  const [statusState, setStatusState] = useState(
    buildStatusState("loading", "Loading Match Data", "Fetching the latest replay data from the backend.")
  );
  const [matchData, setMatchData] = useState(null);
  const [activeMatchId, setActiveMatchId] = useState(initialParams.matchId);
  const [playback, setPlayback] = useState({ roundIndex: 0, turnIndex: 0 });
  const [isRunning, setIsRunning] = useState(false);
  const [routeMarkup, setRouteMarkup] = useState("");
  const replayHref = buildPageHref("/", initialParams.apiBase, activeMatchId);
  const botsHref = buildPageHref("/bots", initialParams.apiBase, activeMatchId);

  useEffect(() => {
    if (!isReplayRoute) {
      setRouteMarkup("");
      return undefined;
    }

    let isCancelled = false;
    loadRouteSvgMarkup().then((markup) => {
      if (!isCancelled) {
        setRouteMarkup(markup);
      }
    });
    return () => {
      isCancelled = true;
    };
  }, [isReplayRoute]);

  useEffect(() => {
    if (!isReplayRoute) {
      return undefined;
    }

    let isCancelled = false;

    async function load() {
      try {
        const result = await loadMatchPayload(initialParams.apiBase, activeMatchId);
        if (isCancelled) {
          return;
        }

        RUN_TRANSITION(() => {
          setStatusState(result.status);
          setMatchData(result.matchData);
          setActiveMatchId(result.matchId);
          setPlayback({ roundIndex: 0, turnIndex: 0 });
          setIsRunning(false);
        });
        writeMatchParams(initialParams.apiBase, result.matchId);
      } catch (error) {
        console.error(error);
        if (!isCancelled) {
          setStatusState(buildStatusState("error", "Unable To Load Match Data", error.message));
        }
      }
    }

    load();
    return () => {
      isCancelled = true;
    };
  }, [activeMatchId, initialParams.apiBase, isReplayRoute]);

  useEffect(() => {
    function syncViewportMetrics() {
      const root = document.documentElement;
      const viewportHeight = window.innerHeight;
      const shellPadding = Math.max(16, Math.round(viewportHeight * 0.018));
      const shellGap = Math.max(14, Math.round(viewportHeight * 0.018));

      root.style.setProperty("--app-height", `${viewportHeight}px`);
      root.style.setProperty("--shell-padding", `${shellPadding}px`);
      root.style.setProperty("--shell-gap", `${shellGap}px`);
      root.style.setProperty("--hero-row-height", `${Math.round(viewportHeight * 0.64)}px`);
      root.style.setProperty("--lower-row-height", `${Math.round(viewportHeight * 0.3)}px`);
      root.style.setProperty("--market-row-height", `${Math.max(82, Math.round(viewportHeight * 0.1))}px`);
    }

    syncViewportMetrics();
    window.addEventListener("resize", syncViewportMetrics);
    return () => window.removeEventListener("resize", syncViewportMetrics);
  }, []);

  useEffect(() => {
    function onResize() {
      if (window.innerWidth >= 980) {
        setSidebarOpen(true);
      }
    }

    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  useEffect(() => {
    if (!isRunning || !matchData) {
      return undefined;
    }

    const intervalId = window.setInterval(() => {
      setPlayback((current) => {
        const next = movePlaybackCursor(matchData, current.roundIndex, current.turnIndex, 1);
        if (!next.changed) {
          setIsRunning(false);
          return current;
        }
        return { roundIndex: next.roundIndex, turnIndex: next.turnIndex };
      });
    }, 1000);

    return () => window.clearInterval(intervalId);
  }, [isRunning, matchData]);

  useEffect(() => {
    function onKeyDown(event) {
      if (!matchData) {
        return;
      }

      if (event.code === "Space") {
        event.preventDefault();
        setIsRunning((current) => !current);
        return;
      }

      if (event.code === "ArrowLeft") {
        event.preventDefault();
        setIsRunning(false);
        setPlayback((current) => {
          const next = movePlaybackCursor(matchData, current.roundIndex, current.turnIndex, -1);
          return next.changed ? { roundIndex: next.roundIndex, turnIndex: next.turnIndex } : current;
        });
        return;
      }

      if (event.code === "ArrowRight") {
        event.preventDefault();
        setIsRunning(false);
        setPlayback((current) => {
          const next = movePlaybackCursor(matchData, current.roundIndex, current.turnIndex, 1);
          return next.changed ? { roundIndex: next.roundIndex, turnIndex: next.turnIndex } : current;
        });
      }
    }

    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [matchData]);

  const currentPointer = useMemo(
    () => movePlaybackCursor(matchData, playback.roundIndex, playback.turnIndex, 0),
    [matchData, playback.roundIndex, playback.turnIndex]
  );
  const previousPointer = useMemo(
    () => movePlaybackCursor(matchData, playback.roundIndex, playback.turnIndex, -1),
    [matchData, playback.roundIndex, playback.turnIndex]
  );
  const nextPointer = useMemo(
    () => movePlaybackCursor(matchData, playback.roundIndex, playback.turnIndex, 1),
    [matchData, playback.roundIndex, playback.turnIndex]
  );
  const topBarStatus = isReplayRoute
    ? deriveTopBarStatus(matchData, currentPointer.roundIndex, currentPointer.turnIndex)
    : { roundNumber: 0, turnNumber: 0, activePlayerName: "" };
  const canStepBack = previousPointer.changed;
  const canStepForward = nextPointer.changed;
  const statusCard = isReplayRoute && statusState
    ? h(StatusScreen, {
        label: statusState.kind === "loading" ? "Replay Status" : "Match Status",
        title: statusState.title,
        message: statusState.message,
      })
    : null;

  function stepPlayback(delta) {
    setIsRunning(false);
    setPlayback((current) => {
      const next = movePlaybackCursor(matchData, current.roundIndex, current.turnIndex, delta);
      return next.changed ? { roundIndex: next.roundIndex, turnIndex: next.turnIndex } : current;
    });
  }

  function jumpPlayback(roundIndex, turnIndex) {
    setIsRunning(false);
    setPlayback({ roundIndex, turnIndex });
  }

  function loadSelectedMatch(matchId) {
    if (!matchId || matchId === activeMatchId) {
      return;
    }

    RUN_TRANSITION(() => {
      setStatusState(buildStatusState("loading", "Loading Match Data", `Fetching replay for ${matchId}.`));
      setMatchData(null);
      setActiveMatchId(matchId);
      setPlayback({ roundIndex: 0, turnIndex: 0 });
      setIsRunning(false);
    });
  }

  return h(
    Fragment,
    null,
    h(
      "div",
      { className: "shell-app" },
      h(
        "div",
        { className: currentPath === "/bots" ? "shell-body shell-body--bots" : "shell-body" },
        h(NavBar, {
          isOpen: isSidebarOpen,
          apiBase: initialParams.apiBase,
          currentPath,
          replayHref,
          botsHref,
          activeMatchId,
          matchName: matchData?.name || activeMatchId || "Match Replay",
          matchStatus: matchData?.status || statusState?.title || "Live",
          activePlayerName: topBarStatus.activePlayerName,
          roundNumber: topBarStatus.roundNumber,
          turnNumber: topBarStatus.turnNumber,
          onLoadMatch: loadSelectedMatch,
        }),
        h(
          "main",
          { className: statusCard ? "shell-main shell-main--status" : "shell-main" },
          currentPath === "/bots"
            ? h(BotsDashboard, { apiBase: initialParams.apiBase })
            : statusCard
            ? statusCard
            : h(ReplayDashboard, {
                matchData,
                playback: currentPointer,
                routeMarkup,
                roundNumber: topBarStatus.roundNumber,
                turnNumber: topBarStatus.turnNumber,
                isRunning,
                onPrev: () => stepPlayback(-1),
                onNext: () => stepPlayback(1),
                onTogglePlay: () => setIsRunning((current) => !current),
                onJumpTo: jumpPlayback,
                canStepBack,
                canStepForward,
                onToggleMenu: () => setSidebarOpen((current) => !current),
              })
        )
      )
    ),
    isSidebarOpen && window.innerWidth < 980
      ? h("button", {
          className: "shell-overlay",
          type: "button",
          "aria-label": "Close navigation",
          onClick: () => setSidebarOpen(false),
        })
      : null
  );
}

export function mountReplayApp(rootNode) {
  ReactDOM.createRoot(rootNode).render(h(App));
}
