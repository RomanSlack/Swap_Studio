import os
import jwt
import time
import uuid
import asyncio
import httpx
import tempfile
import subprocess
import base64
from typing import Optional
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Swap Studio API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API Configuration - supports fal.ai, Replicate, and direct Kling
FAL_API_KEY = os.getenv("FAL_API_KEY")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
KLING_API_BASE = os.getenv("KLING_API_BASE", "https://api.klingai.com")
KLING_ACCESS_KEY = os.getenv("KLING_ACCESS_KEY")
KLING_SECRET_KEY = os.getenv("KLING_SECRET_KEY")

# Determine which provider to use (fal.ai preferred for character swap)
def get_provider() -> str:
    if FAL_API_KEY:
        return "fal"  # Best for character replacement
    elif KLING_ACCESS_KEY and KLING_SECRET_KEY:
        return "kling"
    elif REPLICATE_API_TOKEN:
        return "replicate"
    return "none"

# In-memory job storage (use Redis/DB in production)
jobs: dict[str, dict] = {}


class SwapRequest(BaseModel):
    image_data: str  # base64 encoded image (data URI or raw base64)
    video_data: str  # base64 encoded video (data URI or raw base64)
    prompt: Optional[str] = ""
    quality: str = "std"  # "std" or "pro"
    swap_mode: str = "character_swap"  # "character_swap" (fal.ai) or "motion_control" (Replicate)


class LipSyncRequest(BaseModel):
    video_data: str  # base64 encoded video
    audio_data: str  # base64 encoded audio


class JobStatus(BaseModel):
    job_id: str
    status: str  # pending, processing, succeeded, failed
    progress: int  # 0-100
    output_url: Optional[str] = None
    error: Optional[str] = None


def generate_kling_jwt_token() -> str:
    """Generate JWT token for Kling API authentication"""
    if not KLING_ACCESS_KEY or not KLING_SECRET_KEY:
        raise ValueError("KLING_ACCESS_KEY and KLING_SECRET_KEY must be set")

    now = int(time.time())
    headers = {
        "alg": "HS256",
        "typ": "JWT"
    }
    payload = {
        "iss": KLING_ACCESS_KEY,
        "exp": now + 1800,  # 30 minutes
        "nbf": now - 5      # Valid from 5 seconds ago
    }
    return jwt.encode(payload, KLING_SECRET_KEY, algorithm="HS256", headers=headers)


def extract_base64_data(data_uri: str) -> str:
    """Extract raw base64 from data URI or return as-is"""
    if data_uri.startswith("data:"):
        parts = data_uri.split(",", 1)
        if len(parts) == 2:
            return parts[1]
    return data_uri


def compress_video(video_base64: str) -> str:
    """Compress video using ffmpeg to reduce file size"""
    # Extract raw base64
    if video_base64.startswith("data:"):
        parts = video_base64.split(",", 1)
        if len(parts) == 2:
            video_base64 = parts[1]

    # Decode to bytes
    video_bytes = base64.b64decode(video_base64)
    original_size = len(video_bytes) / (1024 * 1024)  # MB
    print(f"Original video size: {original_size:.2f} MB")

    # Skip compression if already small
    if original_size < 5:
        print("Video already small, skipping compression")
        return f"data:video/mp4;base64,{video_base64}"

    with tempfile.TemporaryDirectory() as tmpdir:
        input_path = os.path.join(tmpdir, "input.mp4")
        output_path = os.path.join(tmpdir, "output.mp4")

        # Write input file
        with open(input_path, "wb") as f:
            f.write(video_bytes)

        # Compress with ffmpeg
        # -crf 28 = decent quality, smaller file
        # -preset fast = reasonable speed
        # scale: ensure minimum 720px width (fal.ai requirement), maintain aspect ratio
        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-c:v", "libx264", "-crf", "26", "-preset", "fast",
            "-vf", "scale='max(720,iw)':-2",
            "-c:a", "aac", "-b:a", "128k",
            output_path
        ]

        try:
            subprocess.run(cmd, capture_output=True, check=True, timeout=120)
        except subprocess.CalledProcessError as e:
            print(f"FFmpeg error: {e.stderr.decode()}")
            # Return original if compression fails
            return f"data:video/mp4;base64,{video_base64}"
        except FileNotFoundError:
            print("FFmpeg not installed, skipping compression")
            return f"data:video/mp4;base64,{video_base64}"

        # Read compressed file
        with open(output_path, "rb") as f:
            compressed_bytes = f.read()

        compressed_size = len(compressed_bytes) / (1024 * 1024)
        print(f"Compressed video size: {compressed_size:.2f} MB ({(1 - compressed_size/original_size)*100:.0f}% reduction)")

        compressed_b64 = base64.b64encode(compressed_bytes).decode()
        return f"data:video/mp4;base64,{compressed_b64}"


