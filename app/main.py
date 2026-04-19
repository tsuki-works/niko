from fastapi import FastAPI

app = FastAPI(title="niko")


@app.get("/")
def root():
    return {"service": "niko", "status": "ok"}


@app.get("/health")
def health():
    return {"status": "ok"}
