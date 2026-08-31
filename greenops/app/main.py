from fastapi import FastAPI

app = FastAPI(title="GreenOps Multi-Cloud Energy Waste Platform")

@app.get("/health")
def health():
    return {"status": "healthy"}