async def upload_to_fal(client: httpx.AsyncClient, file_data: str, content_type: str, filename: str) -> str:
    """Upload a file to fal.ai and return the URL"""
    # Extract raw base64 if it's a data URI
    if file_data.startswith("data:"):
        parts = file_data.split(",", 1)
        if len(parts) == 2:
            file_data = parts[1]

    file_bytes = base64.b64decode(file_data)
    print(f"Uploading {filename}: {len(file_bytes) / 1024 / 1024:.2f} MB")

    # Get upload URL from fal
    headers = {
        "Authorization": f"Key {FAL_API_KEY}",
        "Content-Type": "application/json",
    }

    # Initiate upload
    init_response = await client.post(
        "https://rest.alpha.fal.ai/storage/upload/initiate",
        headers=headers,
        json={"content_type": content_type, "file_name": filename}
    )

    if init_response.status_code != 200:
        raise Exception(f"Failed to initiate fal upload: {init_response.text}")

    init_data = init_response.json()
    upload_url = init_data.get("upload_url")
    file_url = init_data.get("file_url")
    print(f"File URL: {file_url}")

    # Upload the file
    upload_resp = await client.put(
        upload_url,
        content=file_bytes,
        headers={"Content-Type": content_type}
    )
    print(f"Upload status: {upload_resp.status_code}")

    return file_url


