"use client";

import { useState, useRef, useCallback, useEffect, DragEvent } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type SwapMode = "character_swap" | "motion_control" | "lip_sync";

interface JobStatus {
  job_id: string;
  status: "pending" | "processing" | "succeeded" | "failed" | "canceled";
  progress: number;
  output_url: string | null;
  error: string | null;
}

// SVG Icons
const VideoIcon = () => (
  <svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <rect x="2" y="4" width="20" height="16" rx="2" />
    <path d="M10 9l5 3-5 3V9z" fill="currentColor" stroke="none" />
  </svg>
);

const ImageIcon = () => (
  <svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <rect x="3" y="3" width="18" height="18" rx="2" />
    <circle cx="8.5" cy="8.5" r="1.5" fill="currentColor" stroke="none" />
    <path d="M21 15l-5-5L5 21" />
  </svg>
);

const AudioIcon = () => (
  <svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <path d="M9 18V5l12-2v13" />
    <circle cx="6" cy="18" r="3" />
    <circle cx="18" cy="16" r="3" />
  </svg>
);

const SparklesIcon = () => (
  <svg className="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 3l1.5 4.5L18 9l-4.5 1.5L12 15l-1.5-4.5L6 9l4.5-1.5L12 3z" />
    <path d="M5 19l1 3 1-3 3-1-3-1-1-3-1 3-3 1 3 1z" />
  </svg>
);

const DownloadIcon = () => (
  <svg className="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
    <polyline points="7,10 12,15 17,10" />
    <line x1="12" y1="15" x2="12" y2="3" />
  </svg>
);

const CameraIcon = () => (
  <svg className="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="13" r="4" />
    <path d="M5 7h2l2-3h6l2 3h2a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V9a2 2 0 012-2z" />
  </svg>
);

