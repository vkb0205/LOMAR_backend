from google.cloud import aiplatform_v1

PROJECT_ID = "lomar-500117"
LOCATION = "us-central1"

client = aiplatform_v1.ModelServiceClient(
    client_options={"api_endpoint": f"{LOCATION}-aiplatform.googleapis.com"}
)

# List models uploaded to this Vertex AI project/location.
models = list(
    client.list_models(parent=f"projects/{PROJECT_ID}/locations/{LOCATION}")
)

if not models:
    print(f"No uploaded Vertex AI models found in {PROJECT_ID}/{LOCATION}.")
else:
    for model in models:
        print(model.name)
