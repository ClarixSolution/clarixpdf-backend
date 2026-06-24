from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import uuid
import io
import os
import boto3
from dotenv import load_dotenv
from PyPDF2 import PdfReader, PdfWriter

load_dotenv()

app = FastAPI(title="ClarixPDF Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# R2 client
s3 = boto3.client(
    "s3",
    endpoint_url=f"https://{os.getenv('R2_ACCOUNT_ID')}.r2.cloudflarestorage.com",
    aws_access_key_id=os.getenv("R2_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY"),
    region_name="auto",
)
BUCKET = os.getenv("R2_BUCKET_NAME")


@app.get("/")
def root():
    return {"status": "ClarixPDF backend running"}


@app.post("/convert/compress")
async def compress_pdf(file: UploadFile = File(...)):
    job_id = str(uuid.uuid4())
    contents = await file.read()

    # Compress PDF
    reader = PdfReader(io.BytesIO(contents))
    writer = PdfWriter()
    for page in reader.pages:
        page.compress_content_streams()
        writer.add_page(page)

    output = io.BytesIO()
    writer.write(output)
    output.seek(0)

    # Upload to R2
    output_key = f"{job_id}/compressed_{file.filename}"
    s3.upload_fileobj(output, BUCKET, output_key)

    # Generate presigned download URL (valid 2 hours)
    url = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": BUCKET, "Key": output_key},
        ExpiresIn=7200,
    )

    return {"job_id": job_id, "status": "done", "download_url": url}


@app.post("/convert/jpg-to-pdf")
async def jpg_to_pdf(file: UploadFile = File(...)):
    from PIL import Image
    job_id = str(uuid.uuid4())
    contents = await file.read()

    img = Image.open(io.BytesIO(contents)).convert("RGB")
    output = io.BytesIO()
    img.save(output, "PDF")
    output.seek(0)

    output_key = f"{job_id}/converted.pdf"
    s3.upload_fileobj(output, BUCKET, output_key)

    url = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": BUCKET, "Key": output_key},
        ExpiresIn=7200,
    )

    return {"job_id": job_id, "status": "done", "download_url": url}