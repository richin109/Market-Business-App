from fastapi import FastAPI

app = FastAPI(title="Market Business System")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
