/**
 * Tool Discovery — Frontend Application
 *
 * Single-page app controlling navigation, API communication,
 * dashboard, analysis, results, library, configuration, and settings.
 * Features: OpenRouter Free Models & One-Click AI App Installation.
 */

(function () {
  "use strict";

  // ── Constants ──────────────────────────────────────────────
  const API = "";  // same origin

  // ── State ──────────────────────────────────────────────────
  let currentPage = "dashboard";
  let currentAnalysisId = null;
  let currentAnalysisData = null;
  let selectedFile = null;
  let currentToolForModal = null;
  let currentInstallTool = null;
  let currentInstallPlan = null;
  let lastDiscoveredTools = [];
  let lastLibraryTools = [];

  // ScreenApp In-Browser Recorder State
  let mediaRecorder = null;
  let recordedChunks = [];
  let recordingStream = null;
  let recordingTimerInterval = null;
  let recordingSeconds = 0;
  let recordedVideoBlob = null;

  // ── DOM References ─────────────────────────────────────────
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => document.querySelectorAll(sel);

  // ── Initialization ─────────────────────────────────────────
  document.addEventListener("DOMContentLoaded", () => {
    initNavigation();
    initTabs();
    initStudioTabs();
    initScreenRecorder();
    initUploadZone();
    initAnalyzeButtons();
    initLibrary();
    initConfigurations();
    initSettings();
    initModal();
    initInstallModal();
    initAskVideoChat();
    loadDashboard();
  });

  // ── Navigation ─────────────────────────────────────────────
  function initNavigation() {
    $$(".nav-links button[data-page]").forEach((btn) => {
      btn.addEventListener("click", () => navigateTo(btn.dataset.page));
    });

    const menuBtn = $("#mobileMenuBtn");
    const navLinks = $("#navLinks");
    menuBtn.addEventListener("click", () => {
      const open = navLinks.classList.toggle("open");
      menuBtn.setAttribute("aria-expanded", open);
    });

    $("#dashAnalyzeBtn")?.addEventListener("click", () => navigateTo("analyze"));
    $("#backToAnalyzeBtn")?.addEventListener("click", () => navigateTo("analyze"));
    const libAnalyze = $("#libraryAnalyzeBtn");
    if (libAnalyze) libAnalyze.addEventListener("click", () => navigateTo("analyze"));

    // ScreenApp Header & Hero recording triggers
    $("#heroRecordBtn")?.addEventListener("click", openScreenRecorderModal);
    $("#navQuickRecordBtn")?.addEventListener("click", openScreenRecorderModal);
    $("#btnLaunchScreenRecorder")?.addEventListener("click", openScreenRecorderModal);
    $("#studioCopyTranscriptBtn")?.addEventListener("click", copyStudioTranscript);
    $("#btnCopyTranscriptPanel")?.addEventListener("click", copyStudioTranscript);
    $("#studioExportNotesBtn")?.addEventListener("click", exportStudioNotes);
    $("#btnJumpToTranscript")?.addEventListener("click", () => {
      $("#tabBtnTranscript")?.click();
      $("#studioTranscriptScrollArea")?.scrollIntoView({ behavior: "smooth" });
    });
  }

  function navigateTo(page) {
    currentPage = page;
    $$(".nav-links button").forEach((b) => {
      b.classList.toggle("active", b.dataset.page === page);
    });
    $$(".page-section").forEach((s) => s.classList.remove("active"));
    const target = $(`#page${capitalize(page)}`);
    if (target) target.classList.add("active");

    const navLinks = $("#navLinks");
    if (navLinks.classList.contains("open")) {
      navLinks.classList.remove("open");
      $("#mobileMenuBtn").setAttribute("aria-expanded", false);
    }

    if (page === "dashboard") loadDashboard();
    if (page === "library") loadLibrary();
    if (page === "configurations") loadConfigurationToolList();
    if (page === "settings") loadSettings();

    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function capitalize(str) {
    return str.charAt(0).toUpperCase() + str.slice(1);
  }

  // ── Analyze Tabs ───────────────────────────────────────────
  function initTabs() {
    $$(".tab-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        $$(".tab-btn").forEach((b) => {
          b.classList.remove("active");
          b.setAttribute("aria-selected", false);
        });
        $$(".tab-panel").forEach((p) => p.classList.remove("active"));

        btn.classList.add("active");
        btn.setAttribute("aria-selected", true);
        const panel = $(`#${btn.dataset.tab}`);
        if (panel) panel.classList.add("active");
      });
    });
  }

  // ── Upload Zone ────────────────────────────────────────────
  function initUploadZone() {
    const zone = $("#uploadZone");
    const input = $("#videoFileInput");
    const info = $("#uploadFileInfo");
    const nameEl = $("#uploadFileName");

    zone.addEventListener("click", () => input.click());
    zone.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        input.click();
      }
    });

    ["dragenter", "dragover"].forEach((evt) => {
      zone.addEventListener(evt, (e) => {
        e.preventDefault();
        zone.classList.add("dragover");
      });
    });

    ["dragleave", "drop"].forEach((evt) => {
      zone.addEventListener(evt, (e) => {
        e.preventDefault();
        zone.classList.remove("dragover");
      });
    });

    zone.addEventListener("drop", (e) => {
      if (e.dataTransfer.files.length) {
        handleFileSelect(e.dataTransfer.files[0]);
      }
    });

    input.addEventListener("change", () => {
      if (input.files.length) {
        handleFileSelect(input.files[0]);
      }
    });

    function handleFileSelect(file) {
      const allowed = ["video/mp4", "video/webm", "video/quicktime", "video/x-msvideo"];
      if (!allowed.includes(file.type) && !file.name.match(/\.(mp4|webm|mov|avi|m4v)$/i)) {
        showToast("Unsupported file type. Please upload MP4, WebM, or MOV.", "error");
        return;
      }
      selectedFile = file;
      nameEl.textContent = `📎 ${file.name} (${formatBytes(file.size)})`;
      info.classList.remove("hidden");
    }
  }

  // ── Analyze Buttons ────────────────────────────────────────
  function initAnalyzeButtons() {
    $("#analyzeUrlBtn").addEventListener("click", () => {
      const url = $("#videoUrlInput").value.trim();
      if (!url) {
        showToast("Please enter a video URL.", "warning");
        return;
      }
      startAnalysis({ source_type: "url", url });
    });

    $("#analyzeUploadBtn").addEventListener("click", () => {
      if (!selectedFile) {
        showToast("Please select a video file.", "warning");
        return;
      }
      const formData = new FormData();
      formData.append("video", selectedFile);
      startAnalysis({ source_type: "upload" }, formData);
    });

    $("#analyzeTextBtn").addEventListener("click", () => {
      const text = $("#transcriptInput").value.trim();
      if (!text) {
        showToast("Please paste some transcript text.", "warning");
        return;
      }
      if (text.length < 20) {
        showToast("Transcript is too short to analyze meaningfully.", "warning");
        return;
      }
      startAnalysis({ source_type: "text", transcript: text });
    });
  }

  async function startAnalysis(data, formData) {
    showProcessing();

    try {
      let response;
      if (formData) {
        updatePipelineStage("validate", "completed");
        updatePipelineStage("ingest", "completed");
        updatePipelineStage("transcribe", "active");
        response = await fetch(`${API}/api/analyze/upload?async=1`, {
          method: "POST",
          headers: { "X-Async-Job": "1" },
          body: formData,
        });
      } else if (data.source_type === "text") {
        updatePipelineStage("validate", "completed");
        updatePipelineStage("ingest", "completed");
        updatePipelineStage("transcribe", "completed");
        updatePipelineStage("analyze", "active");
        response = await fetch(`${API}/api/analyze/text`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(data),
        });
      } else {
        updatePipelineStage("validate", "active");
        updatePipelineStage("ingest", "active");
        response = await fetch(`${API}/api/analyze/url?async=1`, {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-Async-Job": "1" },
          body: JSON.stringify(data),
        });
      }

      if (!response.ok) {
        const err = await response.json().catch(() => ({ error: "Server error" }));
        throw new Error(err.error || `HTTP ${response.status}`);
      }

      const result = await response.json();
      currentAnalysisId = result.video_id;

      // If job is queued in background, begin status polling
      if (response.status === 202 || (result.status && result.status !== "completed")) {
        pollAnalysisStatus(result.video_id);
        return;
      }

      $$(".pipeline-stage").forEach((s) => {
        updatePipelineStage(s.dataset.stage, "completed");
      });
      $("#processingBadge").className = "badge badge-success";
      $("#processingBadge").textContent = "Completed";

      showToast(`Found ${result.tools_count || 0} tool(s)!`, "success");
      setTimeout(() => showResults(result), 500);

    } catch (err) {
      handleProcessingError(err.message);
    }
  }

  async function pollAnalysisStatus(videoId) {
    let attempts = 0;
    const maxAttempts = 180; // 6 minutes max polling
    const interval = setInterval(async () => {
      attempts++;
      if (attempts > maxAttempts) {
        clearInterval(interval);
        handleProcessingError("Analysis timed out. Please try again or check the dashboard.");
        return;
      }

      try {
        const resp = await fetch(`${API}/api/analysis/${videoId}`);
        if (!resp.ok) return;
        const data = await resp.json();

        if (data.status === "queued" || data.status === "pending") {
          updatePipelineStage("validate", "active");
          $("#processingBadge").className = "badge badge-pending";
          $("#processingBadge").textContent = "In Queue — Preparing Analysis...";
        } else if (data.status === "downloading") {
          updatePipelineStage("validate", "completed");
          updatePipelineStage("ingest", "active");
          $("#processingBadge").className = "badge badge-pending";
          $("#processingBadge").textContent = "Downloading Video...";
        } else if (data.status === "transcribing") {
          updatePipelineStage("validate", "completed");
          updatePipelineStage("ingest", "completed");
          updatePipelineStage("transcribe", "active");
          $("#processingBadge").className = "badge badge-pending";
          $("#processingBadge").textContent = "Transcribing Speech & Frames...";
        } else if (data.status === "analyzing") {
          updatePipelineStage("validate", "completed");
          updatePipelineStage("ingest", "completed");
          updatePipelineStage("transcribe", "completed");
          updatePipelineStage("analyze", "active");
          $("#processingBadge").className = "badge badge-pending";
          $("#processingBadge").textContent = "Discovering AI Tools & Skills...";
        } else if (data.status === "completed") {
          clearInterval(interval);
          $$(".pipeline-stage").forEach((s) => {
            updatePipelineStage(s.dataset.stage, "completed");
          });
          $("#processingBadge").className = "badge badge-success";
          $("#processingBadge").textContent = "Completed";
          showToast(`Found ${data.tools_count || 0} tool(s)!`, "success");
          setTimeout(() => showResults(data), 400);
        } else if (data.status === "failed") {
          clearInterval(interval);
          handleProcessingError(data.error_message || "Video analysis failed.");
        }
      } catch (e) {
        console.debug("Status polling error:", e);
      }
    }, 2000);
  }

  function showProcessing() {
    $("#processingCard").classList.remove("hidden");
    $("#processingError").classList.add("hidden");
    $("#processingBadge").className = "badge badge-pending";
    $("#processingBadge").textContent = "In Progress";
    $$(".pipeline-stage").forEach((s) => {
      s.className = "pipeline-stage";
    });
  }

  function updatePipelineStage(stage, state) {
    const el = $(`.pipeline-stage[data-stage="${stage}"]`);
    if (!el) return;
    el.className = `pipeline-stage ${state}`;
    if (state === "completed") {
      el.querySelector(".stage-indicator").textContent = "✓";
    } else if (state === "error") {
      el.querySelector(".stage-indicator").textContent = "✗";
    }
  }

  function handleProcessingError(message) {
    const errEl = $("#processingError");
    errEl.classList.remove("hidden");
    errEl.innerHTML = `<span>⚠️</span><span>${escapeHtml(message)}</span>`;
    $("#processingBadge").className = "badge badge-error";
    $("#processingBadge").textContent = "Failed";

    const active = $(".pipeline-stage.active");
    if (active) {
      updatePipelineStage(active.dataset.stage, "error");
    }
  }

  // ── ScreenApp Studio Tabs ──────────────────────────────────
  function initStudioTabs() {
    $$(".studio-tab-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        if (btn.dataset.studiotab === "studiotabTools") {
          const section = $("#discoveredToolsCardSection");
          if (section) {
            section.scrollIntoView({ behavior: "smooth", block: "start" });
            return;
          }
        }
        $$(".studio-tab-btn").forEach((b) => b.classList.remove("active"));
        $$(".studio-tab-panel").forEach((p) => p.classList.remove("active"));
        btn.classList.add("active");
        const panel = $(`#${btn.dataset.studiotab}`);
        if (panel) panel.classList.add("active");
      });
    });
  }

  // ── ScreenApp In-Browser Screen Recorder ───────────────────
  function openScreenRecorderModal() {
    const modal = $("#recordingModal");
    if (!modal) return;
    modal.classList.remove("hidden");
    resetRecorderUI();
  }

  function closeScreenRecorderModal() {
    const modal = $("#recordingModal");
    if (!modal) return;
    stopActiveRecordingStream();
    modal.classList.add("hidden");
    resetRecorderUI();
  }

  function stopActiveRecordingStream() {
    if (recordingTimerInterval) {
      clearInterval(recordingTimerInterval);
      recordingTimerInterval = null;
    }
    if (mediaRecorder && mediaRecorder.state !== "inactive") {
      try { mediaRecorder.stop(); } catch (e) {}
    }
    if (recordingStream) {
      recordingStream.getTracks().forEach((track) => track.stop());
      recordingStream = null;
    }
  }

  function resetRecorderUI() {
    recordingSeconds = 0;
    recordedChunks = [];
    recordedVideoBlob = null;
    const badge = $("#recorderTimerBadge");
    if (badge) badge.textContent = "00:00";
    $("#recorderLiveVideo")?.classList.add("hidden");
    $("#recorderPlaybackVideo")?.classList.add("hidden");
    $("#recorderIdleState")?.classList.remove("hidden");
    $("#recorderReviewActions")?.classList.add("hidden");
    $("#btnStartRecording")?.classList.remove("hidden");
    $("#btnPauseRecording")?.classList.add("hidden");
    $("#btnResumeRecording")?.classList.add("hidden");
    $("#btnStopRecording")?.classList.add("hidden");
  }

  function initScreenRecorder() {
    $("#closeRecorderBtn")?.addEventListener("click", closeScreenRecorderModal);

    $("#btnMobileCameraRecord")?.addEventListener("click", () => {
      $("#mobileCameraInput")?.click();
    });

    $("#mobileCameraInput")?.addEventListener("change", (e) => {
      const file = e.target.files?.[0];
      if (!file) return;
      recordedVideoBlob = file;
      const playbackVideo = $("#recorderPlaybackVideo");
      if (playbackVideo) {
        playbackVideo.src = URL.createObjectURL(file);
        playbackVideo.classList.remove("hidden");
      }
      $("#recorderLiveVideo")?.classList.add("hidden");
      $("#recorderIdleState")?.classList.add("hidden");
      $("#recorderReviewActions")?.classList.remove("hidden");
      $("#btnStartRecording")?.classList.add("hidden");
      $("#btnMobileCameraRecord")?.classList.add("hidden");
      showToast("Video loaded! Click 'Transcribe & Extract Skills' to analyze.", "success");
    });

    $("#btnStartRecording")?.addEventListener("click", async () => {
      try {
        const includeMic = $("#recorderMicToggle")?.checked;
        let stream = null;
        let isScreenShare = false;

        // Try getDisplayMedia (Desktop screen capture) if supported
        if (navigator.mediaDevices && typeof navigator.mediaDevices.getDisplayMedia === "function") {
          try {
            stream = await navigator.mediaDevices.getDisplayMedia({
              video: { cursor: "always" },
              audio: true,
            });
            isScreenShare = true;
          } catch (dispErr) {
            if (dispErr.name === "NotAllowedError" || dispErr.name === "AbortError") {
              return; // User cancelled screen selection dialog
            }
            console.warn("getDisplayMedia not supported or failed, falling back to camera:", dispErr);
          }
        }

        // Mobile fallback: Camera & Audio via getUserMedia
        if (!stream && navigator.mediaDevices && typeof navigator.mediaDevices.getUserMedia === "function") {
          try {
            stream = await navigator.mediaDevices.getUserMedia({
              video: { facingMode: "user" },
              audio: includeMic !== false,
            });
          } catch (camErr) {
            console.warn("Camera getUserMedia failed:", camErr);
            // Try audio-only or prompt mobile capture
            try {
              stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            } catch (micErr) {
              $("#mobileCameraInput")?.click();
              return;
            }
          }
        }

        if (!stream) {
          showToast("Live recording unavailable in this browser. Opening camera capture...", "info");
          $("#mobileCameraInput")?.click();
          return;
        }

        let audioTracks = stream.getAudioTracks();

        if (includeMic && isScreenShare && audioTracks.length === 0) {
          try {
            const micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
            const micTrack = micStream.getAudioTracks()[0];
            if (micTrack) audioTracks.push(micTrack);
          } catch (micErr) {
            console.warn("Microphone access skipped or denied:", micErr);
          }
        }

        const combinedStream = new MediaStream([
          ...stream.getVideoTracks(),
          ...audioTracks,
        ]);
        recordingStream = combinedStream;

        const liveVideo = $("#recorderLiveVideo");
        if (liveVideo) {
          liveVideo.srcObject = combinedStream;
          liveVideo.classList.remove("hidden");
        }
        $("#recorderIdleState")?.classList.add("hidden");
        $("#recorderPlaybackVideo")?.classList.add("hidden");

        recordedChunks = [];
        const mimeType = MediaRecorder.isTypeSupported("video/webm;codecs=vp9,opus")
          ? "video/webm;codecs=vp9,opus"
          : MediaRecorder.isTypeSupported("video/webm;codecs=vp8,opus")
          ? "video/webm;codecs=vp8,opus"
          : MediaRecorder.isTypeSupported("video/mp4")
          ? "video/mp4"
          : "video/webm";

        mediaRecorder = new MediaRecorder(combinedStream, { mimeType });
        mediaRecorder.ondataavailable = (e) => {
          if (e.data && e.data.size > 0) recordedChunks.push(e.data);
        };

        mediaRecorder.onstop = () => {
          recordedVideoBlob = new Blob(recordedChunks, { type: mimeType });
          const playbackVideo = $("#recorderPlaybackVideo");
          if (playbackVideo) {
            playbackVideo.src = URL.createObjectURL(recordedVideoBlob);
            playbackVideo.classList.remove("hidden");
          }
          liveVideo?.classList.add("hidden");
          $("#recorderReviewActions")?.classList.remove("hidden");
          $("#btnStopRecording")?.classList.add("hidden");
          $("#btnPauseRecording")?.classList.add("hidden");
          $("#btnResumeRecording")?.classList.add("hidden");

          if (recordingStream) {
            recordingStream.getTracks().forEach((track) => track.stop());
          }
          if (recordingTimerInterval) {
            clearInterval(recordingTimerInterval);
            recordingTimerInterval = null;
          }
        };

        // Handle user clicking native browser "Stop sharing" button
        if (stream.getVideoTracks()[0]) {
          stream.getVideoTracks()[0].onended = () => {
            if (mediaRecorder && mediaRecorder.state !== "inactive") {
              mediaRecorder.stop();
            }
          };
        }

        mediaRecorder.start(1000);

        recordingSeconds = 0;
        const timerBadge = $("#recorderTimerBadge");
        if (timerBadge) timerBadge.textContent = "00:00";
        recordingTimerInterval = setInterval(() => {
          recordingSeconds++;
          const mins = String(Math.floor(recordingSeconds / 60)).padStart(2, "0");
          const secs = String(recordingSeconds % 60).padStart(2, "0");
          if (timerBadge) timerBadge.textContent = `${mins}:${secs}`;
        }, 1000);

        $("#btnStartRecording")?.classList.add("hidden");
        $("#btnPauseRecording")?.classList.remove("hidden");
        $("#btnStopRecording")?.classList.remove("hidden");

      } catch (err) {
        showToast("Screen recording permission was not granted: " + err.message, "error");
      }
    });

    $("#btnPauseRecording")?.addEventListener("click", () => {
      if (mediaRecorder && mediaRecorder.state === "recording") {
        mediaRecorder.pause();
        $("#btnPauseRecording")?.classList.add("hidden");
        $("#btnResumeRecording")?.classList.remove("hidden");
      }
    });

    $("#btnResumeRecording")?.addEventListener("click", () => {
      if (mediaRecorder && mediaRecorder.state === "paused") {
        mediaRecorder.resume();
        $("#btnResumeRecording")?.classList.add("hidden");
        $("#btnPauseRecording")?.classList.remove("hidden");
      }
    });

    $("#btnStopRecording")?.addEventListener("click", () => {
      if (mediaRecorder && mediaRecorder.state !== "inactive") {
        mediaRecorder.stop();
      }
    });

    $("#btnDownloadRecording")?.addEventListener("click", () => {
      if (!recordedVideoBlob) return;
      const url = URL.createObjectURL(recordedVideoBlob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `screenapp_recording_${Date.now()}.webm`;
      a.click();
      URL.revokeObjectURL(url);
    });

    $("#btnDiscardRecording")?.addEventListener("click", resetRecorderUI);

    $("#btnTranscribeRecording")?.addEventListener("click", () => {
      if (!recordedVideoBlob) return;
      const file = new File([recordedVideoBlob], "screen_recording.webm", { type: "video/webm" });
      closeScreenRecorderModal();
      navigateTo("analyze");
      const formData = new FormData();
      formData.append("video", file);
      startAnalysis({ source_type: "upload" }, formData);
    });
  }

  // ── Results & Video Studio Rendering ─────────────────────────
  function showResults(result) {
    navigateTo("results");
    currentAnalysisData = result;
    currentAnalysisId = result.video_id;

    // Header info
    const titleEl = $("#studioVideoTitle");
    if (titleEl) titleEl.textContent = result.title || "Video Analysis";

    const sourceEl = $("#studioSourceBadge");
    if (sourceEl) {
      const src = result.source_type || "video";
      sourceEl.textContent = src === "youtube" ? "YouTube" :
                             src === "upload" ? "ScreenApp Upload" :
                             src === "instagram" ? "Instagram Reel" : "Transcript";
    }

    const timeSavedEl = $("#studioTimeSavedBadge");
    if (timeSavedEl) {
      const words = (result.transcript || "").split(/\s+/).length;
      const minutesSaved = Math.max(5, Math.round(words / 130));
      timeSavedEl.textContent = `⏱️ ~${minutesSaved} min watch time saved`;
    }

    // Video Player Injection
    const playerWrapper = $("#studioPlayerWrapper");
    if (playerWrapper) {
      if (result.source_type === "youtube" && result.source_url) {
        const ytid = extractYoutubeId(result.source_url) || result.video_id_code;
        if (ytid) {
          playerWrapper.innerHTML = `
            <iframe id="studioYoutubeIframe"
                    src="https://www.youtube.com/embed/${ytid}?enablejsapi=1"
                    allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                    allowfullscreen></iframe>`;
        } else {
          playerWrapper.innerHTML = `<div class="player-placeholder"><div class="player-icon">🎬</div><p>${escapeHtml(result.title || "YouTube Video")}</p></div>`;
        }
      } else if (result.media_url) {
        playerWrapper.innerHTML = `
          <video id="studioHtml5Video" controls playsinline src="${result.media_url}" style="width:100%;height:100%;object-fit:contain;background:#000;">
          </video>`;
        const videoEl = $("#studioHtml5Video");
        if (videoEl) {
          videoEl.addEventListener("timeupdate", () => {
            const curTime = $("#playerCurrentTime");
            if (curTime) curTime.textContent = formatTimestamp(videoEl.currentTime);
          });
        }
      } else {
        playerWrapper.innerHTML = `
          <div class="player-placeholder">
            <div class="player-icon">📝</div>
            <p style="font-weight:600;">Text Transcript Analysis</p>
          </div>`;
      }
    }

    // Summary & Takeaways
    const summaryEl = $("#studioSummaryText");
    if (summaryEl) {
      summaryEl.textContent = result.summary || "Summary generated from transcript.";
    }

    const takeawaysEl = $("#studioKeyTakeawaysList");
    if (takeawaysEl) {
      const takeaways = result.key_takeaways || [];
      if (takeaways.length) {
        takeawaysEl.innerHTML = takeaways.map((t) => `<li>${escapeHtml(t)}</li>`).join("");
      } else {
        takeawaysEl.innerHTML = `<li>Transcribed and analyzed with ScreenApp AI.</li>`;
      }
    }

    // Transcript Tab (Rendered first & made active by default)
    const transcriptText = (result.transcript || result.full_text || result.transcript_text || "").trim();
    const transcriptSegments = result.segments || [];
    currentAnalysisData.transcript = transcriptText;
    currentAnalysisData.segments = transcriptSegments;

    const wordCount = transcriptText ? transcriptText.split(/\s+/).filter(Boolean).length : 0;
    const wordCountEl = $("#studioTranscriptWordCount");
    if (wordCountEl) {
      wordCountEl.textContent = `${wordCount.toLocaleString()} words`;
    }

    renderTranscriptSegments(transcriptSegments, transcriptText);

    // Skills Tab
    const skills = result.skills || [];
    $("#studioSkillsCount").textContent = skills.length;
    renderSkillsList(skills);

    // Tools Tab & Dedicated Tools Section
    const tools = result.tools || [];
    $("#studioToolsCount").textContent = tools.length;
    const headerBadge = $("#studioToolsHeaderBadge");
    if (headerBadge) {
      headerBadge.textContent = `${tools.length} ${tools.length === 1 ? 'Tool' : 'Tools'}`;
    }
    lastDiscoveredTools = tools;
    const toolCardsContainer = $("#resultsToolCards");
    const emptyTools = $("#resultsEmpty");
    if (tools.length === 0) {
      toolCardsContainer.innerHTML = "";
      emptyTools.classList.remove("hidden");
    } else {
      emptyTools.classList.add("hidden");
      toolCardsContainer.innerHTML = tools.map((tool) => renderToolCard(tool, "result")).join("");
      attachCardHandlers(toolCardsContainer, tools, "result");
    }

    // Make Transcript tab active by default so the user sees the transcript immediately!
    $("#tabBtnTranscript")?.click();
  }

  function renderSkillsList(skills) {
    const container = $("#studioSkillsList");
    if (!container) return;

    if (!skills || skills.length === 0) {
      container.innerHTML = `
        <div class="empty-state" style="padding: var(--sp-6);">
          <div class="empty-icon">🧠</div>
          <p>No specific individual skills tagged. View the full summary and tools for details.</p>
        </div>`;
      return;
    }

    container.innerHTML = skills.map((sk) => {
      const tsBtn = sk.timestamp
        ? `<button class="skill-timestamp-badge" data-time="${escapeHtml(sk.timestamp)}">⏱️ ${escapeHtml(sk.timestamp)}</button>`
        : '';
      return `
        <div class="skill-card">
          <div class="skill-card-top">
            <span class="skill-domain-pill">${escapeHtml(sk.domain || "Technical Skill")}</span>
            ${tsBtn}
          </div>
          <h4 class="skill-title">${escapeHtml(sk.name)}</h4>
          <p class="skill-desc">${escapeHtml(sk.description || "")}</p>
        </div>
      `;
    }).join("");

    container.querySelectorAll(".skill-timestamp-badge").forEach((btn) => {
      btn.addEventListener("click", () => {
        const timeStr = btn.dataset.time;
        const secs = parseTimestampToSeconds(timeStr);
        if (secs !== null) seekStudioVideo(secs);
      });
    });
  }

  function renderTranscriptSegments(segments, fullText) {
    const container = $("#studioTranscriptScrollArea");
    if (!container) return;

    if (!segments || segments.length === 0) {
      if (fullText && fullText.trim()) {
        const paragraphs = fullText.split(/\n+/).map((p) => p.trim()).filter(Boolean);
        if (paragraphs.length > 1) {
          container.innerHTML = paragraphs.map((para, idx) => {
            const estSec = idx * 15;
            const timeStr = formatTimestamp(estSec);
            return `
              <div class="transcript-line" data-start="${estSec}">
                <button class="transcript-timestamp-btn" data-time="${estSec}">${timeStr}</button>
                <div class="transcript-text">${escapeHtml(para)}</div>
              </div>
            `;
          }).join("");

          container.querySelectorAll(".transcript-timestamp-btn").forEach((btn) => {
            btn.addEventListener("click", () => {
              const sec = parseFloat(btn.dataset.time);
              seekStudioVideo(sec);
            });
          });
        } else {
          container.innerHTML = `
            <div class="transcript-line" data-start="0">
              <button class="transcript-timestamp-btn" data-time="0">00:00</button>
              <div class="transcript-text" style="line-height:1.7;">${escapeHtml(fullText)}</div>
            </div>`;
        }
      } else {
        container.innerHTML = `
          <div class="empty-state" style="padding:var(--sp-6);">
            <div class="empty-icon">📝</div>
            <p>No transcript text available for this video yet.</p>
          </div>`;
      }
      return;
    }

    container.innerHTML = segments.map((seg) => {
      const startSec = Math.round(seg.start || 0);
      const timeStr = formatTimestamp(startSec);
      return `
        <div class="transcript-line" data-start="${startSec}">
          <button class="transcript-timestamp-btn" data-time="${startSec}">${timeStr}</button>
          <div class="transcript-text">${escapeHtml(seg.text || "")}</div>
        </div>
      `;
    }).join("");

    container.querySelectorAll(".transcript-timestamp-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const sec = parseFloat(btn.dataset.time);
        seekStudioVideo(sec);
      });
    });

    // Transcript Search Filter
    const searchInput = $("#transcriptSearchInput");
    if (searchInput) {
      searchInput.oninput = (e) => {
        const query = e.target.value.toLowerCase().trim();
        container.querySelectorAll(".transcript-line").forEach((line) => {
          const text = line.querySelector(".transcript-text")?.textContent.toLowerCase() || "";
          line.style.display = query === "" || text.includes(query) ? "flex" : "none";
        });
      };
    }
  }

  function seekStudioVideo(seconds) {
    const timer = $("#playerCurrentTime");
    if (timer) timer.textContent = formatTimestamp(seconds);

    const html5 = $("#studioHtml5Video");
    if (html5) {
      html5.currentTime = seconds;
      html5.play().catch(() => {});
      return;
    }

    const yt = $("#studioYoutubeIframe");
    if (yt && yt.contentWindow) {
      yt.contentWindow.postMessage(JSON.stringify({
        event: "command",
        func: "seekTo",
        args: [seconds, true]
      }), "*");
    }
  }

  function copyStudioTranscript() {
    if (!currentAnalysisData || !currentAnalysisData.transcript) {
      showToast("No transcript text available to copy.", "warning");
      return;
    }
    navigator.clipboard.writeText(currentAnalysisData.transcript).then(() => {
      showToast("Transcript copied to clipboard!", "success");
    }).catch(() => {
      showToast("Could not copy transcript.", "error");
    });
  }

  function exportStudioNotes() {
    if (!currentAnalysisData) {
      showToast("No active video analysis to export.", "warning");
      return;
    }
    const d = currentAnalysisData;
    let md = `# ${d.title || "ScreenApp Video Analysis"}\n\n`;
    md += `**Source**: ${d.source_type || "Video"}\n`;
    if (d.source_url) md += `**URL**: ${d.source_url}\n`;
    md += `**Date**: ${new Date().toLocaleDateString()}\n\n`;

    md += `## 📋 Executive Summary\n${d.summary || "N/A"}\n\n`;

    if (d.key_takeaways && d.key_takeaways.length) {
      md += `## 🎯 Key Takeaways\n`;
      d.key_takeaways.forEach((t) => { md += `- ${t}\n`; });
      md += `\n`;
    }

    if (d.skills && d.skills.length) {
      md += `## 🧠 Skills Demonstrated\n`;
      d.skills.forEach((s) => {
        md += `### ${s.name} (${s.domain || "Skill"})\n`;
        if (s.timestamp) md += `- **Timestamp**: ${s.timestamp}\n`;
        if (s.description) md += `- **Description**: ${s.description}\n`;
        md += `\n`;
      });
    }

    if (d.tools && d.tools.length) {
      md += `## 🛠️ Discovered Tools\n`;
      d.tools.forEach((t) => {
        md += `### ${t.name} [${t.category || "Tool"}]\n`;
        if (t.purpose) md += `- **Purpose**: ${t.purpose}\n`;
        if (t.official_website) md += `- **Official Website**: ${t.official_website}\n`;
        if (t.repository_url) md += `- **Repository**: ${t.repository_url}\n`;
        md += `\n`;
      });
    }

    if (d.transcript) {
      md += `## 📝 Transcript\n${d.transcript}\n`;
    }

    const blob = new Blob([md], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${(d.title || "video_notes").replace(/[^a-zA-Z0-9_-]/g, "_")}_notes.md`;
    a.click();
    URL.revokeObjectURL(url);
    showToast("Notes exported as Markdown!", "success");
  }

  // ── Ask Video AI Chat ───────────────────────────────────────
  function initAskVideoChat() {
    const form = $("#askChatForm");
    const input = $("#askQuestionInput");
    const history = $("#askChatHistory");
    if (!form || !input || !history) return;

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const question = input.value.trim();
      if (!question) return;

      if (!currentAnalysisId) {
        showToast("Please analyze a video first.", "warning");
        return;
      }

      // Append user message
      const userBubble = document.createElement("div");
      userBubble.className = "ask-user-msg";
      userBubble.innerHTML = `<div class="ask-msg-bubble">${escapeHtml(question)}</div>`;
      history.appendChild(userBubble);
      input.value = "";
      history.scrollTop = history.scrollHeight;

      // Append loading bubble
      const loadingBubble = document.createElement("div");
      loadingBubble.className = "ask-ai-msg";
      loadingBubble.innerHTML = `<div class="ask-msg-bubble"><em>ScreenApp AI is searching the transcript…</em></div>`;
      history.appendChild(loadingBubble);
      history.scrollTop = history.scrollHeight;

      try {
        const resp = await fetch(`${API}/api/video/ask`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ video_id: currentAnalysisId, question }),
        });
        const data = await resp.json();
        if (data.answer) {
          const formatted = escapeHtml(data.answer).replace(/\[(\d{1,2}:\d{2})\]/g, (match, p1) => {
            return `<button class="skill-timestamp-badge" style="margin: 0 4px;" data-time="${p1}">⏱️ ${p1}</button>`;
          });
          loadingBubble.innerHTML = `<div class="ask-msg-bubble">${formatted}</div>`;

          loadingBubble.querySelectorAll(".skill-timestamp-badge").forEach((b) => {
            b.addEventListener("click", () => {
              const sec = parseTimestampToSeconds(b.dataset.time);
              if (sec !== null) seekStudioVideo(sec);
            });
          });
        } else {
          loadingBubble.innerHTML = `<div class="ask-msg-bubble text-muted">${escapeHtml(data.error || "No answer found.")}</div>`;
        }
      } catch (err) {
        loadingBubble.innerHTML = `<div class="ask-msg-bubble text-error">Error communicating with AI: ${escapeHtml(err.message)}</div>`;
      }
      history.scrollTop = history.scrollHeight;
    });
  }

  // ── Helper Utilities ───────────────────────────────────────
  function formatTimestamp(seconds) {
    if (isNaN(seconds)) return "00:00";
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  }

  function parseTimestampToSeconds(str) {
    if (!str) return null;
    const parts = str.trim().replace(/[\[\]]/g, "").split(":");
    if (parts.length === 2) {
      return parseInt(parts[0], 10) * 60 + parseFloat(parts[1]);
    }
    if (parts.length === 3) {
      return parseInt(parts[0], 10) * 3600 + parseInt(parts[1], 10) * 60 + parseFloat(parts[2]);
    }
    const val = parseFloat(str);
    return isNaN(val) ? null : val;
  }

  function extractYoutubeId(url) {
    if (!url) return null;
    const regExp = /^.*(youtu.be\/|v\/|u\/\w\/|embed\/|watch\?v=|&v=|shorts\/)([^#&?]*).*/;
    const match = url.match(regExp);
    return (match && match[2].length === 11) ? match[2] : null;
  }

  function attachCardHandlers(container, tools, context) {
    container.querySelectorAll(".tool-card").forEach((card) => {
      card.addEventListener("click", (e) => {
        if (e.target.closest("a") || e.target.closest("button")) return;
        const toolId = parseInt(card.dataset.toolId, 10);
        const tool = tools.find((t) => t.id === toolId);
        if (tool) openToolModal(tool, context);
      });

      card.querySelectorAll(".save-tool-btn").forEach((btn) => {
        btn.addEventListener("click", (e) => {
          e.stopPropagation();
          const toolId = parseInt(btn.dataset.toolId, 10);
          const tool = tools.find((t) => t.id === toolId);
          if (tool) saveTool(tool);
        });
      });

      card.querySelectorAll(".install-tool-btn").forEach((btn) => {
        btn.addEventListener("click", (e) => {
          e.stopPropagation();
          const toolId = parseInt(btn.dataset.toolId, 10);
          const tool = tools.find((t) => t.id === toolId);
          if (tool) openInstallModal(tool);
        });
      });

      card.querySelectorAll(".remove-tool-btn").forEach((btn) => {
        btn.addEventListener("click", (e) => {
          e.stopPropagation();
          removeSavedTool(parseInt(btn.dataset.toolId, 10));
        });
      });
    });
  }

  // ── Tool Card Rendering ────────────────────────────────────
  function renderToolCard(tool, context) {
    const verifiedBadge = tool.verified
      ? '<span class="badge badge-success">✓ Verified</span>'
      : '<span class="badge badge-warning">Unverified</span>';

    const mentionBadge = tool.mention_type === "explicit"
      ? '<span class="badge badge-teal">Explicit</span>'
      : '<span class="badge badge-info">Inferred</span>';

    const categoryTag = tool.category
      ? `<span class="category-tag">${escapeHtml(tool.category)}</span>`
      : "";

    let links = "";
    if (tool.official_website) {
      links += `<a href="${escapeAttr(tool.official_website)}" target="_blank" rel="noopener noreferrer">🌐 Website</a>`;
    }
    if (tool.documentation_url) {
      links += `<a href="${escapeAttr(tool.documentation_url)}" target="_blank" rel="noopener noreferrer">📄 Docs</a>`;
    }
    if (tool.repository_url) {
      links += `<a href="${escapeAttr(tool.repository_url)}" target="_blank" rel="noopener noreferrer">💻 Repo</a>`;
    }

    const saveBtn = context === "result"
      ? `<button class="btn btn-sm btn-primary save-tool-btn" data-tool-id="${tool.id}">💾 Save</button>`
      : "";
    const removeBtn = context === "library"
      ? `<button class="btn btn-sm btn-danger remove-tool-btn" data-tool-id="${tool.id}">🗑️ Remove</button>`
      : "";
    const installBtn = `<button class="btn btn-sm btn-secondary install-tool-btn" data-tool-id="${tool.id}">🚀 Install in AI App</button>`;

    return `
      <div class="tool-card" data-tool-id="${tool.id}" tabindex="0" role="button"
           aria-label="View details for ${escapeAttr(tool.name || 'Unknown tool')}">
        <div class="tool-name">
          ${escapeHtml(tool.name || "Unknown Tool")}
        </div>
        <div class="tool-purpose">${escapeHtml(tool.purpose || "No description available.")}</div>
        <div class="tool-meta">
          ${categoryTag}
          ${verifiedBadge}
          ${mentionBadge}
        </div>
        ${links ? `<div class="tool-links">${links}</div>` : ""}
        <div class="tool-actions mt-3 flex-wrap gap-2">
          ${installBtn}
          ${saveBtn}
          ${removeBtn}
        </div>
      </div>
    `;
  }

  // ── Tool Detail Modal ──────────────────────────────────────
  function initModal() {
    $("#modalCloseBtn").addEventListener("click", closeModal);
    $("#modalDismissBtn").addEventListener("click", closeModal);
    $("#toolDetailModal").addEventListener("click", (e) => {
      if (e.target === e.currentTarget) closeModal();
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        closeModal();
        closeInstallModal();
      }
    });
    $("#modalSaveBtn").addEventListener("click", () => {
      if (currentToolForModal) saveTool(currentToolForModal);
    });
    $("#modalInstallBtn").addEventListener("click", () => {
      if (currentToolForModal) {
        const tool = currentToolForModal;
        closeModal();
        openInstallModal(tool);
      }
    });

    // Privacy & Architecture Notice Modal
    const privModal = $("#privacyModal");
    const privLink = $("#privacyLink");
    const privClose = $("#privacyModalCloseBtn");
    const privDismiss = $("#privacyModalDismissBtn");
    if (privLink && privModal) {
      privLink.addEventListener("click", () => privModal.classList.add("open"));
      if (privClose) privClose.addEventListener("click", () => privModal.classList.remove("open"));
      if (privDismiss) privDismiss.addEventListener("click", () => privModal.classList.remove("open"));
      privModal.addEventListener("click", (e) => {
        if (e.target === e.currentTarget) privModal.classList.remove("open");
      });
    }
  }

  function openToolModal(tool, context) {
    currentToolForModal = tool;
    $("#modalToolName").textContent = tool.name || "Tool Details";
    $("#modalSaveBtn").classList.toggle("hidden", context === "library");

    const body = $("#modalBody");
    body.innerHTML = renderToolDetails(tool);
    $("#toolDetailModal").classList.add("open");
  }

  function closeModal() {
    $("#toolDetailModal").classList.remove("open");
    currentToolForModal = null;
  }

  function renderToolDetails(tool) {
    const rows = [];
    const addRow = (label, value) => {
      if (value && value !== "null") {
        rows.push(`
          <div class="detail-row">
            <div class="detail-label">${escapeHtml(label)}</div>
            <div class="detail-value">${value}</div>
          </div>
        `);
      }
    };

    addRow("Category", escapeHtml(tool.category || "—"));
    addRow("Purpose", escapeHtml(tool.purpose || "—"));
    addRow("Mention Type", tool.mention_type === "explicit" ? "Explicitly mentioned" : "Inferred from context");
    addRow("Verified", tool.verified ? "✅ Yes" : "⚠️ Not verified — URLs and claims may be unverified");

    if (tool.verification_details) {
      addRow("Verification Details", escapeHtml(tool.verification_details));
    }

    if (tool.capabilities && Array.isArray(tool.capabilities) && tool.capabilities.length) {
      addRow("Capabilities", `<ul>${tool.capabilities.map((c) => `<li>${escapeHtml(c)}</li>`).join("")}</ul>`);
    }

    if (tool.evidence_excerpt) {
      addRow("Evidence Excerpt", `<div class="code-block">${escapeHtml(tool.evidence_excerpt)}</div>`);
    }

    if (tool.official_website) {
      addRow("Website", `<a href="${escapeAttr(tool.official_website)}" target="_blank" rel="noopener noreferrer">${escapeHtml(tool.official_website)}</a>`);
    }
    if (tool.documentation_url) {
      addRow("Documentation", `<a href="${escapeAttr(tool.documentation_url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(tool.documentation_url)}</a>`);
    }
    if (tool.repository_url) {
      addRow("Repository", `<a href="${escapeAttr(tool.repository_url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(tool.repository_url)}</a>`);
    }

    if (tool.requirements && Array.isArray(tool.requirements) && tool.requirements.length) {
      addRow("Requirements", `<ul>${tool.requirements.map((r) => `<li>${escapeHtml(r)}</li>`).join("")}</ul>`);
    }

    if (tool.setup_steps && Array.isArray(tool.setup_steps) && tool.setup_steps.length) {
      addRow("Setup Steps", `<ol>${tool.setup_steps.map((s) => `<li>${escapeHtml(s)}</li>`).join("")}</ol>`);
    }

    return rows.join("");
  }

  // ── One-Click Install in AI App Modal ──────────────────────
  function initInstallModal() {
    $("#installModalCloseBtn").addEventListener("click", closeInstallModal);
    $("#installDismissBtn").addEventListener("click", closeInstallModal);
    $("#installModal").addEventListener("click", (e) => {
      if (e.target === e.currentTarget) closeInstallModal();
    });

    $("#installTargetSelect").addEventListener("change", (e) => {
      if (currentInstallTool) {
        loadInstallPlan(currentInstallTool, e.target.value);
      }
    });

    $("#installCopyPromptBtn").addEventListener("click", () => {
      if (currentInstallPlan && currentInstallPlan.copyable_prompt) {
        navigator.clipboard.writeText(currentInstallPlan.copyable_prompt).then(() => {
          showToast("AI Assistant prompt copied to clipboard!", "success");
        });
      }
    });

    $("#installCopyConfigBtn").addEventListener("click", () => {
      if (currentInstallPlan) {
        const text = currentInstallPlan.config_changes?.snippet ||
          (currentInstallPlan.commands || []).join("\n");
        navigator.clipboard.writeText(text).then(() => {
          showToast("Configuration copied to clipboard!", "success");
        });
      }
    });

    $("#installApproveBtn").addEventListener("click", executeApprovedInstall);
  }

  async function openInstallModal(tool) {
    currentInstallTool = tool;
    $("#installModalTitle").textContent = `Install ${tool.name || "Tool"}`;
    $("#installModalSubtitle").textContent = tool.purpose || "";
    $("#installModal").classList.add("open");
    const target = $("#installTargetSelect").value || "claude-code";
    await loadInstallPlan(tool, target);
  }

  function closeInstallModal() {
    $("#installModal").classList.remove("open");
    currentInstallTool = null;
    currentInstallPlan = null;
  }

  async function loadInstallPlan(tool, target) {
    const container = $("#installPlanDetails");
    container.innerHTML = '<div style="padding: var(--sp-6); text-align: center;">⏳ Generating target-specific installation plan…</div>';
    $("#installLogBox").classList.add("hidden");
    $("#installApproveBtn").disabled = true;

    try {
      const resp = await fetch(`${API}/api/install/plan`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tool, target }),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.error || "Failed to generate installation plan");
      }
      const plan = await resp.json();
      currentInstallPlan = plan;

      $("#installIntegrationType").textContent = (plan.integration_type || "manual").toUpperCase();
      $("#installStatusBadge").className = "badge badge-pending";
      $("#installStatusBadge").textContent = "Ready to install";

      let html = "";

      if (plan.prerequisites && plan.prerequisites.length) {
        html += `
          <div class="mb-4">
            <label class="form-label">Prerequisites</label>
            <ul style="padding-left: 20px; font-size: var(--text-sm);">
              ${plan.prerequisites.map((p) => `<li>✔ ${escapeHtml(p)}</li>`).join("")}
            </ul>
          </div>
        `;
      }

      if (plan.permissions && plan.permissions.length) {
        html += `
          <div class="mb-4">
            <label class="form-label">Permissions Requested</label>
            <div>
              ${plan.permissions.map((p) => `<span class="badge badge-warning" style="margin-right: 6px;">🔑 ${escapeHtml(p)}</span>`).join("")}
            </div>
          </div>
        `;
      }

      if (plan.commands && plan.commands.length) {
        html += `
          <div class="mb-4">
            <label class="form-label">Commands</label>
            <pre class="code-preview" style="background: var(--bg-surface); padding: var(--sp-3); border-radius: var(--radius-md); font-size: var(--text-sm);">${escapeHtml(plan.commands.join("\n"))}</pre>
          </div>
        `;
      }

      if (plan.config_changes && plan.config_changes.snippet) {
        html += `
          <div class="mb-4">
            <label class="form-label">Configuration Preview (${escapeHtml(plan.config_changes.file || "settings")})</label>
            <pre class="code-preview" style="background: var(--bg-surface); padding: var(--sp-3); border-radius: var(--radius-md); font-size: var(--text-sm); max-height: 180px; overflow-y: auto;">${escapeHtml(plan.config_changes.snippet)}</pre>
          </div>
        `;
      }

      if (plan.potential_risks && plan.potential_risks.length) {
        html += `
          <div class="notice notice-warning mt-2 mb-2">
            <span>⚠️</span>
            <div>
              <strong>Potential Risks & Security Guidance:</strong>
              ${plan.potential_risks.map((r) => `<div>• ${escapeHtml(r)}</div>`).join("")}
            </div>
          </div>
        `;
      }

      container.innerHTML = html;
      $("#installApproveBtn").disabled = false;

    } catch (err) {
      container.innerHTML = `<div class="notice notice-error"><span>⚠️</span><span>${escapeHtml(err.message)}</span></div>`;
      $("#installApproveBtn").disabled = true;
    }
  }

  async function executeApprovedInstall() {
    if (!currentInstallPlan) return;
    const btn = $("#installApproveBtn");
    btn.disabled = true;
    $("#installStatusBadge").className = "badge badge-pending";
    $("#installStatusBadge").textContent = "Installing…";
    $("#installLogBox").classList.remove("hidden");
    $("#installLogContent").textContent = "Contacting Local Companion Agent...\nExecuting verified action...\n";

    try {
      const resp = await fetch(`${API}/api/install/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          job_id: currentInstallPlan.job_id,
          approved: true,
          companion_payload: currentInstallPlan.companion_payload,
        }),
      });

      const res = await resp.json();
      $("#installLogContent").textContent += res.execution_log || res.message || "";

      if (res.status === "Installed and verified") {
        $("#installStatusBadge").className = "badge badge-success";
        $("#installStatusBadge").textContent = "✓ Installed & Verified";
        showToast(res.message, "success");
      } else if (res.status === "Manual setup required") {
        $("#installStatusBadge").className = "badge badge-info";
        $("#installStatusBadge").textContent = "Manual setup required";
        showToast(res.message, "info");
      } else {
        $("#installStatusBadge").className = "badge badge-error";
        $("#installStatusBadge").textContent = "Failed";
        showToast(res.message || "Installation failed", "error");
      }
    } catch (err) {
      $("#installStatusBadge").className = "badge badge-error";
      $("#installStatusBadge").textContent = "Failed";
      $("#installLogContent").textContent += `\nError: ${err.message}`;
      showToast(err.message, "error");
    } finally {
      btn.disabled = false;
    }
  }

  // ── Dashboard ──────────────────────────────────────────────
  async function loadDashboard() {
    try {
      const resp = await fetch(`${API}/api/dashboard`);
      if (!resp.ok) throw new Error("Failed to load dashboard");
      const data = await resp.json();

      $("#statTotalAnalyses").textContent = data.stats.total_analyses;
      $("#statCompleted").textContent = data.stats.completed_analyses;
      $("#statDiscovered").textContent = data.stats.total_discovered_tools;
      $("#statSaved").textContent = data.stats.total_saved_tools;

      const list = $("#recentAnalysesList");
      if (!data.recent_analyses || data.recent_analyses.length === 0) {
        list.innerHTML = `
          <div class="empty-state" style="padding: var(--sp-8);">
            <div class="empty-icon">📹</div>
            <h3>No analyses yet</h3>
            <p>Start by analyzing a video or pasting a transcript.</p>
          </div>
        `;
        return;
      }

      list.innerHTML = '<div class="analysis-list">' +
        data.recent_analyses.map((v) => {
          const icon = v.source_type === "youtube" ? "🎬" :
                       v.source_type === "instagram" ? "📱" :
                       v.source_type === "upload" ? "📁" : "📝";
          const statusBadge = `<span class="badge badge-${v.status === 'completed' ? 'success' : v.status === 'failed' ? 'error' : 'pending'}">${v.status}</span>`;
          const title = v.title || v.source_url || v.original_filename || "Text analysis";
          const date = formatDate(v.created_at);
          return `
            <div class="analysis-item" data-video-id="${v.id}">
              <div class="analysis-icon">${icon}</div>
              <div class="analysis-info">
                <div class="analysis-title">${escapeHtml(title)}</div>
                <div class="analysis-date">${date}</div>
              </div>
              ${statusBadge}
            </div>
          `;
        }).join("") + '</div>';

      list.querySelectorAll(".analysis-item").forEach((item) => {
        item.addEventListener("click", () => {
          const vid = parseInt(item.dataset.videoId, 10);
          loadAnalysisResults(vid);
        });
      });
    } catch (err) {
      console.error("Dashboard load error:", err);
    }
  }

  async function loadAnalysisResults(videoId) {
    try {
      const resp = await fetch(`${API}/api/analysis/${videoId}`);
      if (!resp.ok) throw new Error("Failed to load analysis");
      const result = await resp.json();
      if (result.status && result.status !== "completed" && result.status !== "failed") {
        navigateTo("analyze");
        showProcessing();
        pollAnalysisStatus(videoId);
        return;
      }
      showResults(result);
    } catch (err) {
      showToast("Failed to load analysis results.", "error");
    }
  }

  // ── Library ────────────────────────────────────────────────
  function initLibrary() {
    let debounce;
    $("#librarySearchInput").addEventListener("input", (e) => {
      clearTimeout(debounce);
      debounce = setTimeout(() => loadLibrary(e.target.value), 300);
    });

    $$("#libraryFilterBar .filter-chip").forEach((chip) => {
      chip.addEventListener("click", () => {
        $$("#libraryFilterBar .filter-chip").forEach((c) => c.classList.remove("active"));
        chip.classList.add("active");
        loadLibrary();
      });
    });
  }

  async function loadLibrary(search) {
    const activeChip = $("#libraryFilterBar .filter-chip.active");
    const category = activeChip && activeChip.dataset.category !== "all"
      ? activeChip.dataset.category : "";

    if (search === undefined) {
      search = $("#librarySearchInput").value.trim();
    }

    try {
      const params = new URLSearchParams();
      if (search) params.set("search", search);
      if (category) params.set("category", category);

      const resp = await fetch(`${API}/api/library?${params}`);
      if (!resp.ok) throw new Error("Failed to load library");
      const data = await resp.json();

      const container = $("#libraryToolCards");
      const empty = $("#libraryEmpty");
      const tools = data.tools || [];
      lastLibraryTools = tools;

      if (tools.length === 0) {
        container.innerHTML = "";
        empty.classList.remove("hidden");
        return;
      }

      empty.classList.add("hidden");
      container.innerHTML = tools.map((t) => renderToolCard(t, "library")).join("");
      attachCardHandlers(container, tools, "library");

    } catch (err) {
      console.error("Library load error:", err);
    }
  }

  async function saveTool(tool) {
    try {
      const resp = await fetch(`${API}/api/library/save`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ discovered_tool_id: tool.id }),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.error || "Failed to save");
      }
      showToast(`"${tool.name}" saved to library!`, "success");
      closeModal();
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function removeSavedTool(toolId) {
    try {
      const resp = await fetch(`${API}/api/library/${toolId}`, { method: "DELETE" });
      if (!resp.ok) throw new Error("Failed to remove");
      showToast("Tool removed from library.", "success");
      loadLibrary();
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  // ── Configurations ─────────────────────────────────────────
  function initConfigurations() {
    const toolSel = $("#configToolSelect");
    const targetSel = $("#configTargetSelect");
    const genBtn = $("#generateConfigBtn");
    const copyBtn = $("#copyConfigBtn");

    const updateGenBtn = () => {
      genBtn.disabled = !toolSel.value || !targetSel.value;
    };
    toolSel.addEventListener("change", updateGenBtn);
    targetSel.addEventListener("change", updateGenBtn);

    genBtn.addEventListener("click", generateConfig);
    copyBtn.addEventListener("click", () => {
      const code = $("#configOutputBody .code-block");
      if (code) {
        navigator.clipboard.writeText(code.textContent).then(() => {
          showToast("Configuration copied!", "success");
        });
      }
    });
  }

  async function loadConfigurationToolList() {
    try {
      const resp = await fetch(`${API}/api/library`);
      if (!resp.ok) return;
      const data = await resp.json();
      const sel = $("#configToolSelect");
      const current = sel.value;

      sel.innerHTML = '<option value="">Choose a saved tool…</option>' +
        (data.tools || []).map((t) =>
          `<option value="${t.id}" ${t.id == current ? "selected" : ""}>${escapeHtml(t.name)} (${escapeHtml(t.category || "tool")})</option>`
        ).join("");
    } catch (err) {
      console.error("Config tool list load error:", err);
    }
  }

  async function generateConfig() {
    const toolId = $("#configToolSelect").value;
    const target = $("#configTargetSelect").value;
    if (!toolId || !target) return;

    try {
      const resp = await fetch(`${API}/api/configurations/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tool_id: parseInt(toolId, 10), target }),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.error || "Failed to generate");
      }
      const data = await resp.json();

      const card = $("#configOutputCard");
      card.classList.remove("hidden");
      $("#configOutputTitle").textContent = `${data.target_label} Configuration for ${data.tool_name}`;

      let html = "";
      if (data.config_content) {
        html += `<pre class="code-block">${escapeHtml(data.config_content)}</pre>`;
      }
      if (data.instructions) {
        html += `<div class="mt-4" style="white-space: pre-line;">${escapeHtml(data.instructions)}</div>`;
      }
      if (data.dependencies && data.dependencies.length) {
        html += `<div class="mt-4"><strong>Dependencies:</strong><ul>${data.dependencies.map((d) => `<li>${escapeHtml(d)}</li>`).join("")}</ul></div>`;
      }
      if (data.warnings && data.warnings.length) {
        html += data.warnings.map((w) =>
          `<div class="notice notice-warning mt-4"><span>⚠️</span><span>${escapeHtml(w)}</span></div>`
        ).join("");
      }
      $("#configOutputBody").innerHTML = html;

    } catch (err) {
      showToast(err.message, "error");
    }
  }

  // ── Settings ───────────────────────────────────────────────
  function initSettings() {
    $("#settingsRefreshBtn").addEventListener("click", loadSettings);
  }

  async function loadSettings() {
    // Health check
    try {
      const healthResp = await fetch(`${API}/api/health`);
      if (healthResp.ok) {
        setStatus("settingsApiStatus", "connected", "Connected");
      } else {
        setStatus("settingsApiStatus", "disconnected", "Error");
      }
    } catch {
      setStatus("settingsApiStatus", "disconnected", "Unreachable");
    }

    // Config status
    try {
      const cfgResp = await fetch(`${API}/api/config/status`);
      if (cfgResp.ok) {
        const cfg = await cfgResp.json();
        $("#settingsLlmProvider").textContent = "OpenRouter (Free Models Only)";
        $("#settingsLlmModel").textContent = cfg.llm_model;
        if (cfg.llm_configured) {
          setStatus("settingsLlmStatus", "connected", "Configured (Free Models Active)");
        } else {
          setStatus("settingsLlmStatus", "disconnected", "Missing OPENROUTER_API_KEY in .env");
        }
        $("#settingsMaxUpload").textContent = `${cfg.max_upload_mb} MB`;
        $("#settingsMaxDuration").textContent = `${Math.round(cfg.max_duration_seconds / 60)} min`;
      }
    } catch {
      setStatus("settingsLlmStatus", "disconnected", "Cannot reach server");
    }

    // Free models list
    try {
      const modelsResp = await fetch(`${API}/api/models/free`);
      if (modelsResp.ok) {
        const mData = await modelsResp.json();
        const sel = $("#settingsModelSelect");
        if (mData.models && mData.models.length) {
          sel.innerHTML = mData.models.map((m) =>
            `<option value="${escapeAttr(m.id)}">${escapeHtml(m.name || m.id)}</option>`
          ).join("");
        }
      }
    } catch (e) {
      console.warn("Could not load free models", e);
    }

    // Companion Agent Status
    try {
      const compResp = await fetch(`${API}/api/companion/status`);
      if (compResp.ok) {
        const comp = await compResp.json();
        setStatus("settingsCompanionStatus", "connected", "Online (Local Companion Active)");
        $("#settingsCompanionVscode").textContent = comp.has_vscode_cli ? "✅ Installed ('code' CLI found)" : "❌ Not in PATH";
        $("#settingsCompanionClaude").textContent = comp.has_claude_cli ? "✅ Installed ('claude' CLI found)" : "⚠️ Not in PATH (using config file)";
      }
    } catch {
      setStatus("settingsCompanionStatus", "disconnected", "Companion Offline");
    }
  }

  function setStatus(elementId, dotClass, text) {
    const el = $(`#${elementId}`);
    if (el) el.innerHTML = `<span class="status-dot ${dotClass}"></span> ${escapeHtml(text)}`;
  }

  // ── Toast Notifications ────────────────────────────────────
  function showToast(message, type = "info") {
    const container = $("#toastContainer");
    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;

    const icons = { success: "✅", error: "❌", warning: "⚠️", info: "ℹ️" };
    toast.innerHTML = `<span>${icons[type] || "ℹ️"}</span><span>${escapeHtml(message)}</span>`;

    container.appendChild(toast);
    setTimeout(() => {
      toast.classList.add("toast-exit");
      setTimeout(() => toast.remove(), 200);
    }, 4000);
  }

  // ── Utilities ──────────────────────────────────────────────
  function escapeHtml(text) {
    if (!text) return "";
    const div = document.createElement("div");
    div.textContent = String(text);
    return div.innerHTML;
  }

  function escapeAttr(text) {
    if (!text) return "";
    return String(text)
      .replace(/&/g, "&amp;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function formatBytes(bytes) {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  }

  function formatDate(dateStr) {
    if (!dateStr) return "";
    try {
      const d = new Date(dateStr);
      return d.toLocaleDateString(undefined, {
        month: "short", day: "numeric", year: "numeric",
        hour: "2-digit", minute: "2-digit",
      });
    } catch {
      return dateStr;
    }
  }

})();
