"use client";

import { ArrowLeft, CheckCircle2, Clapperboard, Download, Eye, History, Plus, RotateCcw, ScanFace, Smartphone, Wand2 } from "lucide-react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { AudioPanel } from "@/components/app/editor/audio-panel";
import { CaptionTimingPanel, HookPanel, PresetCards, SafeAreaToggle } from "@/components/app/editor/caption-controls";
import { CaptionLayer, type HookPreview } from "@/components/app/editor/caption-layer";
import { CaptionSwitch, LayoutPicker, PositionPicker } from "@/components/app/editor/controls";
import { NineBySixteenFrame, PreviewStage, ReframedPreview, type Framing } from "@/components/app/editor/preview-stage";
import { SmartReframePanel, type FramingMode } from "@/components/app/editor/smart-reframe";
import { PublishToYouTube } from "@/components/app/editor/publish-dialog";
import { VersionList } from "@/components/app/editor/versions";
import { VisualsLayer } from "@/components/app/editor/visuals-layer";
import { VisualsPanel } from "@/components/app/editor/visuals-panel";
import { PageHeader } from "@/components/app/page-header";
import { EmptyState, ErrorState } from "@/components/app/states";
import { useAuth } from "@/components/auth/auth-provider";
import { Button } from "@/components/ui/button";
import { ButtonLink } from "@/components/ui/button-link";
import { buttonClasses } from "@/components/ui/button-styles";
import { InlineAlert } from "@/components/ui/inline-alert";
import { WorkingState } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, errorMessage } from "@/lib/api";
import { audioContentUrl, getAudioUploadLimits, getWaveform, listAudio, type AudioAsset, type AudioUploadLimits } from "@/lib/audio";
import {
  DEFAULT_MUSIC,
  DEFAULT_SFX_GAIN_DB,
  MAX_SFX_CUES,
  audioSummary,
  normalizeAudio,
  type AudioRequest,
} from "@/lib/audio-mix";
import {
  TRACK_STAGES,
  getCaptionPreview,
  getCaptionStyles,
  getTimingOptions,
  getTrack,
  isTrackActive,
  retryWordTiming,
  startWordTiming,
  type CaptionStyles,
  type CaptionTiming,
  type CaptionTrack,
  type DynamicPreset,
  type HookPosition,
  type HookStyle,
  type PreviewCue,
} from "@/lib/captions";
import { autoEditHref, getPlan } from "@/lib/auto-edit";
import { getCandidate } from "@/lib/clip-detection";
import { clipContentUrl, type GeneratedClip } from "@/lib/clips";
import {
  EDIT_STAGES,
  captionSummary,
  createEdit,
  describeEdit,
  editContentUrl,
  editDownloadUrl,
  editStageLabel,
  friendlyEditError,
  isEditActive,
  layoutLabel,
  listEdits,
  normalizeHookText,
  retryEdit,
  sameSettings,
  type CaptionPosition,
  type ClipEdit,
  type EditRequest,
  type PickableLayout,
} from "@/lib/edits";
import { DEFAULT_DRAFT, draftFromConfiguration, type EditorDraft } from "@/lib/edit-draft";
import { formatDuration } from "@/lib/format";
import { loadProjectClip } from "@/lib/project-clip";
import { isProjectId, type Project } from "@/lib/projects";
import {
  ANALYSIS_STAGES,
  getAnalysis,
  getCropPath,
  getCurrentAnalysis,
  isAnalysisActive,
  retryAnalysis,
  startAnalysis,
  type CropPath,
  type ReframeAnalysis,
} from "@/lib/reframe";
import { mergeJobs, newer } from "@/lib/status-sync";
import { useApi } from "@/lib/use-api";
import { usePolling } from "@/lib/use-polling";
import { useAudioPreview, type PreviewPlan } from "@/lib/use-audio-preview";
import { getYouTubeStatus } from "@/lib/publishing";
import { getVisualLayout } from "@/lib/broll";
import {
  elementProblems,
  elementRequest,
  overlapProblems,
  visualsSummary,
  type VisualElementDraft,
  type VisualLayout,
} from "@/lib/visual-elements";
import { listVisuals, type VisualAsset } from "@/lib/visuals";