export default function Home() {
  // Video state
  const [videoFile, setVideoFile] = useState<File | null>(null);
  const [videoPreview, setVideoPreview] = useState<string | null>(null);
  const [isRecording, setIsRecording] = useState(false);
  const [recordingTime, setRecordingTime] = useState(0);
  const [showWebcam, setShowWebcam] = useState(false);

  // Image state
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [imagePreview, setImagePreview] = useState<string | null>(null);

  // Audio state (for lip sync)
  const [audioFile, setAudioFile] = useState<File | null>(null);
  const [audioPreview, setAudioPreview] = useState<string | null>(null);

  // Drag and drop state
  const [videoDragActive, setVideoDragActive] = useState(false);
  const [imageDragActive, setImageDragActive] = useState(false);
  const [audioDragActive, setAudioDragActive] = useState(false);

  // Options
  const [prompt, setPrompt] = useState("");
  const [quality, setQuality] = useState<"std" | "pro">("std");
  const [swapMode, setSwapMode] = useState<SwapMode>("character_swap");

  // Job state
  const [currentJob, setCurrentJob] = useState<JobStatus | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Refs
  const videoRef = useRef<HTMLVideoElement>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const timerRef = useRef<NodeJS.Timeout | null>(null);
  const pollRef = useRef<NodeJS.Timeout | null>(null);
  const videoInputRef = useRef<HTMLInputElement>(null);
  const imageInputRef = useRef<HTMLInputElement>(null);
  const audioInputRef = useRef<HTMLInputElement>(null);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  // Start webcam
  const startWebcam = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { width: 1280, height: 720 },
        audio: true,
      });
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
      }
      setShowWebcam(true);
    } catch (err) {
      console.error("Error accessing webcam:", err);
      alert("Could not access webcam. Please check permissions.");
    }
  };

  // Stop webcam
  const stopWebcam = () => {
    if (videoRef.current?.srcObject) {
      const tracks = (videoRef.current.srcObject as MediaStream).getTracks();
      tracks.forEach((track) => track.stop());
      videoRef.current.srcObject = null;
    }
    setShowWebcam(false);
    setIsRecording(false);
    setRecordingTime(0);
    if (timerRef.current) clearInterval(timerRef.current);
  };

  // Start recording
  const startRecording = () => {
    if (!videoRef.current?.srcObject) return;

    chunksRef.current = [];
    const stream = videoRef.current.srcObject as MediaStream;
    const mediaRecorder = new MediaRecorder(stream, {
      mimeType: "video/webm;codecs=vp9",
    });

    mediaRecorder.ondataavailable = (e) => {
      if (e.data.size > 0) {
        chunksRef.current.push(e.data);
      }
    };

    mediaRecorder.onstop = () => {
      const blob = new Blob(chunksRef.current, { type: "video/webm" });
      const file = new File([blob], "recording.webm", { type: "video/webm" });
      setVideoFile(file);
      setVideoPreview(URL.createObjectURL(blob));
      stopWebcam();
    };

    mediaRecorder.start(100);
    mediaRecorderRef.current = mediaRecorder;
    setIsRecording(true);
    setRecordingTime(0);

    timerRef.current = setInterval(() => {
      setRecordingTime((t) => t + 1);
    }, 1000);
  };

  // Stop recording
  const stopRecording = () => {
    if (mediaRecorderRef.current && isRecording) {
      mediaRecorderRef.current.stop();
      if (timerRef.current) clearInterval(timerRef.current);
      setIsRecording(false);
    }
  };

  // Handle file uploads
  const handleVideoUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      setVideoFile(file);
      setVideoPreview(URL.createObjectURL(file));
    }
  };

  const handleImageUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      setImageFile(file);
      setImagePreview(URL.createObjectURL(file));
    }
  };

  const handleAudioUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      setAudioFile(file);
      setAudioPreview(URL.createObjectURL(file));
    }
  };

  // Drag and drop handlers
  const handleVideoDrag = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setVideoDragActive(true);
    } else if (e.type === "dragleave") {
      setVideoDragActive(false);
    }
  };

  const handleVideoDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setVideoDragActive(false);
    const file = e.dataTransfer.files?.[0];
    if (file && file.type.startsWith("video/")) {
      setVideoFile(file);
      setVideoPreview(URL.createObjectURL(file));
    }
  };

  const handleImageDrag = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setImageDragActive(true);
    } else if (e.type === "dragleave") {
      setImageDragActive(false);
    }
  };

  const handleImageDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setImageDragActive(false);
    const file = e.dataTransfer.files?.[0];
    if (file && file.type.startsWith("image/")) {
      setImageFile(file);
      setImagePreview(URL.createObjectURL(file));
    }
  };

  const handleAudioDrag = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setAudioDragActive(true);
    } else if (e.type === "dragleave") {
      setAudioDragActive(false);
    }
  };

  const handleAudioDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setAudioDragActive(false);
    const file = e.dataTransfer.files?.[0];
    if (file && file.type.startsWith("audio/")) {
      setAudioFile(file);
      setAudioPreview(URL.createObjectURL(file));
    }
  };

  // Remove files
  const removeVideo = () => {
    setVideoFile(null);
    setVideoPreview(null);
    if (videoInputRef.current) videoInputRef.current.value = "";
  };

  const removeImage = () => {
    setImageFile(null);
    setImagePreview(null);
    if (imageInputRef.current) imageInputRef.current.value = "";
  };

  const removeAudio = () => {
    setAudioFile(null);
    setAudioPreview(null);
    if (audioInputRef.current) audioInputRef.current.value = "";
  };

  // Convert file to base64
  const fileToBase64 = (file: File): Promise<string> => {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.readAsDataURL(file);
      reader.onload = () => resolve(reader.result as string);
      reader.onerror = (error) => reject(error);
    });
  };

  // Poll job status
  const pollJobStatus = useCallback(async (jobId: string, endpoint: string) => {
    try {
      const res = await fetch(`${API_URL}${endpoint}/${jobId}`);
      if (!res.ok) throw new Error("Failed to fetch job status");

      const status: JobStatus = await res.json();
      setCurrentJob(status);

      if (status.status === "succeeded" || status.status === "failed") {
        if (pollRef.current) {
          clearInterval(pollRef.current);
          pollRef.current = null;
        }
        setIsSubmitting(false);
      }
    } catch (err) {
      console.error("Error polling job status:", err);
    }
  }, []);

  // Submit job
  const handleSubmit = async () => {
    // Validate inputs based on mode
    if (swapMode === "lip_sync") {
      if (!videoFile || !audioFile) {
        alert("Please provide both a video and an audio file");
        return;
      }
    } else {
      if (!videoFile || !imageFile) {
        alert("Please provide both a video and a character image");
        return;
      }
    }

    setIsSubmitting(true);
    setCurrentJob(null);

    try {
      if (swapMode === "lip_sync") {
        // Lip sync request
        const [videoData, audioData] = await Promise.all([
          fileToBase64(videoFile!),
          fileToBase64(audioFile!),
        ]);

        const res = await fetch(`${API_URL}/api/lipsync`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            video_data: videoData,
            audio_data: audioData,
          }),
        });

        if (!res.ok) {
          const err = await res.json();
          throw new Error(err.detail || "Failed to start lip sync");
        }

        const job: JobStatus = await res.json();
        setCurrentJob(job);

        pollRef.current = setInterval(() => {
          pollJobStatus(job.job_id, "/api/lipsync");
        }, 2000);

      } else {
        // Character swap or motion control
        const [videoData, imageData] = await Promise.all([
          fileToBase64(videoFile!),
          fileToBase64(imageFile!),
        ]);

        const res = await fetch(`${API_URL}/api/swap`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            video_data: videoData,
            image_data: imageData,
            prompt,
            quality,
            swap_mode: swapMode,
          }),
        });

        if (!res.ok) {
          const err = await res.json();
          throw new Error(err.detail || "Failed to start swap");
        }

        const job: JobStatus = await res.json();
        setCurrentJob(job);

        pollRef.current = setInterval(() => {
          pollJobStatus(job.job_id, "/api/swap");
        }, 2000);
      }
    } catch (err) {
      console.error("Error submitting job:", err);
      alert(err instanceof Error ? err.message : "Failed to start job");
      setIsSubmitting(false);
    }
  };

  // Format time
  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}:${secs.toString().padStart(2, "0")}`;
  };

  // Check if can submit
  const canSubmit = swapMode === "lip_sync"
    ? videoFile && audioFile && !isSubmitting
    : videoFile && imageFile && !isSubmitting;

  // Mode labels
  const modeLabels = {
    character_swap: {
      video: "Your Video",
      secondary: "Character",
      button: "Generate Swap",
      description: "Replaces you with the character in your scene"
    },
    motion_control: {
      video: "Motion Reference",
      secondary: "Character",
      button: "Generate Animation",
      description: "Animates the character with your motion"
    },
    lip_sync: {
      video: "Video",
      secondary: "Audio",
      button: "Generate Lip Sync",
      description: "Syncs lips in the video to match the audio"
    }
  };

  const labels = modeLabels[swapMode];

  return (
    <main className="container">
      <header className="header">
        <h1>Swap Studio</h1>
        <p>AI-powered character swap, motion transfer, and lip sync</p>
      </header>

      {/* Mode Selector */}
      <div className="mode-section">
        <div className="mode-toggle">
          <button
            className={`mode-btn ${swapMode === "character_swap" ? "active" : ""}`}
            onClick={() => setSwapMode("character_swap")}
          >
            Character Swap
          </button>
          <button
            className={`mode-btn ${swapMode === "motion_control" ? "active" : ""}`}
            onClick={() => setSwapMode("motion_control")}
          >
            Motion Control
          </button>
          <button
            className={`mode-btn ${swapMode === "lip_sync" ? "active" : ""}`}
            onClick={() => setSwapMode("lip_sync")}
          >
            Lip Sync
          </button>
        </div>
      </div>

      <div className="grid">
        {/* Video Section */}
        <div className="card">
          <h2>{labels.video}</h2>

          {!videoPreview && !showWebcam && (
            <>
              <div
                className={`upload-zone ${videoDragActive ? "active" : ""}`}
                onClick={() => videoInputRef.current?.click()}
                onDragEnter={handleVideoDrag}
                onDragOver={handleVideoDrag}
                onDragLeave={handleVideoDrag}
                onDrop={handleVideoDrop}
              >
                <VideoIcon />
                <strong>{videoDragActive ? "Drop video here" : "Upload video"}</strong>
                <p>{swapMode === "lip_sync" ? "MP4, WebM, MOV (2-10s)" : "MP4, WebM, MOV up to 30s"}</p>
              </div>
              <input
                ref={videoInputRef}
                type="file"
                accept="video/*"
                onChange={handleVideoUpload}
                className="hidden"
              />
              {swapMode !== "lip_sync" && (
                <div className="record-controls">
                  <button className="btn btn-secondary" onClick={startWebcam}>
                    <CameraIcon />
                    Record
                  </button>
                </div>
              )}
            </>
          )}

          {showWebcam && !videoPreview && (
            <div className="webcam-container">
              <video
                ref={videoRef}
                autoPlay
                muted
                playsInline
                className="webcam-video"
              />
              {isRecording && (
                <div className="recording-indicator">
                  <span className="recording-dot"></span>
                  Recording
                  <span className="timer">{formatTime(recordingTime)}</span>
                </div>
              )}
              <div className="record-controls">
                {!isRecording ? (
                  <>
                    <button className="btn btn-danger" onClick={startRecording}>
                      Start
                    </button>
                    <button className="btn btn-secondary" onClick={stopWebcam}>
                      Cancel
                    </button>
                  </>
                ) : (
                  <button className="btn btn-danger" onClick={stopRecording}>
                    Stop ({formatTime(recordingTime)})
                  </button>
                )}
              </div>
            </div>
          )}

          {videoPreview && (
            <div className="preview-container">
              <video src={videoPreview} controls style={{ transform: "none" }} />
              <button className="remove-btn" onClick={removeVideo}>
                &times;
              </button>
              {videoFile && (
                <p className="file-info">
                  {videoFile.name} ({(videoFile.size / 1024 / 1024).toFixed(1)} MB)
                </p>
              )}
            </div>
          )}
        </div>

        {/* Secondary Section - Image or Audio */}
        <div className="card">
          <h2>{labels.secondary}</h2>

          {swapMode === "lip_sync" ? (
            // Audio upload for lip sync
            !audioPreview ? (
              <>
                <div
                  className={`upload-zone ${audioDragActive ? "active" : ""}`}
                  onClick={() => audioInputRef.current?.click()}
                  onDragEnter={handleAudioDrag}
                  onDragOver={handleAudioDrag}
                  onDragLeave={handleAudioDrag}
                  onDrop={handleAudioDrop}
                >
                  <AudioIcon />
                  <strong>{audioDragActive ? "Drop audio here" : "Upload audio"}</strong>
                  <p>MP3, WAV, M4A (2-60s)</p>
                </div>
                <input
                  ref={audioInputRef}
                  type="file"
                  accept="audio/*"
                  onChange={handleAudioUpload}
                  className="hidden"
                />
              </>
            ) : (
              <div className="preview-container">
                <div className="audio-preview">
                  <AudioIcon />
                  <audio src={audioPreview} controls />
                </div>
                <button className="remove-btn" onClick={removeAudio}>
                  &times;
                </button>
                {audioFile && (
                  <p className="file-info">
                    {audioFile.name} ({(audioFile.size / 1024 / 1024).toFixed(1)} MB)
                  </p>
                )}
              </div>
            )
          ) : (
            // Image upload for character swap/motion control
            !imagePreview ? (
              <>
                <div
                  className={`upload-zone ${imageDragActive ? "active" : ""}`}
                  onClick={() => imageInputRef.current?.click()}
                  onDragEnter={handleImageDrag}
                  onDragOver={handleImageDrag}
                  onDragLeave={handleImageDrag}
                  onDrop={handleImageDrop}
                >
                  <ImageIcon />
                  <strong>{imageDragActive ? "Drop image here" : "Upload character"}</strong>
                  <p>PNG, JPG with clear face</p>
                </div>
                <input
                  ref={imageInputRef}
                  type="file"
                  accept="image/*"
                  onChange={handleImageUpload}
                  className="hidden"
                />
              </>
            ) : (
              <div className="preview-container">
                <img src={imagePreview} alt="Character" />
                <button className="remove-btn" onClick={removeImage}>
                  &times;
                </button>
                {imageFile && (
                  <p className="file-info">
                    {imageFile.name} ({(imageFile.size / 1024 / 1024).toFixed(1)} MB)
                  </p>
                )}
              </div>
            )
          )}
        </div>
      </div>

      {/* Options - only show for non-lip-sync modes */}
      {swapMode !== "lip_sync" && (
        <div className="card options-card">
          <h2>Options</h2>
          <div className="options-grid">
            <div className="option-group">
              <label>Prompt (optional)</label>
              <input
                type="text"
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                placeholder={swapMode === "character_swap"
                  ? "e.g., Replace person with character, keep background"
                  : "e.g., Person dancing smoothly"}
              />
            </div>
            <div className="option-group">
              <label>Quality</label>
              <select value={quality} onChange={(e) => setQuality(e.target.value as "std" | "pro")}>
                <option value="std">Standard</option>
                <option value="pro">Pro</option>
              </select>
            </div>
          </div>
          <p className="mode-hint">{labels.description}</p>
        </div>
      )}

      {/* Mode description for lip sync */}
      {swapMode === "lip_sync" && (
        <p className="mode-hint" style={{ textAlign: "center", marginBottom: "1.5rem" }}>
          {labels.description} - Kling LipSync via fal.ai (~$0.17/min)
        </p>
      )}

      {/* Submit Button */}
      <button
        className="btn btn-primary btn-full"
        onClick={handleSubmit}
        disabled={!canSubmit}
      >
        {isSubmitting ? (
          <>
            <span className="spinner"></span>
            Processing...
          </>
        ) : (
          <>
            <SparklesIcon />
            {labels.button}
          </>
        )}
      </button>

      {/* Progress Section */}
      {currentJob && (
        <div className="progress-section">
          <div className="progress-card">
            <div className="progress-header">
              <h3>Generation Progress</h3>
              <span className={`status-badge status-${currentJob.status}`}>
                {currentJob.status}
              </span>
            </div>
            <div className="progress-bar-container">
              <div
                className="progress-bar"
                style={{ width: `${currentJob.progress}%` }}
              />
            </div>
            <p className="progress-status">
              {currentJob.status === "pending" && "Preparing your files..."}
              {currentJob.status === "processing" &&
                `Generating... ${currentJob.progress}%`}
              {currentJob.status === "succeeded" && "Complete! Your video is ready."}
              {currentJob.status === "failed" && "Generation failed."}
            </p>

            {currentJob.error && (
              <div className="error-message">{currentJob.error}</div>
            )}
          </div>
        </div>
      )}

      {/* Result Section */}
      {currentJob?.status === "succeeded" && currentJob.output_url && (
        <div className="result-section">
          <div className="card">
            <h2>Result</h2>
            <video
              src={currentJob.output_url}
              controls
              className="result-video"
              autoPlay
            />
            <div className="download-area">
              <a
                href={currentJob.output_url}
                download="result.mp4"
                className="btn btn-primary"
              >
                <DownloadIcon />
                Download
              </a>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