async def process_swap_fal(
    job_id: str,
    image_data: str,
    video_data: str,
    prompt: str,
):
    """Process character swap using fal.ai Kling O1 Edit - replaces you with the character"""
    try:
        jobs[job_id]["status"] = "processing"
        jobs[job_id]["progress"] = 5

        # Compress video first
        print("Compressing video...")
        compressed_video = compress_video(video_data)
        jobs[job_id]["progress"] = 15

        async with httpx.AsyncClient(timeout=600.0) as client:
            # Upload files to fal.ai
            jobs[job_id]["progress"] = 20
            print("Uploading image to fal.ai...")
            image_url = await upload_to_fal(client, image_data, "image/png", "character.png")

            jobs[job_id]["progress"] = 30
            print("Uploading video to fal.ai...")
            video_url = await upload_to_fal(client, compressed_video, "video/mp4", "motion.mp4")

            jobs[job_id]["progress"] = 40
            print(f"Files uploaded. Starting Kling O1 Edit...")

            headers = {
                "Authorization": f"Key {FAL_API_KEY}",
                "Content-Type": "application/json",
            }

            # Build the prompt for character replacement
            edit_prompt = prompt if prompt else "Replace the person in the video with @Element1, maintaining the same movements, poses, and camera angles"
            if "@Element1" not in edit_prompt:
                edit_prompt = f"Replace the person in the video with @Element1. {edit_prompt}"

            # Submit to Kling O1 Edit
            request_body = {
                "video_url": video_url,
                "prompt": edit_prompt,
                "elements": [
                    {
                        "frontal_image_url": image_url,
                        "reference_image_urls": [image_url]  # Required: at least 1 reference
                    }
                ],
                "keep_audio": True,
            }

            model_id = "fal-ai/kling-video/o1/video-to-video/edit"

            # Submit job to queue
            submit_response = await client.post(
                f"https://queue.fal.run/{model_id}",
                headers=headers,
                json=request_body
            )

            print(f"Submit response: {submit_response.status_code} - {submit_response.text[:500]}")

            if submit_response.status_code not in [200, 201, 202]:
                jobs[job_id]["status"] = "failed"
                jobs[job_id]["error"] = f"fal.ai API error: {submit_response.status_code} - {submit_response.text}"
                return

            submit_data = submit_response.json()
            request_id = submit_data.get("request_id")

            if not request_id:
                jobs[job_id]["status"] = "failed"
                jobs[job_id]["error"] = f"No request_id in response: {submit_data}"
                return

            jobs[job_id]["task_id"] = request_id
            jobs[job_id]["progress"] = 50
            print(f"Job submitted with request_id: {request_id}")

            # Use the URLs provided in the response (they have the correct path)
            status_url = submit_data.get("status_url")
            result_url = submit_data.get("response_url")
            print(f"Status URL: {status_url}")
            print(f"Result URL: {result_url}")

            max_attempts = 180  # 15 minutes (5s intervals)
            attempt = 0

            while attempt < max_attempts:
                await asyncio.sleep(5)
                attempt += 1

                status_response = await client.get(status_url, headers=headers)
                if status_response.status_code not in [200, 202]:
                    print(f"Status check failed: {status_response.status_code} - {status_response.text}")
                    continue

                status_data = status_response.json()
                status = status_data.get("status")
                print(f"fal.ai status: {status} (attempt {attempt})")

                # Update progress based on status
                if status in ["IN_QUEUE", "QUEUED"]:
                    jobs[job_id]["progress"] = min(50 + attempt // 4, 60)
                elif status in ["IN_PROGRESS", "PROCESSING"]:
                    jobs[job_id]["progress"] = min(60 + attempt // 3, 90)

                if status == "COMPLETED":
                    # Get the result
                    result_response = await client.get(result_url, headers=headers)
                    print(f"Result response: {result_response.status_code}")
                    print(f"Result body: {result_response.text[:1000]}")

                    if result_response.status_code == 200:
                        result_data = result_response.json()
                        print(f"Result data keys: {result_data.keys()}")

                        # Get video URL from response
                        video_obj = result_data.get("video", {})
                        video_output = video_obj.get("url") if isinstance(video_obj, dict) else video_obj

                        if not video_output:
                            video_output = result_data.get("video_url")

                        print(f"Video output URL: {video_output}")

                        if video_output:
                            jobs[job_id]["status"] = "succeeded"
                            jobs[job_id]["progress"] = 100
                            jobs[job_id]["output_url"] = video_output
                            return

                    # Check if the status response itself has the result
                    video_in_status = status_data.get("video", {}).get("url") if isinstance(status_data.get("video"), dict) else status_data.get("video")
                    if video_in_status:
                        jobs[job_id]["status"] = "succeeded"
                        jobs[job_id]["progress"] = 100
                        jobs[job_id]["output_url"] = video_in_status
                        return

                    jobs[job_id]["status"] = "failed"
                    jobs[job_id]["error"] = f"No video URL in result. Status: {result_response.status_code}, Body: {result_response.text[:500]}"
                    return

                elif status in ["FAILED", "ERROR"]:
                    error = status_data.get("error", "Unknown error")
                    jobs[job_id]["status"] = "failed"
                    jobs[job_id]["error"] = f"fal.ai task failed: {error}"
                    return

            jobs[job_id]["status"] = "failed"
            jobs[job_id]["error"] = "Task timed out after 15 minutes"

    except Exception as e:
        jobs[job_id]["status"] = "failed"
        jobs[job_id]["error"] = str(e)


@app.get("/")
async def root():
    provider = get_provider()
    return {
        "message": "Swap Studio API",
        "version": "1.0.0",
        "provider": provider,
    }


@app.get("/health")
async def health():
    provider = get_provider()
    return {
        "status": "healthy",
        "provider": provider,
        "fal_configured": bool(FAL_API_KEY),
        "kling_configured": bool(KLING_ACCESS_KEY and KLING_SECRET_KEY),
        "replicate_configured": bool(REPLICATE_API_TOKEN),
    }


@app.post("/api/swap", response_model=JobStatus)
async def create_swap(request: SwapRequest, background_tasks: BackgroundTasks):
    """Start a character swap or motion control job"""

    # Check which providers are available for the requested mode
    if request.swap_mode == "character_swap":
        if not FAL_API_KEY:
            raise HTTPException(
                status_code=500,
                detail="FAL_API_KEY not configured. Character swap requires fal.ai."
            )
        provider = "fal"
    else:  # motion_control
        if KLING_ACCESS_KEY and KLING_SECRET_KEY:
            provider = "kling"
        elif REPLICATE_API_TOKEN:
            provider = "replicate"
        else:
            raise HTTPException(
                status_code=500,
                detail="No API configured for motion control. Set REPLICATE_API_TOKEN or KLING keys."
            )

    # Generate job ID
    job_id = str(uuid.uuid4())

    # Initialize job status
    jobs[job_id] = {
        "status": "pending",
        "progress": 0,
        "output_url": None,
        "error": None,
        "task_id": None,
        "provider": provider,
        "swap_mode": request.swap_mode,
    }

    # Start processing in background
    if provider == "fal":
        background_tasks.add_task(
            process_swap_fal,
            job_id,
            request.image_data,
            request.video_data,
            request.prompt,
        )
    elif provider == "kling":
        background_tasks.add_task(
            process_swap_kling,
            job_id,
            request.image_data,
            request.video_data,
            request.prompt,
            request.quality,
        )
    else:
        background_tasks.add_task(
            process_swap_replicate,
            job_id,
            request.image_data,
            request.video_data,
            request.prompt,
            request.quality,
        )

    return JobStatus(job_id=job_id, status="pending", progress=0)


async def upload_to_replicate(client: httpx.AsyncClient, file_data: str, filename: str) -> str:
    """Upload a file to Replicate and return the URL"""
    # Extract raw base64 if it's a data URI
    if file_data.startswith("data:"):
        parts = file_data.split(",", 1)
        if len(parts) == 2:
            file_data = parts[1]

    # Decode base64 to bytes
    file_bytes = base64.b64decode(file_data)

    # Create upload
    headers = {
        "Authorization": f"Bearer {REPLICATE_API_TOKEN}",
        "Content-Type": "application/json",
    }

    create_response = await client.post(
        "https://api.replicate.com/v1/files",
        headers=headers,
        json={"filename": filename, "content_type": "application/octet-stream"}
    )

    if create_response.status_code in [200, 201]:
        upload_data = create_response.json()
        upload_url = upload_data.get("upload_url")
        file_url = upload_data.get("urls", {}).get("get")

        if upload_url:
            # Upload the actual file
            await client.put(
                upload_url,
                content=file_bytes,
                headers={"Content-Type": "application/octet-stream"}
            )
            return file_url

    # Fallback: return as data URI if upload fails (for small files)
    return f"data:application/octet-stream;base64,{file_data}"


async def process_swap_replicate(
    job_id: str,
    image_data: str,
    video_data: str,
    prompt: str,
    mode: str,
):
    """Process the swap using Replicate's Kling API wrapper"""
    try:
        jobs[job_id]["status"] = "processing"
        jobs[job_id]["progress"] = 5

        # Compress video first to avoid Replicate's large file issues
        print("Compressing video...")
        compressed_video = compress_video(video_data)
        jobs[job_id]["progress"] = 15

        async with httpx.AsyncClient(timeout=300.0) as client:
            # Upload files to Replicate first (base64 fails for large files)
            jobs[job_id]["progress"] = 20
            print("Uploading image to Replicate...")
            image_url = await upload_to_replicate(client, image_data, "character.png")

            jobs[job_id]["progress"] = 30
            print("Uploading video to Replicate...")
            video_url = await upload_to_replicate(client, compressed_video, "motion.mp4")

            jobs[job_id]["progress"] = 35
            print(f"Files uploaded. Image: {image_url[:50]}... Video: {video_url[:50]}...")

            headers = {
                "Authorization": f"Bearer {REPLICATE_API_TOKEN}",
                "Content-Type": "application/json",
            }

            # Create prediction with URLs instead of base64
            create_url = "https://api.replicate.com/v1/predictions"
            request_body = {
                "version": "kwaivgi/kling-v2.6-motion-control",
                "input": {
                    "image": image_url,
                    "video": video_url,
                    "prompt": prompt or "person performing the motion naturally",
                    "mode": mode,
                    "character_orientation": "video",
                    "keep_original_sound": True,
                }
            }

            jobs[job_id]["progress"] = 40
            response = await client.post(create_url, headers=headers, json=request_body)

            # 200, 201, 202 are all valid - 202 means "accepted, processing"
            if response.status_code not in [200, 201, 202]:
                jobs[job_id]["status"] = "failed"
                jobs[job_id]["error"] = f"Replicate API error: {response.status_code} - {response.text}"
                return

            result = response.json()
            prediction_id = result.get("id")
            if not prediction_id:
                jobs[job_id]["status"] = "failed"
                jobs[job_id]["error"] = f"No prediction ID in response: {result}"
                return

            jobs[job_id]["task_id"] = prediction_id
            jobs[job_id]["progress"] = 40

            # Check if already completed (unlikely but possible)
            if result.get("status") == "succeeded":
                jobs[job_id]["status"] = "succeeded"
                jobs[job_id]["progress"] = 100
                jobs[job_id]["output_url"] = result.get("output")
                return

            # If failed immediately
            if result.get("status") == "failed":
                jobs[job_id]["status"] = "failed"
                jobs[job_id]["error"] = result.get("error") or "Prediction failed"
                return

            # Poll for completion (status is "starting" or "processing")
            poll_url = f"https://api.replicate.com/v1/predictions/{prediction_id}"
            max_attempts = 120  # 10 minutes
            attempt = 0

            while attempt < max_attempts:
                await asyncio.sleep(5)
                attempt += 1

                poll_response = await client.get(poll_url, headers=headers)
                if poll_response.status_code != 200:
                    continue

                poll_data = poll_response.json()
                status = poll_data.get("status")

                # Update progress
                current = jobs[job_id]["progress"]
                if current < 90:
                    jobs[job_id]["progress"] = min(current + 2, 90)

                if status == "succeeded":
                    jobs[job_id]["status"] = "succeeded"
                    jobs[job_id]["progress"] = 100
                    # Output can be a string URL or a list
                    output = poll_data.get("output")
                    if isinstance(output, list) and len(output) > 0:
                        jobs[job_id]["output_url"] = output[0]
                    else:
                        jobs[job_id]["output_url"] = output
                    return
                elif status == "failed":
                    jobs[job_id]["status"] = "failed"
                    jobs[job_id]["error"] = poll_data.get("error") or "Replicate task failed"
                    return
                elif status == "canceled":
                    jobs[job_id]["status"] = "failed"
                    jobs[job_id]["error"] = "Task was canceled"
                    return

            jobs[job_id]["status"] = "failed"
            jobs[job_id]["error"] = "Task timed out after 10 minutes"

    except Exception as e:
        jobs[job_id]["status"] = "failed"
        jobs[job_id]["error"] = str(e)


async def process_swap_kling(
    job_id: str,
    image_data: str,
    video_data: str,
    prompt: str,
    mode: str,
):
    """Process the swap using Kling's direct API"""
    try:
        jobs[job_id]["status"] = "processing"
        jobs[job_id]["progress"] = 10

        # Generate auth token
        token = generate_kling_jwt_token()
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}"
        }

        # Extract base64 data
        image_b64 = extract_base64_data(image_data)
        video_b64 = extract_base64_data(video_data)

        jobs[job_id]["progress"] = 20

        # Create the video generation task with motion control
        create_url = f"{KLING_API_BASE}/v1/videos/image2video"

        request_body = {
            "model_name": "kling-v2-6",
            "image": image_b64,
            "prompt": prompt or "person performing natural movement",
            "mode": mode,
            "duration": "5",
            "cfg_scale": 0.5,
            "motion_video": video_b64,
        }

        jobs[job_id]["progress"] = 30

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(create_url, headers=headers, json=request_body)

            if response.status_code != 200:
                # Try alternate endpoint
                if response.status_code in [400, 404]:
                    create_url = f"{KLING_API_BASE}/v1/videos/motion"
                    request_body = {
                        "model_name": "kling-v2-6",
                        "image": image_b64,
                        "reference_video": video_b64,
                        "prompt": prompt or "person performing natural movement",
                        "mode": mode,
                        "character_orientation": "video",
                        "keep_audio": True,
                    }
                    response = await client.post(create_url, headers=headers, json=request_body)

                if response.status_code != 200:
                    jobs[job_id]["status"] = "failed"
                    jobs[job_id]["error"] = f"Kling API error: {response.status_code} - {response.text}"
                    return

            result = response.json()
            task_id = result.get("data", {}).get("task_id") or result.get("task_id")

            if not task_id:
                jobs[job_id]["status"] = "failed"
                jobs[job_id]["error"] = f"No task_id in response: {result}"
                return

            jobs[job_id]["task_id"] = task_id
            jobs[job_id]["progress"] = 40

            # Poll for completion
            query_url = f"{KLING_API_BASE}/v1/videos/image2video/{task_id}"
            max_attempts = 120
            attempt = 0

            while attempt < max_attempts:
                await asyncio.sleep(5)
                attempt += 1

                if attempt % 60 == 0:
                    token = generate_kling_jwt_token()
                    headers["Authorization"] = f"Bearer {token}"

                try:
                    status_response = await client.get(query_url, headers=headers)
                    if status_response.status_code != 200:
                        query_url = f"{KLING_API_BASE}/v1/videos/motion/{task_id}"
                        status_response = await client.get(query_url, headers=headers)

                    if status_response.status_code != 200:
                        continue

                    status_data = status_response.json()
                    task_status = (
                        status_data.get("data", {}).get("task_status") or
                        status_data.get("task_status") or
                        status_data.get("status")
                    )

                    current = jobs[job_id]["progress"]
                    if current < 90:
                        jobs[job_id]["progress"] = min(current + 2, 90)

                    if task_status in ["succeed", "completed", "complete"]:
                        task_result = status_data.get("data", {}).get("task_result", {})
                        videos = task_result.get("videos", [])
                        if videos:
                            video_url = videos[0].get("url")
                        else:
                            video_url = (
                                status_data.get("data", {}).get("video_url") or
                                status_data.get("output", {}).get("video_url") or
                                status_data.get("video_url")
                            )

                        if video_url:
                            jobs[job_id]["status"] = "succeeded"
                            jobs[job_id]["progress"] = 100
                            jobs[job_id]["output_url"] = video_url
                            return
                        else:
                            jobs[job_id]["status"] = "failed"
                            jobs[job_id]["error"] = "No video URL in completed task"
                            return

                    elif task_status in ["failed", "error"]:
                        error_msg = (
                            status_data.get("data", {}).get("task_status_msg") or
                            status_data.get("error", {}).get("message") or
                            "Task failed"
                        )
                        jobs[job_id]["status"] = "failed"
                        jobs[job_id]["error"] = error_msg
                        return

                except Exception as e:
                    print(f"Poll error: {e}")
                    continue

            jobs[job_id]["status"] = "failed"
            jobs[job_id]["error"] = "Task timed out after 10 minutes"

    except Exception as e:
        jobs[job_id]["status"] = "failed"
        jobs[job_id]["error"] = str(e)