function Editor({ project, clip }: { project: Project; clip: GeneratedClip }) {
  const { setUser } = useAuth();
  const id = useId();
  const [layout, setLayout] = useState<PickableLayout>("blur_background");
  const [framingMode, setFramingMode] = useState<FramingMode>("auto");
  const [focus, setFocus] = useState({ x: 0.5, y: 0.5 });
  // undefined = still loading, null = never analyzed with the server's current configuration.
  const [analysis, setAnalysis] = useState<ReframeAnalysis | null | undefined>(undefined);
  const [cropPath, setCropPath] = useState<CropPath | null>(null);
  const [analysisBusy, setAnalysisBusy] = useState(false);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [captions, setCaptions] = useState(true);
  const [preset, setPreset] = useState<DynamicPreset>("focus");
  const [position, setPosition] = useState<CaptionPosition>("bottom");
  const [timing, setTiming] = useState<CaptionTiming>("aligned_word");
  const [spec, setSpec] = useState<CaptionStyles | null>(null);
  // undefined = still loading, null = never generated with the server's current configuration.
  const [track, setTrack] = useState<CaptionTrack | null | undefined>(undefined);
  const [phraseAvailable, setPhraseAvailable] = useState(false);
  const [trackBusy, setTrackBusy] = useState(false);
  const [trackError, setTrackError] = useState<string | null>(null);
  const [cues, setCues] = useState<PreviewCue[] | null>(null);
  const [hookOn, setHookOn] = useState(false);
  const [hookText, setHookText] = useState("");
  const [hookStyle, setHookStyle] = useState<HookStyle>("headline");
  const [hookPosition, setHookPosition] = useState<HookPosition>("top");
  const [hookDuration, setHookDuration] = useState(2);
  const [showSafeArea, setShowSafeArea] = useState(false);
  const [audio, setAudio] = useState<AudioRequest>({ source_gain_db: 0, normalize: true, music: null, sfx: [] });
  // An audio section exists once the creator uses Audio, or when loaded settings had one.
  const [audioSection, setAudioSection] = useState(false);
  const [audioAssets, setAudioAssets] = useState<AudioAsset[] | null>(null);
  const [waveforms, setWaveforms] = useState<Record<string, number[]>>({});
  const [audioLimits, setAudioLimits] = useState<AudioUploadLimits | null>(null);
  const [visuals, setVisuals] = useState<VisualElementDraft[]>([]);
  const [visualAssets, setVisualAssets] = useState<VisualAsset[] | null>(null);
  const [visualLayout, setVisualLayout] = useState<VisualLayout | null>(null);
  const [previewVideo, setPreviewVideo] = useState<HTMLVideoElement | null>(null);
  const [edits, setEdits] = useState<ClipEdit[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [mode, setMode] = useState<"preview" | "rendered">("preview");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  // Whether this server can publish (the button appears only then).
  const { data: publishing } = useApi(getYouTubeStatus);
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [justFinished, setJustFinished] = useState(false);
  const [busy, setBusy] = useState(false);
  const [retryingId, setRetryingId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  // ---- loading settings: a stored version or Auto Edit plan opens with exactly its settings ----
  const search = useSearchParams();
  const planParam = search.get("plan");
  const editParam = search.get("edit");
  // Any change by the creator wins over settings that arrive later from the network.
  const touched = useRef(false);
  const hydrated = useRef(false);
  const [loadedFrom, setLoadedFrom] = useState<{ label: string; configuration: Record<string, unknown>; href?: string } | null>(null);
  const edit = useCallback(<T,>(set: (value: T) => void) => (value: T) => {
    touched.current = true;
    set(value);
  }, []);
  const applyDraft = useCallback((draft: EditorDraft) => {
    setLayout(draft.layout);
    setFramingMode(draft.framingMode);
    setFocus(draft.focus);
    setCaptions(draft.captions);
    setPreset(draft.preset);
    setPosition(draft.position);
    setTiming(draft.timing);
    setHookOn(draft.hookOn);
    if (draft.hookText !== null) setHookText(draft.hookText);
    setHookStyle(draft.hookStyle);
    setHookPosition(draft.hookPosition);
    setHookDuration(draft.hookDuration);
    setAudio(draft.audio);
    setAudioSection(draft.audioSection);
    setVisuals(draft.visuals);
  }, []);
  const hydrate = useCallback(
    (configuration: Record<string, unknown> | null | undefined, label: string, href?: string) => {
      if (hydrated.current) return;
      hydrated.current = true;
      if (!configuration || touched.current) return; // never overwrite the creator's changes
      applyDraft(draftFromConfiguration(configuration, { analysisId: null, trackId: null }).draft);
      setLoadedFrom({ label, configuration, href });
    },
    [applyDraft],
  );
  function resetToDefaults() {
    touched.current = true;
    applyDraft({ ...DEFAULT_DRAFT, focus: { ...DEFAULT_DRAFT.focus }, audio: { ...DEFAULT_DRAFT.audio, sfx: [] }, visuals: [] });
    setLoadedFrom(null);
  }

  const handleError = useCallback(
    (err: unknown) => {
      if (err instanceof ApiError && err.status === 401) setUser(null);
      return errorMessage(err);
    },
    [setUser],
  );

  const stageRef = useRef<HTMLDivElement>(null);
  // The version just started; read through a ref so polling does not restart on change.
  const pendingRef = useRef<string | null>(null);
  pendingRef.current = pendingId;

  const refresh = useCallback(
    () =>
      listEdits(project.id, clip.video_id, clip.id)
        .then((page) => {
          // Merge, never replace: a list fetched before a new render started must not drop it.
          setEdits((current) => mergeJobs(current, page.edits, EDIT_STAGES));
          setLoadError(null);
          if (!hydrated.current && !planParam) {
            // The requested version, else the newest one: the editor continues where it was.
            // An unknown or deleted version falls back to the newest one.
            const target = (editParam ? page.edits.find((e) => e.id === editParam) : undefined) ?? page.edits[0];
            if (target) {
              hydrate(target.configuration, describeEdit(target));
              if (target.id === editParam && target.status === "ready") {
                setSelectedId(target.id);
                setMode("rendered");
              } else if (target.id === editParam && isEditActive(target.status)) {
                setPendingId(target.id);
              }
            } else {
              hydrated.current = true;
            }
          }
          // When the version just started becomes ready, put the real output on the stage.
          const finished = page.edits.find((e) => e.id === pendingRef.current && e.status === "ready");
          if (finished) {
            setSelectedId(finished.id);
            setMode("rendered");
            setJustFinished(true);
            setPendingId(null);
            stageRef.current?.scrollIntoView({ block: "nearest" });
          }
        })
        .catch((err: unknown) => setLoadError(handleError(err))),
    [project.id, clip.video_id, clip.id, handleError, hydrate, planParam, editParam],
  );

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // "Edit choices" from Auto Edit: the plan's settings, not yet rendered.
  useEffect(() => {
    if (!planParam || hydrated.current) return;
    let cancelled = false;
    getPlan(project.id, clip.video_id, clip.id, planParam)
      .then((plan) => {
        if (!cancelled) {
          hydrate(plan.configuration, `Auto Edit plan · ${plan.recipe_label}`, autoEditHref(project.id, clip.id));
        }
      })
      .catch(() => {
        hydrated.current = true; // a missing plan leaves the editor as it is
      });
    return () => {
      cancelled = true;
    };
  }, [planParam, project.id, clip.video_id, clip.id, hydrate]);

  // ---- audio: the project's music and effects, their waveforms, the upload limits ---------
  const loadWaveform = useCallback(
    (asset: AudioAsset) =>
      getWaveform(project.id, asset.id)
        .then((wave) => setWaveforms((current) => ({ ...current, [asset.id]: wave.peaks })))
        .catch(() => {}), // the waveform is a navigation aid; the asset stays usable without it
    [project.id],
  );
  useEffect(() => {
    let cancelled = false;
    listAudio(project.id)
      .then((assets) => {
        if (cancelled) return;
        setAudioAssets(assets);
        assets.forEach((asset) => void loadWaveform(asset));
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setAudioAssets([]);
          setActionError(handleError(err));
        }
      });
    getAudioUploadLimits()
      .then((limits) => !cancelled && setAudioLimits(limits))
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [project.id, loadWaveform, handleError]);

  // ---- visuals: the project's images and B-roll videos, and where insets sit ---------------
  useEffect(() => {
    let cancelled = false;
    listVisuals(project.id)
      .then((assets) => !cancelled && setVisualAssets(assets))
      .catch(() => !cancelled && setVisualAssets([]));
    getVisualLayout()
      .then((layout) => !cancelled && setVisualLayout(layout))
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [project.id]);
  const visualAssetMap = useMemo(() => new Map((visualAssets ?? []).map((a) => [a.id, a])), [visualAssets]);
  function visualUploaded(asset: VisualAsset) {
    setVisualAssets((current) => [asset, ...(current ?? []).filter((a) => a.id !== asset.id)]);
  }

  function audioUploaded(asset: AudioAsset) {
    touched.current = true;
    setAudioSection(true);
    setAudioAssets((current) => [asset, ...(current ?? []).filter((a) => a.id !== asset.id)]);
    void loadWaveform(asset);
    setAudio((current) => {
      if (asset.kind === "music") {
        // A newly uploaded track becomes the music (levels and ducking are kept).
        const keep = current.music ? { gain_db: current.music.gain_db, ducking: current.music.ducking } : {};
        return { ...current, music: { asset_id: asset.id, ...DEFAULT_MUSIC, ...keep } };
      }
      if (current.sfx.length >= MAX_SFX_CUES) return current;
      const at = Math.round(Math.min(clip.duration_seconds, previewVideo?.currentTime ?? 0) * 10) / 10;
      return { ...current, sfx: [...current.sfx, { asset_id: asset.id, at_seconds: at, gain_db: DEFAULT_SFX_GAIN_DB }] };
    });
  }

  // ---- dynamic captions: the renderer's spec, word timing, the hook suggestion -------------
  useEffect(() => {
    let cancelled = false;
    getCaptionStyles()
      .then((styles) => {
        if (!cancelled) setSpec(styles);
      })
      .catch((err: unknown) => {
        if (!cancelled) setActionError(handleError(err));
      });
    getTimingOptions(project.id, clip.video_id, clip.id)
      .then((options) => {
        if (cancelled) return;
        setTrack(options.track);
        setPhraseAvailable(options.phrase_timing_available);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setTrack(null);
        setTrackError(handleError(err));
      });
    // Suggest the candidate's own hook (or title) when it fits; never call another model.
    getCandidate(project.id, clip.video_id, clip.run_id, clip.candidate_id)
      .then((candidate) => {
        if (cancelled) return;
        const suggestion = [candidate.hook, candidate.title, clip.title]
          .map((t) => normalizeHookText(t ?? ""))
          .find((t) => t && [...t].length <= 60);
        if (suggestion) setHookText((current) => current || suggestion);
      })
      .catch(() => {
        if (!cancelled && [...clip.title].length <= 60) setHookText((current) => current || clip.title);
      });
    return () => {
      cancelled = true;
    };
  }, [project.id, clip.video_id, clip.id, clip.run_id, clip.candidate_id, clip.title, handleError]);

  const trackId = track?.id ?? null;
  const trackReady = track?.status === "completed";
  const trackRunning = !!track && isTrackActive(track.status) && !track.is_stale;
  const acceptTrack = useCallback(
    (next: CaptionTrack) => setTrack((current) => newer(current, next, TRACK_STAGES)),
    [],
  );
  usePolling(
    trackRunning && trackId !== null,
    async () => {
      if (!trackId) return;
      try {
        acceptTrack(await getTrack(project.id, clip.video_id, clip.id, trackId));
      } catch (err) {
        setTrackError(handleError(err));
      }
    },
    trackId,
  );

  async function generateWordSync(retrying: boolean) {
    if (trackBusy) return;
    setTrackBusy(true);
    setTrackError(null);
    try {
      const next =
        retrying && track
          ? await retryWordTiming(project.id, clip.video_id, clip.id, track.id)
          : await startWordTiming(project.id, clip.video_id, clip.id);
      acceptTrack(next);
      edit(setTiming)("aligned_word");
    } catch (err) {
      setTrackError(handleError(err));
    } finally {
      setTrackBusy(false);
    }
  }

  // The preview shows the renderer's own cues (lines, word timing) for these settings.
  const previewReady = captions && (timing === "phrase_fallback" ? phraseAvailable : trackReady);
  useEffect(() => {
    if (!previewReady) return;
    let cancelled = false;
    getCaptionPreview(project.id, clip.video_id, clip.id, {
      style: preset,
      position,
      timing,
      trackId: timing === "aligned_word" ? trackId : null,
    })
      .then((preview) => {
        if (!cancelled) setCues(preview?.cues ?? null);
      })
      .catch(() => {
        if (!cancelled) setCues(null);
      });
    return () => {
      cancelled = true;
    };
  }, [previewReady, project.id, clip.video_id, clip.id, preset, position, timing, trackId]);

  // Poll only while some version is really rendering; stop when all are settled.
  const anyActive = !!edits?.some((e) => isEditActive(e.status) && !e.is_stale);
  usePolling(anyActive, refresh);

  // ---- smart framing analysis -------------------------------------------------------------
  useEffect(() => {
    let cancelled = false;
    getCurrentAnalysis(project.id, clip.video_id, clip.id)
      .then((current) => {
        if (!cancelled) setAnalysis(current);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setAnalysis(null);
        setAnalysisError(handleError(err));
      });
    return () => {
      cancelled = true;
    };
  }, [project.id, clip.video_id, clip.id, handleError]);

  // Poll only while the analysis is really running.
  const analysisId = analysis?.id ?? null;
  const analysisRunning = !!analysis && isAnalysisActive(analysis.status) && !analysis.is_stale;
  const acceptAnalysis = useCallback(
    (next: ReframeAnalysis) => setAnalysis((current) => newer(current, next, ANALYSIS_STAGES)),
    [],
  );
  usePolling(
    analysisRunning && analysisId !== null,
    async () => {
      if (!analysisId) return;
      try {
        acceptAnalysis(await getAnalysis(project.id, clip.video_id, clip.id, analysisId));
      } catch (err) {
        setAnalysisError(handleError(err));
      }
    },
    analysisId,
  );

  // The crop path drives the live preview once the analysis has completed.
  const analysisDone = analysis?.status === "completed";
  useEffect(() => {
    if (!analysisDone || !analysisId) return;
    let cancelled = false;
    getCropPath(project.id, clip.video_id, clip.id, analysisId)
      .then((path) => {
        if (!cancelled) setCropPath(path);
      })
      .catch(() => {
        if (!cancelled) setCropPath(null); // the preview stays centered; rendering is unaffected
      });
    return () => {
      cancelled = true;
    };
  }, [analysisDone, analysisId, project.id, clip.video_id, clip.id]);

  async function analyze(retrying: boolean) {
    if (analysisBusy) return;
    setAnalysisBusy(true);
    setAnalysisError(null);
    try {
      const next =
        retrying && analysis
          ? await retryAnalysis(project.id, clip.video_id, clip.id, analysis.id)
          : await startAnalysis(project.id, clip.video_id, clip.id);
      setCropPath(null);
      acceptAnalysis(next);
    } catch (err) {
      setAnalysisError(handleError(err));
    } finally {
      setAnalysisBusy(false);
    }
  }

  const smart = layout === "smart_reframe";
  const manual = smart && framingMode === "manual";
  const sourceWidth = clip.width ?? cropPath?.source_width ?? analysis?.source_width ?? null;
  const sourceHeight = clip.height ?? cropPath?.source_height ?? analysis?.source_height ?? null;
  const pathKeyframes = analysisDone && cropPath?.analysis_id === analysisId ? cropPath.keyframes : null;
  const framing: Framing = useMemo(
    () =>
      manual
        ? { kind: "focus", x: focus.x, y: focus.y }
        : pathKeyframes
          ? { kind: "path", keyframes: pathKeyframes }
          : { kind: "center" },
    [manual, focus, pathKeyframes],
  );
  // Automatic framing can render only from a completed analysis of this clip.
  const awaitingAnalysis = smart && !manual && !analysisDone;

  // The audio section is sent only once the creator uses Audio (or loaded settings had one), so
  // a creator who never opens Audio gets exactly the earlier render.
  const audioActive = audioSection || !!audio.music || audio.sfx.length > 0 || audio.source_gain_db !== 0;
  const audioRequest = useMemo(() => (audioActive ? normalizeAudio(audio) : null), [audioActive, audio]);
  // Visuals are sent only when there are some, so an edit without them keeps its old settings.
  const visualsRequest = useMemo(
    () => (visuals.length ? { elements: visuals.map((e) => elementRequest(e, visualAssetMap.get(e.asset_id))) } : null),
    [visuals, visualAssetMap],
  );
  const visualsInvalid = useMemo(
    () =>
      overlapProblems(visuals).size > 0 ||
      visuals.some((e) => elementProblems(e, visualAssetMap.get(e.asset_id), clip.duration_seconds).length > 0),
    [visuals, visualAssetMap, clip.duration_seconds],
  );
  const request: EditRequest = useMemo(
    () => ({
      aspect_ratio: "9:16",
      layout: manual ? "manual_crop" : layout,
      captions_enabled: captions,
      ...(captions
        ? {
            caption_style: preset,
            caption_position: position,
            caption_timing: timing,
            ...(timing === "aligned_word" && trackReady && trackId ? { caption_track_id: trackId } : {}),
          }
        : {}),
      ...(smart && !manual && analysisDone && analysisId ? { reframe_analysis_id: analysisId } : {}),
      ...(manual ? { focus_x: focus.x, focus_y: focus.y } : {}),
      ...(hookOn
        ? {
            hook_enabled: true,
            hook_text: normalizeHookText(hookText),
            hook_style: hookStyle,
            hook_position: hookPosition,
            hook_duration_seconds: hookDuration,
          }
        : {}),
      ...(audioRequest ? { audio: audioRequest } : {}),
      ...(visualsRequest ? { visuals: visualsRequest } : {}),
    }),
    [layout, manual, smart, captions, preset, position, timing, trackReady, trackId, analysisDone, analysisId, focus, hookOn, hookText, hookStyle, hookPosition, hookDuration, audioRequest, visualsRequest],
  );
  // An approximate audio preview with the video as its clock (the render is authoritative).
  const previewPlan: PreviewPlan | null = useMemo(() => {
    if (!audioActive) return null;
    const music = audio.music ? audioAssets?.find((a) => a.id === audio.music!.asset_id) : undefined;
    return {
      duration: clip.duration_seconds,
      sourceGainDb: audio.source_gain_db,
      music:
        audio.music && music
          ? { url: audioContentUrl(project.id, music.id), trackSeconds: music.duration_seconds, config: audio.music }
          : null,
      cues: audio.sfx.map((cue) => ({ url: audioContentUrl(project.id, cue.asset_id), at_seconds: cue.at_seconds, gain_db: cue.gain_db })),
    };
  }, [audioActive, audio, audioAssets, clip.duration_seconds, project.id]);
  useAudioPreview(mode === "preview" ? previewVideo : null, previewPlan);
  // Word-synced captions render only from a completed word timing (never silently phrase).
  const awaitingWords = captions && timing === "aligned_word" && !trackReady;
  const hookLength = [...normalizeHookText(hookText)].length;
  const hookInvalid = hookOn && (hookLength === 0 || hookLength > (spec?.hook.max_chars ?? 60));
  const blocked = awaitingAnalysis || awaitingWords || hookInvalid || visualsInvalid;
  const hookPreview: HookPreview | null =
    hookOn && !hookInvalid
      ? { text: normalizeHookText(hookText), style: hookStyle, position: hookPosition, duration: hookDuration }
      : null;
  // Visuals under the text layer: captions and the hook stay on top, as in the render.
  const overlay = (
    <>
      <VisualsLayer projectId={project.id} elements={visuals} assets={visualAssetMap} layout={visualLayout} />
      {spec ? (
        <CaptionLayer
          spec={spec}
          preset={captions ? preset : null}
          position={position}
          cues={captions && previewReady ? cues : null}
          hook={hookPreview}
          showSafeArea={showSafeArea}
        />
      ) : null}
    </>
  );
  const match = blocked ? null : (edits?.find((e) => sameSettings(e, request)) ?? null);
  const matchActive = !!match && isEditActive(match.status) && !match.is_stale;
  const matchStuck = !!match && (match.status === "failed" || (isEditActive(match.status) && match.is_stale));
  const readyEdits = edits?.filter((e) => e.status === "ready") ?? [];
  const selected = edits?.find((e) => e.id === selectedId && e.status === "ready") ?? null;

  function upsert(edit: ClipEdit) {
    setEdits((current) => mergeJobs(current, [edit], EDIT_STAGES));
  }

  async function retry(edit: ClipEdit) {
    setRetryingId(edit.id);
    setActionError(null);
    try {
      const updated = await retryEdit(project.id, clip.video_id, clip.id, edit.id);
      upsert(updated);
      setPendingId(updated.id);
    } catch (err) {
      setActionError(handleError(err));
    } finally {
      setRetryingId(null);
    }
  }

  async function render() {
    if (busy || matchActive || blocked) return; // no duplicate submissions (the API deduplicates too)
    if (match?.status === "ready") {
      showRendered(match);
      return;
    }
    if (match && matchStuck) {
      await retry(match);
      return;
    }
    setBusy(true);
    setActionError(null);
    setJustFinished(false);
    try {
      const edit = await createEdit(project.id, clip.video_id, clip.id, request);
      upsert(edit);
      setPendingId(edit.id);
    } catch (err) {
      setActionError(handleError(err));
    } finally {
      setBusy(false);
    }
  }

  function showRendered(edit: ClipEdit) {
    setSelectedId(edit.id);
    setMode("rendered");
    setJustFinished(false);
  }

  // What could not be loaded exactly (framing or word timing regenerated since), said plainly.
  const hydrationNotes = useMemo(() => {
    if (!loadedFrom || analysis === undefined || track === undefined) return [];
    return draftFromConfiguration(loadedFrom.configuration, {
      analysisId: analysis?.status === "completed" ? analysis.id : null,
      trackId: track?.status === "completed" ? track.id : null,
    }).notes;
  }, [loadedFrom, analysis, track]);

  const backToProject = `/projects/${project.id}#generated`;
  const renderedName = selected ? describeEdit(selected) : "";
  const audioLabel = audioSummary(audioRequest);
  const settingsSummary = `${layoutLabel(request.layout)} · ${captionSummary({
    captions_enabled: captions,
    caption_style: preset,
    caption_position: position,
    caption_timing: timing,
    hook_enabled: hookOn,
  })}${audioLabel ? ` · ${audioLabel}` : ""}${visuals.length ? ` · ${visualsSummary(visuals.length)}` : ""}`;

  // ---- primary action area -------------------------------------------------------------
  let action;
  if (matchActive && match) {
    action = (
      <div className="rounded-xl border border-border bg-surface-2 p-3.5">
        <WorkingState
          label={editStageLabel(match).replace("…", "")}
          progress={match.status === "queued" ? null : match.progress_percent}
          progressLabel="Render progress"
          detail="Rendering short on the server. You can keep adjusting settings or leave this page."
        />
      </div>
    );
  } else if (match?.status === "ready") {
    action = (
      <div className="space-y-2">
        <Button size="lg" variant="secondary" className="w-full" onClick={() => showRendered(match)}>
          <Eye aria-hidden="true" />
          View this version
        </Button>
        <p className="text-center text-xs text-subtle">You already rendered these settings.</p>
      </div>
    );
  } else if (matchStuck && match) {
    action = (
      <div className="space-y-3">
        <InlineAlert title={match.status === "failed" ? "Render failed" : "Render stalled"}>
          We couldn&apos;t generate this version of your short.
          <span className="block text-xs text-subtle">
            {match.status === "failed" ? friendlyEditError(match) : "The worker stopped reporting progress."}
          </span>
        </InlineAlert>
        <Button size="lg" className="w-full" onClick={() => void retry(match)} disabled={retryingId === match.id}>
          <RotateCcw aria-hidden="true" />
          {retryingId === match.id ? "Retrying…" : "Retry render"}
        </Button>
      </div>
    );
  } else if (awaitingAnalysis) {
    action = (
      <div className="space-y-2">
        <Button size="lg" className="w-full" disabled>
          <Wand2 aria-hidden="true" />
          Render short
        </Button>
        <p className="text-center text-xs text-subtle">
          {analysis && isAnalysisActive(analysis.status) && !analysis.is_stale
            ? "Available when the framing analysis finishes."
            : "Analyze the framing first, or set a focal point."}
        </p>
      </div>
    );
  } else if (awaitingWords) {
    action = (
      <div className="space-y-2">
        <Button size="lg" className="w-full" disabled>
          <Wand2 aria-hidden="true" />
          Render short
        </Button>
        <p className="text-center text-xs text-subtle">
          {trackRunning ? "Available when word sync finishes." : "Generate word sync first, or use phrase timing."}
        </p>
        {phraseAvailable ? (
          <Button variant="ghost" className="w-full" onClick={() => edit(setTiming)("phrase_fallback")}>
            Use phrase timing instead
          </Button>
        ) : null}
      </div>
    );
  } else if (hookInvalid) {
    action = (
      <div className="space-y-2">
        <Button size="lg" className="w-full" disabled>
          <Wand2 aria-hidden="true" />
          Render short
        </Button>
        <p className="text-center text-xs text-subtle">
          {hookLength === 0 ? "Add hook text, or turn the hook off." : "Shorten the hook text to render."}
        </p>
      </div>
    );
  } else if (visualsInvalid) {
    action = (
      <div className="space-y-2">
        <Button size="lg" className="w-full" disabled>
          <Wand2 aria-hidden="true" />
          Render short
        </Button>
        <p className="text-center text-xs text-subtle">Fix the highlighted visuals to render.</p>
      </div>
    );
  } else {
    action = (
      <Button size="lg" className="w-full" onClick={() => void render()} disabled={busy || edits === null}>
        <Wand2 aria-hidden="true" />
        {busy ? "Starting…" : "Render short"}
      </Button>
    );
  }

  return (
    <>
      <PageHeader
        back={{ href: backToProject, label: project.name }}
        title="Short-form editor"
        action={
          <ButtonLink href={autoEditHref(project.id, clip.id)} variant="secondary">
            <Wand2 aria-hidden="true" />
            Auto Edit
          </ButtonLink>
        }
        description={
          <span className="inline-flex flex-wrap items-center gap-x-2">
            <span className="text-foreground">{clip.title}</span>
            <span className="tabular text-subtle">· {formatDuration(clip.duration_seconds)} clip</span>
          </span>
        }
      />

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_400px] lg:gap-8">
        {/* Stage: the video is the focal point. */}
        <section aria-label="Stage" ref={stageRef} className="min-w-0 scroll-mt-20 lg:col-start-1 lg:row-start-1">
          <div className="rounded-2xl border border-border bg-[radial-gradient(ellipse_at_top,rgb(255_255_255/0.04),transparent_60%)] bg-surface p-4 sm:p-6">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
              <div className="inline-flex rounded-lg border border-border bg-surface-2 p-0.5" role="group" aria-label="Stage view">
                <button
                  type="button"
                  aria-pressed={mode === "preview"}
                  onClick={() => setMode("preview")}
                  className={`inline-flex h-8 items-center gap-1.5 rounded-md px-3 text-[13px] font-medium transition-colors focus-visible:outline-2 focus-visible:outline-accent ${
                    mode === "preview" ? "bg-surface-3 text-foreground shadow-sm" : "text-muted hover:text-foreground"
                  }`}
                >
                  <Eye aria-hidden="true" className="size-3.5" />
                  Preview
                </button>
                <button
                  type="button"
                  aria-pressed={mode === "rendered"}
                  disabled={readyEdits.length === 0}
                  onClick={() => {
                    const target = selected ?? readyEdits[0];
                    if (target) showRendered(target);
                  }}
                  className={`inline-flex h-8 items-center gap-1.5 rounded-md px-3 text-[13px] font-medium transition-colors focus-visible:outline-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-40 ${
                    mode === "rendered" ? "bg-surface-3 text-foreground shadow-sm" : "text-muted hover:text-foreground"
                  }`}
                >
                  <Smartphone aria-hidden="true" className="size-3.5" />
                  Rendered short
                </button>
              </div>
              <div className="flex items-center gap-3">
                {mode === "preview" && spec ? <SafeAreaToggle checked={showSafeArea} onChange={setShowSafeArea} /> : null}
                <span className="tabular hidden text-xs text-subtle sm:inline">9:16 · 1080 × 1920</span>
              </div>
            </div>

            {mode === "rendered" && selected ? (
              <div className="animate-fade-in space-y-4">
                <NineBySixteenFrame label={`Rendered short: ${renderedName}`}>
                  <video
                    key={selected.id}
                    controls
                    playsInline
                    preload="metadata"
                    src={editContentUrl(selected.id)}
                    className="size-full bg-black object-contain"
                    aria-label={`Rendered short: ${renderedName}`}
                  />
                </NineBySixteenFrame>
                {justFinished ? (
                  <p role="status" className="flex items-center justify-center gap-2 text-sm text-emerald-200">
                    <CheckCircle2 aria-hidden="true" className="size-4" />
                    Your short is ready.
                  </p>
                ) : null}
                <div className="text-center">
                  <p className="text-sm font-medium text-foreground">{renderedName}</p>
                  <p className="tabular text-xs text-subtle">
                    Rendered MP4 · {selected.duration_seconds != null ? formatDuration(selected.duration_seconds) : ""} · 1080 × 1920
                  </p>
                </div>
                <div className="flex flex-col items-stretch justify-center gap-2 sm:flex-row sm:flex-wrap sm:items-center">
                  <a
                    href={editDownloadUrl(selected.id)}
                    download
                    className={buttonClasses("primary", "md")}
                    aria-label={`Download short — ${renderedName}`}
                  >
                    <Download aria-hidden="true" />
                    Download short
                  </a>
                  {publishing?.enabled ? (
                    <PublishToYouTube editId={selected.id} editName={renderedName} />
                  ) : null}
                  <Button variant="secondary" onClick={() => setMode("preview")}>
                    <Plus aria-hidden="true" />
                    Create another version
                  </Button>
                  <Link href={backToProject} className={buttonClasses("ghost", "md")}>
                    <ArrowLeft aria-hidden="true" />
                    Back to clip
                  </Link>
                </div>
              </div>
            ) : (
              <div className="space-y-3">
                <div className="relative">
                  {smart && sourceWidth && sourceHeight ? (
                    <ReframedPreview
                      clipSrc={clipContentUrl(clip.id)}
                      sourceWidth={sourceWidth}
                      sourceHeight={sourceHeight}
                      framing={framing}
                      overlay={overlay}
                      onVideo={setPreviewVideo}
                      badge={
                        framing.kind === "center" ? (
                          <span className="inline-flex items-center gap-1.5 rounded-full bg-black/70 px-2.5 py-1 text-[11px] font-medium text-white backdrop-blur-sm">
                            <ScanFace aria-hidden="true" className="size-3" />
                            Centered until framing is analyzed
                          </span>
                        ) : null
                      }
                    />
                  ) : (
                    <PreviewStage
                      clipSrc={clipContentUrl(clip.id)}
                      layout={smart ? "center_crop" : layout}
                      overlay={overlay}
                      onVideo={setPreviewVideo}
                    />
                  )}
                </div>
                <p className="mx-auto max-w-sm text-center text-xs text-pretty text-subtle">
                  Preview — captions use the renderer&apos;s own lines and timing; sizes are close, not pixel-exact. The rendered
                  MP4 is the final result.
                </p>
              </div>
            )}
          </div>
        </section>

        {/* Settings: everything the server accepts, nothing it does not. */}
        <aside
          aria-label="Edit settings"
          className="self-start rounded-2xl border border-border bg-surface lg:sticky lg:top-20 lg:col-start-2 lg:row-span-2 lg:row-start-1"
        >
          <div className="border-b border-border px-4 py-4 sm:px-5">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <h2 className="text-[15px] font-semibold text-foreground">Edit settings</h2>
                <p className="mt-0.5 text-sm text-muted">Choose how this clip becomes a vertical short.</p>
              </div>
              <Button variant="ghost" size="sm" className="shrink-0" onClick={resetToDefaults}>
                <RotateCcw aria-hidden="true" />
                Reset to defaults
              </Button>
            </div>
            {loadedFrom ? (
              <div role="status" className="mt-3 space-y-1.5 rounded-lg border border-border bg-surface-2 px-3 py-2.5 text-xs">
                <p className="flex items-start gap-2 text-muted">
                  <History aria-hidden="true" className="mt-px size-3.5 shrink-0" />
                  <span>
                    Loaded the settings of <span className="break-words text-foreground">{loadedFrom.label}</span>.
                    {loadedFrom.href ? (
                      <>
                        {" "}
                        <Link href={loadedFrom.href} className="text-accent-soft underline-offset-2 hover:underline">
                          Back to the plan
                        </Link>
                      </>
                    ) : null}
                  </span>
                </p>
                {hydrationNotes.map((note) => (
                  <p key={note} className="pl-5.5 text-amber-200">
                    {note}
                  </p>
                ))}
              </div>
            ) : null}
          </div>
          <div className="space-y-6 px-4 py-5 sm:px-5">
            <div className="space-y-3">
              <LayoutPicker value={layout} onChange={edit(setLayout)} name={`${id}-layout`} />
              {smart ? (
                <div className="animate-fade-in space-y-2">
                  <SmartReframePanel
                    name={`${id}-framing`}
                    mode={framingMode}
                    onModeChange={edit(setFramingMode)}
                    analysis={analysis}
                    busy={analysisBusy}
                    onAnalyze={() => void analyze(false)}
                    onRetry={() => void analyze(true)}
                    posterSrc={clipContentUrl(clip.id)}
                    sourceWidth={sourceWidth ?? 16}
                    sourceHeight={sourceHeight ?? 9}
                    focusX={focus.x}
                    focusY={focus.y}
                    onFocusChange={(x, y) => edit(setFocus)({ x, y })}
                  />
                  {analysisError ? (
                    <InlineAlert title="Smart framing is unavailable">{analysisError}</InlineAlert>
                  ) : null}
                </div>
              ) : null}
            </div>
            <div className="space-y-4">
              <CaptionSwitch checked={captions} onChange={edit(setCaptions)} />
              {captions ? (
                <div className="animate-fade-in space-y-4">
                  <CaptionTimingPanel
                    timing={timing}
                    onTimingChange={edit(setTiming)}
                    track={track}
                    phraseAvailable={phraseAvailable}
                    busy={trackBusy}
                    error={trackError}
                    onGenerate={() => void generateWordSync(false)}
                    onRetry={() => void generateWordSync(true)}
                  />
                  {spec ? (
                    <PresetCards spec={spec} value={preset} onChange={edit(setPreset)} name={`${id}-preset`} disabled={!captions} />
                  ) : null}
                  <PositionPicker
                    value={position}
                    onChange={edit(setPosition)}
                    name={`${id}-position`}
                    disabled={!captions}
                    taken={hookOn ? hookPosition : null}
                  />
                </div>
              ) : null}
            </div>
            {spec ? (
              <HookPanel
                spec={spec}
                enabled={hookOn}
                onEnabled={(on) => {
                  touched.current = true;
                  // The hook never shares the captions' position: start it somewhere free.
                  if (on && captions && hookPosition === position) setHookPosition(position === "top" ? "center" : "top");
                  setHookOn(on);
                }}
                text={hookText}
                onText={edit(setHookText)}
                style={hookStyle}
                onStyle={edit(setHookStyle)}
                position={hookPosition}
                onPosition={edit(setHookPosition)}
                duration={hookDuration}
                onDuration={edit(setHookDuration)}
                captionPosition={captions ? position : null}
                emojiOmitted={spec.emoji === "omitted"}
              />
            ) : null}
            <div className="border-t border-border pt-5">
              <VisualsPanel
                projectId={project.id}
                videoId={clip.video_id}
                clipId={clip.id}
                duration={clip.duration_seconds}
                video={previewVideo}
                assets={visualAssets}
                onUploaded={visualUploaded}
                elements={visuals}
                onChange={edit(setVisuals)}
              />
            </div>
            <div className="border-t border-border pt-5">
              <AudioPanel
                projectId={project.id}
                value={audio}
                onChange={edit((next: AudioRequest) => {
                  setAudioSection(true);
                  setAudio(next);
                })}
                assets={audioAssets}
                waveforms={waveforms}
                limits={audioLimits}
                duration={clip.duration_seconds}
                video={previewVideo}
                onUploaded={audioUploaded}
              />
            </div>
          </div>
          <div className="space-y-3 border-t border-border px-4 py-4 sm:px-5">
            <p className="text-xs text-muted">
              <span className="text-subtle">Output: </span>
              {settingsSummary}
            </p>
            {action}
            {actionError ? (
              <InlineAlert title="The render could not start">{actionError}</InlineAlert>
            ) : null}
          </div>
        </aside>

        {/* Versions of this clip, named by their settings. */}
        <section aria-labelledby="versions-heading" className="min-w-0 lg:col-start-1 lg:row-start-2">
          <div className="mb-3 flex items-baseline justify-between">
            <h2 id="versions-heading" className="text-sm font-medium text-muted">
              Versions{edits && edits.length > 0 ? <span className="tabular text-subtle"> · {edits.length}</span> : null}
            </h2>
          </div>
          {edits === null && !loadError ? (
            <div role="status" aria-label="Loading versions" className="space-y-2">
              <Skeleton className="h-[78px] rounded-xl" />
              <Skeleton className="h-[78px] rounded-xl" />
            </div>
          ) : loadError ? (
            <ErrorState title="Versions could not be loaded" message={loadError} onRetry={() => void refresh()} />
          ) : edits && edits.length > 0 ? (
            <VersionList
              edits={edits}
              selectedId={mode === "rendered" ? selectedId : null}
              onSelect={showRendered}
              onRetry={(edit) => void retry(edit)}
              retryingId={retryingId}
            />
          ) : (
            <EmptyState
              compact
              icon={Smartphone}
              title="No versions yet"
              description="Create a vertical version ready for short-form platforms."
            />
          )}
        </section>
      </div>
    </>
  );
}

/** /projects/[id]/clips/[clipId] — the focused short-form editing workspace for one clip. */
export function ShortEditorView() {
  const { id, clipId } = useParams<{ id: string; clipId: string }>();
  const load = useCallback(() => loadProjectClip(id, clipId), [id, clipId]);
  const { data, error, loading, reload } = useApi(load);

  if (loading) {
    return (
      <div role="status" aria-label="Loading the editor">
        <Skeleton className="mb-3 h-4 w-32" />
        <Skeleton className="mb-8 h-8 w-72" />
        <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_400px]">
          <Skeleton className="h-[640px] rounded-2xl" />
          <Skeleton className="h-[640px] rounded-2xl" />
        </div>
      </div>
    );
  }
  if (error || !data) {
    const notFound = error === "Clip not found" || error === "Project not found";
    return (
      <>
        <PageHeader back={{ href: isProjectId(id) ? `/projects/${id}` : "/projects", label: "Project" }} title="Short-form editor" />
        {notFound ? (
          <EmptyState
            icon={Clapperboard}
            title="Clip not found"
            description="This clip does not exist or you do not have access to it."
            action={<ButtonLink href="/projects" variant="secondary">Back to projects</ButtonLink>}
          />
        ) : (
          <ErrorState title="The editor could not be loaded" message={error ?? "Unavailable."} onRetry={reload} />
        )}
      </>
    );
  }
  if (data.clip.status !== "ready") {
    return (
      <>
        <PageHeader back={{ href: `/projects/${id}#generated`, label: data.project.name }} title="Short-form editor" />
        <EmptyState
          icon={Clapperboard}
          title="This clip isn't ready yet"
          description="Short-form edits start from a rendered clip. Come back once it shows Ready."
          action={<ButtonLink href={`/projects/${id}#generated`} variant="secondary">Back to the project</ButtonLink>}
        />
      </>
    );
  }
  return <Editor project={data.project} clip={data.clip} />;
}
