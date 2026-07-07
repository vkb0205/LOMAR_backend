# LOMAR Vertex AI Nano Banana VTON Test UI

Small separate test project for calling Nano Banana through Google Cloud Vertex AI authenticated credentials and validating mannequin virtual try-on results in either a plain HTML UI or Streamlit UI.

## What this does

The user provides:

1. A base mannequin image.
2. A selected dress/clothing image.
3. A category such as `dress`, `tops`, `bottoms`, `onepieces`, or `clothes`.
4. An optional user query/edit prompt, for example: `make the dress more elegant but preserve the same fabric pattern`.

The backend sends the mannequin image, clothing image, and composed VTON prompt to Nano Banana via Vertex AI. The response is returned as a browser-displayable `data:image/...;base64,...` URL.

## Prerequisites

- Python 3.10+
- Google Cloud project with Vertex AI access
- Local authenticated application-default credentials, for example:

```bash
gcloud auth application-default login
gcloud config set project your-google-cloud-project-id
```

- Public/presigned image URLs, or local image files, for:
  - mannequin/base image
  - dress/clothing image

## Project files

- `test_api.py` - FastAPI backend with `/health`, `/test-try-on`, and `/test-try-on-upload`
- `index.html` - plain HTML/CSS/JavaScript test UI
- `streamlit_ui.py` - Streamlit alternative UI
- `.env` - local Vertex AI/backend configuration
- `requirements.txt` - Python dependencies
- `test_images/` - folder for local example images or notes

## Installation

Using the existing conda environment:

```bash
conda activate vton_env
cd backend
pip install -r requirements.txt
```

Optional virtualenv alternative:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configure Vertex AI Nano Banana

Edit `.env`:

```env
GOOGLE_GENAI_USE_VERTEXAI=true
GOOGLE_CLOUD_PROJECT=your-google-cloud-project-id
GOOGLE_CLOUD_LOCATION=global
NANO_BANANA_MODEL=gemini-2.5-flash-image-preview
API_HOST=0.0.0.0
API_PORT=3003
LOMAR_API_URL=http://localhost:3003
```

If you want to use API-key mode instead of Vertex AI credentials, set:

```env
GOOGLE_GENAI_USE_VERTEXAI=false
GOOGLE_API_KEY=your_google_api_key_here
```

## Run backend API

```bash
conda activate vton_env
cd backend
python test_api.py
```

Backend runs on the configured port. With the included `.env`, use:

```text
http://localhost:3003
```

Health check:

```bash
curl http://localhost:3003/health
```

Expected response includes:

```json
{
  "ok": true,
  "service": "LOMAR Vertex AI Nano Banana VTON API",
  "model": "gemini-2.5-flash-image-preview",
  "provider": "vertex-ai",
  "project": "your-google-cloud-project-id",
  "location": "global",
  "vertex_configured": true
}
```

## Run HTML UI

Open a second terminal:

```bash
cd backend
python -m http.server 8081
```

Open:

```text
http://localhost:8081/index.html
```

Use the form to enter:

1. Backend API URL: `http://localhost:3003`
2. Mannequin/base image URL or upload
3. Dress/clothing image URL or upload
4. Category: `tops`, `bottoms`, `onepieces`, `dress`, or `clothes`
5. Optional user query/edit prompt
6. Click **Generate mannequin try-on**

The UI shows loading, errors, generated result image, latency, model, and category.

## Run Streamlit UI

Alternative UI:

```bash
conda activate vton_env
cd backend
streamlit run streamlit_ui.py --server.port 8501
```

Open:

```text
http://localhost:8501
```

## API details

### `GET /health`

Returns backend status and Vertex AI model/project/location configuration state.

### `POST /test-try-on`

URL-based VTON endpoint.

Request body:

```json
{
  "body_url": "https://example.com/mannequin.png",
  "garment_url": "https://example.com/dress.png",
  "category": "dress",
  "prompt": "make the dress more premium and adjust the sleeves while keeping the original fabric pattern"
}
```

Response body:

```json
{
  "ok": true,
  "image_url": "data:image/png;base64,...",
  "latency_ms": 8123,
  "latency_seconds": 8.12,
  "model": "gemini-2.5-flash-image-preview",
  "provider": "vertex-ai",
  "project": "your-google-cloud-project-id",
  "location": "us-central1",
  "category": "dress",
  "prompt": "make the dress more premium and adjust the sleeves while keeping the original fabric pattern",
  "raw": null
}
```

### `POST /test-try-on-upload`

Local upload VTON endpoint. Use `multipart/form-data` with:

- `body_image` - local mannequin/base image file
- `garment_image` - local dress/clothing image file
- `category` - `tops`, `bottoms`, `onepieces`, `dress`, or `clothes`
- `prompt` - optional user query/edit prompt

Example using local images:

```bash
curl -s -X POST http://localhost:3003/test-try-on-upload \
  -F "body_image=@test_images/mannequin.png" \
  -F "garment_image=@test_images/dress.png" \
  -F "category=dress" \
  -F "prompt=make the dress more elegant but preserve the original fabric pattern"
```

Save the generated image from an upload test:

```bash
curl -s -X POST http://localhost:3003/test-try-on-upload \
  -F "body_image=@test_images/mannequin.png" \
  -F "garment_image=@test_images/dress.png" \
  -F "category=dress" \
  -F "prompt=make the dress more elegant but preserve the original fabric pattern" \
| python -c 'import sys,json,base64,re; d=json.load(sys.stdin); img=d["image_url"]; b64=re.sub(r"^data:image/[^;]+;base64,","",img); open("test_images/generated_tryon.png","wb").write(base64.b64decode(b64)); print("saved test_images/generated_tryon.png")'
```

## Suggested prompt examples

- `Fit this dress naturally on the mannequin and preserve the original color and texture.`
- `Make the dress look more formal with cleaner drape, but do not change the pattern.`
- `Adjust the sleeves to look slightly longer while keeping the same fabric.`
- `Style this as a premium product photo with realistic shadows.`

## Troubleshooting

### `GOOGLE_CLOUD_PROJECT is not configured in .env`

Set `GOOGLE_CLOUD_PROJECT` in `.env` to the Google Cloud project that has Vertex AI access.

### Vertex AI authentication errors

Run:

```bash
gcloud auth application-default login
gcloud config set project your-google-cloud-project-id
```

Then restart the backend.

### Model not found or permission denied

Check that `NANO_BANANA_MODEL` is available in your selected `GOOGLE_CLOUD_LOCATION` and that your credentials/project have Vertex AI permissions. For Gemini image preview models, try `GOOGLE_CLOUD_LOCATION=global` first. If your project has regional model access, switch to that supported region.

### Browser shows CORS or connection error

Confirm the backend is running on port 3003:

```bash
curl http://localhost:3003/health
```

Then confirm the UI is using backend URL `http://localhost:3003`.

### Invalid URL errors

The backend validates both URLs and downloads them before calling Vertex AI. Make sure presigned URLs are not expired and return an `image/*` content type.

## Verification checklist

- Backend `/health` returns `ok: true`
- HTML UI loads at `http://localhost:8081/index.html`
- Streamlit UI loads at `http://localhost:8501`
- Valid mannequin + clothing URLs return a generated result image
- Local mannequin + clothing uploads return a generated result image
- Optional user query changes/refines the generated clothing result
- Invalid URLs show an error
- Missing URLs or missing files show validation errors
- Latency, model, and category information are displayed