@app.get("/api/swap/{job_id}", response_model=JobStatus)
async def get_swap_status(job_id: str):
    """Get the status of a swap job"""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    job = jobs[job_id]
    return JobStatus(
        job_id=job_id,
        status=job["status"],
        progress=job["progress"],
        output_url=job["output_url"],
        error=job["error"],
    )


@app.delete("/api/swap/{job_id}")
async def cancel_swap(job_id: str):
    """Cancel a swap job"""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    jobs[job_id]["status"] = "canceled"
    return {"message": "Job canceled"}


# ============================================
# Lip Sync Endpoints
# ============================================

@app.post("/api/lipsync", response_model=JobStatus)
async def create_lipsync(request: LipSyncRequest, background_tasks: BackgroundTasks):
    """Start a lip sync job using Kling LipSync via fal.ai"""
    if not FAL_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="FAL_API_KEY not configured. Lip sync requires fal.ai."
        )

    job_id = str(uuid.uuid4())

    jobs[job_id] = {
        "status": "pending",
        "progress": 0,
        "output_url": None,
        "error": None,
        "task_id": None,
        "provider": "fal",
        "mode": "lipsync",
    }

    background_tasks.add_task(
        process_lipsync_fal,
        job_id,
        request.video_data,
        request.audio_data,
    )

    return JobStatus(job_id=job_id, status="pending", progress=0)


