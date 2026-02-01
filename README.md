# Swap Studio

AI-powered character swap and motion transfer using Kling AI's Motion Control API.

Record yourself (or upload a video), provide a character image, and watch the AI perfectly replace you with that character - preserving your exact movements, gestures, and timing.

## Features

- **Webcam Recording** - Record directly from your browser (10-30 seconds)
- **Video Upload** - Or upload an existing video file
- **Character Image Upload** - Any clear image of the character you want to become
- **Real-time Progress** - Live updates as your video is processed
- **Quality Options** - Standard or Pro mode for different quality/cost tradeoffs

## Tech Stack

- **Frontend**: Next.js 15, React 19, TypeScript
- **Backend**: Python FastAPI
- **AI**: Kling AI v2.6 Motion Control (Direct API)

## Quick Start

### 1. Get Kling API Credentials

1. Sign up at [klingai.com](https://klingai.com)
2. Go to [Developer Portal](https://klingai.com/global/dev)
3. Get your **Access Key** and **Secret Key**

### 2. Backend Setup

```bash
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env and add your KLING_ACCESS_KEY and KLING_SECRET_KEY

# Run the server
uvicorn main:app --reload --port 8000
```

### 3. Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Run dev server
npm run dev
```

### 4. Open the App

Navigate to [http://localhost:3000](http://localhost:3000)

## Usage

1. **Record or upload a video** of yourself (3-30 seconds)
   - Keep your face clearly visible
   - Simple movements work best to start
   - Good lighting helps

2. **Upload a character image**
   - Clear face/body visible
   - Similar pose to your starting position works best

3. **Optionally add a prompt** describing the motion

4. **Click Generate** and wait for the magic

## Pricing

Using Kling's Direct API (cheaper than third-party wrappers):
- **Standard Mode (v2.6)**: ~$0.21 per 5-second video
- **Pro Mode (v2.6)**: ~$0.33 per 5-second video

Volume discounts available. See [Kling Pricing](https://klingai.com/global/dev) for details.

## Project Structure

```
Swap_Studio/
├── frontend/           # Next.js 15 app
│   ├── app/
│   │   ├── page.tsx    # Main UI
│   │   ├── layout.tsx
│   │   └── globals.css
│   └── package.json
├── backend/            # FastAPI server
│   ├── main.py         # API endpoints
│   └── requirements.txt
└── photoai_mocap_tech_stack_2026.md  # Research notes
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/swap` | Start a new swap job |
| GET | `/api/swap/{job_id}` | Get job status |
| DELETE | `/api/swap/{job_id}` | Cancel a job |

## Resources

- [Kling Developer Portal](https://klingai.com/global/dev)
- [Kling Motion Control Guide](https://higgsfield.ai/blog/Kling-2.6-Motion-Control-Full-Guide)
- [Kling API Documentation](https://app.klingai.com/global/dev/document-api/quickStart/productIntroduction/overview)
- [Next.js Docs](https://nextjs.org/docs)
