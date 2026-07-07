import os
import time
from typing import Any, Dict

import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

DEFAULT_API_URL = os.getenv("LOMAR_API_URL", "http://localhost:3000")

st.set_page_config(page_title="LOMAR Nano Banana VTON Test", page_icon="👗", layout="wide")

st.title("LOMAR Vertex AI Nano Banana VTON Test UI")
st.caption("Streamlit UI for testing mannequin virtual try-on with Vertex AI Nano Banana through the local LOMAR backend API.")

with st.sidebar:
    st.header("Backend")
    api_url = st.text_input("LOMAR backend API URL", value=DEFAULT_API_URL).rstrip("/")
    if st.button("Check /health"):
        try:
            response = requests.get(f"{api_url}/health", timeout=10)
            response.raise_for_status()
            st.success("Backend is healthy")
            st.json(response.json())
        except Exception as exc:
            st.error(f"Health check failed: {exc}")

col_form, col_result = st.columns([0.9, 1.1], gap="large")

with col_form:
    st.subheader("Inputs")
    input_mode = st.radio("Input mode", options=["Upload local files", "Use image URLs"], horizontal=True)
    category = st.selectbox("Category", options=["tops", "bottoms", "onepieces", "dress", "clothes"], index=2)
    prompt = st.text_area(
        "Optional user query / edit prompt",
        placeholder="Example: make the dress more elegant, adjust sleeves, keep the same fabric pattern...",
    )

    body_url = ""
    garment_url = ""
    body_upload = None
    garment_upload = None

    if input_mode == "Upload local files":
        body_upload = st.file_uploader("Mannequin/base image file", type=["png", "jpg", "jpeg", "webp"])
        garment_upload = st.file_uploader("Dress/clothing image file", type=["png", "jpg", "jpeg", "webp"])
    else:
        body_url = st.text_input("Mannequin/base image URL", placeholder="https://.../mannequin.png")
        garment_url = st.text_input("Dress/clothing image URL", placeholder="https://.../dress.png")

    test_button = st.button("Generate mannequin try-on", type="primary", use_container_width=True)

with col_result:
    st.subheader("Result")
    result_slot = st.empty()
    metric_cols = st.columns(3)


def parse_error(payload: Dict[str, Any]) -> str:
    detail = payload.get("detail") if isinstance(payload, dict) else None
    if isinstance(detail, str):
        return detail
    if detail is not None:
        return str(detail)
    return str(payload)


if test_button:
    started = time.perf_counter()
    with st.spinner("Running Vertex AI Nano Banana virtual try-on..."):
        try:
            if input_mode == "Upload local files":
                if body_upload is None or garment_upload is None:
                    st.error("Upload both mannequin/base image and dress/clothing image files.")
                    st.stop()

                files = {
                    "body_image": (body_upload.name, body_upload.getvalue(), body_upload.type or "image/png"),
                    "garment_image": (garment_upload.name, garment_upload.getvalue(), garment_upload.type or "image/png"),
                }
                response = requests.post(
                    f"{api_url}/test-try-on-upload",
                    data={"category": category, "prompt": prompt.strip()},
                    files=files,
                    timeout=150,
                )
            else:
                if not body_url.strip() or not garment_url.strip():
                    st.error("Mannequin/base image URL and dress/clothing image URL are required.")
                    st.stop()

                payload = {
                    "body_url": body_url.strip(),
                    "garment_url": garment_url.strip(),
                    "category": category,
                    "prompt": prompt.strip(),
                }
                response = requests.post(f"{api_url}/test-try-on", json=payload, timeout=150)

            try:
                data = response.json()
            except ValueError:
                data = {"detail": response.text}

            if response.status_code >= 400:
                st.error(parse_error(data))
            elif not data.get("image_url"):
                st.error("Backend response did not include image_url.")
                st.json(data)
            else:
                result_slot.image(data["image_url"], caption="Generated virtual try-on result", use_container_width=True)
                latency_seconds = data.get("latency_seconds", round(time.perf_counter() - started, 2))
                metric_cols[0].metric("Latency", f"{latency_seconds}s")
                metric_cols[1].metric("Model", data.get("model", "Unknown"))
                metric_cols[2].metric("Category", data.get("category", category))
                st.success("Image generation completed successfully.")
        except requests.RequestException as exc:
            st.error(f"Could not call backend API: {exc}")
else:
    result_slot.info("Upload local files or enter mannequin + clothing URLs, choose a category, optionally add a user query, then generate the try-on.")