@app.get("/api/lipsync/{job_id}", response_model=JobStatus)
async def get_lipsync_status(job_id: str):
    """Get the status of a lip sync job"""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    job = jobs[job_id]
    return JobStatus(
        job_id=job_id,
        status=job["status"],
        progress=job["progress"],
        output_url=job["output_url"],
        error=job["error"],
    )


async def process_lipsync_fal(
    job_id: str,
    video_data: str,
    audio_data: str,
):
    """Process lip sync using fal.ai Kling LipSync"""
    try:
        jobs[job_id]["status"] = "processing"
        jobs[job_id]["progress"] = 5

        async with httpx.AsyncClient(timeout=600.0) as client:
            # Upload video to fal.ai
            jobs[job_id]["progress"] = 10
            print("Uploading video to fal.ai for lip sync...")
            video_url = await upload_to_fal(client, video_data, "video/mp4", "lipsync_video.mp4")

            # Upload audio to fal.ai
            jobs[job_id]["progress"] = 25
            print("Uploading audio to fal.ai...")

            # Detect audio type from data URI
            audio_content_type = "audio/mp3"
            if audio_data.startswith("data:"):
                if "wav" in audio_data.lower():
                    audio_content_type = "audio/wav"
                elif "m4a" in audio_data.lower():
                    audio_content_type = "audio/m4a"
                elif "ogg" in audio_data.lower():
                    audio_content_type = "audio/ogg"

            audio_ext = audio_content_type.split("/")[1]
            audio_url = await upload_to_fal(client, audio_data, audio_content_type, f"lipsync_audio.{audio_ext}")

            jobs[job_id]["progress"] = 40
            print(f"Files uploaded. Video: {video_url}, Audio: {audio_url}")

            headers = {
                "Authorization": f"Key {FAL_API_KEY}",
                "Content-Type": "application/json",
            }

            # Submit to Kling LipSync
            request_body = {
                "video_url": video_url,
                "audio_url": audio_url,
            }

            model_id = "fal-ai/kling-video/lipsync/audio-to-video"

            submit_response = await client.post(
                f"https://queue.fal.run/{model_id}",
                headers=headers,
                json=request_body
            )

            print(f"LipSync submit response: {submit_response.status_code} - {submit_response.text[:500]}")

            if submit_response.status_code not in [200, 201, 202]:
                jobs[job_id]["status"] = "failed"
                jobs[job_id]["error"] = f"fal.ai API error: {submit_response.status_code} - {submit_response.text}"
                return

            submit_data = submit_response.json()
            request_id = submit_data.get("request_id")

            if not request_id:
                jobs[job_id]["status"] = "failed"
                jobs[job_id]["error"] = f"No request_id in response: {submit_data}"
                return

            jobs[job_id]["task_id"] = request_id
            jobs[job_id]["progress"] = 50

            status_url = submit_data.get("status_url")
            result_url = submit_data.get("response_url")
            print(f"LipSync Status URL: {status_url}")

            # Poll for completion
            max_attempts = 120  # 10 minutes
            attempt = 0

            while attempt < max_attempts:
                await asyncio.sleep(5)
                attempt += 1

                status_response = await client.get(status_url, headers=headers)
                if status_response.status_code not in [200, 202]:
                    print(f"Status check failed: {status_response.status_code}")
                    continue

                status_data = status_response.json()
                status = status_data.get("status")
                print(f"LipSync status: {status} (attempt {attempt})")

                if status in ["IN_QUEUE", "QUEUED"]:
                    jobs[job_id]["progress"] = min(50 + attempt // 4, 60)
                elif status in ["IN_PROGRESS", "PROCESSING"]:
                    jobs[job_id]["progress"] = min(60 + attempt // 2, 90)

                if status == "COMPLETED":
                    result_response = await client.get(result_url, headers=headers)
                    print(f"LipSync result: {result_response.status_code}")

                    if result_response.status_code == 200:
                        result_data = result_response.json()

                        # Get video URL
                        video_obj = result_data.get("video", {})
                        video_output = video_obj.get("url") if isinstance(video_obj, dict) else video_obj

                        if video_output:
                            jobs[job_id]["status"] = "succeeded"
                            jobs[job_id]["progress"] = 100
                            jobs[job_id]["output_url"] = video_output
                            return

                    # Check status response for video
                    video_in_status = status_data.get("video", {}).get("url") if isinstance(status_data.get("video"), dict) else status_data.get("video")
                    if video_in_status:
                        jobs[job_id]["status"] = "succeeded"
                        jobs[job_id]["progress"] = 100
                        jobs[job_id]["output_url"] = video_in_status
                        return

                    jobs[job_id]["status"] = "failed"
                    jobs[job_id]["error"] = "No video URL in lip sync result"
                    return

                elif status in ["FAILED", "ERROR"]:
                    error = status_data.get("error", "Unknown error")
                    jobs[job_id]["status"] = "failed"
                    jobs[job_id]["error"] = f"Lip sync failed: {error}"
                    return

            jobs[job_id]["status"] = "failed"
            jobs[job_id]["error"] = "Lip sync timed out after 10 minutes"

    except Exception as e:
        jobs[job_id]["status"] = "failed"
        jobs[job_id]["error"] = str(e)
        print(f"LipSync error: {e}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
