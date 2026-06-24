from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import List
import uuid
import io
import os
import boto3
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="ClarixPDF Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

s3 = boto3.client(
    "s3",
    endpoint_url=f"https://{os.getenv('R2_ACCOUNT_ID')}.r2.cloudflarestorage.com",
    aws_access_key_id=os.getenv("R2_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY"),
    region_name="auto",
)
BUCKET = os.getenv("R2_BUCKET_NAME")


def upload_to_r2(data: bytes, filename: str) -> str:
    job_id = str(uuid.uuid4())
    key = f"{job_id}/{filename}"
    s3.upload_fileobj(io.BytesIO(data), BUCKET, key)
    url = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": BUCKET, "Key": key},
        ExpiresIn=7200,
    )
    return url


@app.get("/")
def root():
    return {"status": "ClarixPDF backend running"}


@app.post("/convert/compress")
async def compress_pdf(file: UploadFile = File(...)):
    import pypdf
    contents = await file.read()
    reader = pypdf.PdfReader(io.BytesIO(contents))
    writer = pypdf.PdfWriter()
    for page in reader.pages:
        page.compress_content_streams()
        writer.add_page(page)
    output = io.BytesIO()
    writer.write(output)
    url = upload_to_r2(output.getvalue(), f"compressed_{file.filename}")
    return {"status": "done", "download_url": url}


@app.post("/convert/merge")
async def merge_pdfs(files: List[UploadFile] = File(...)):
    import pypdf
    writer = pypdf.PdfWriter()
    for f in files:
        contents = await f.read()
        reader = pypdf.PdfReader(io.BytesIO(contents))
        for page in reader.pages:
            writer.add_page(page)
    output = io.BytesIO()
    writer.write(output)
    url = upload_to_r2(output.getvalue(), "merged.pdf")
    return {"status": "done", "download_url": url}


@app.post("/convert/split")
async def split_pdf(file: UploadFile = File(...), pages: str = "1"):
    import pypdf
    contents = await file.read()
    reader = pypdf.PdfReader(io.BytesIO(contents))
    
    # Parse page numbers (e.g. "1,3,5" or "1-3")
    page_nums = []
    for part in pages.split(","):
        if "-" in part:
            start, end = part.split("-")
            page_nums.extend(range(int(start)-1, int(end)))
        else:
            page_nums.append(int(part)-1)

    writer = pypdf.PdfWriter()
    for i in page_nums:
        if i < len(reader.pages):
            writer.add_page(reader.pages[i])
    output = io.BytesIO()
    writer.write(output)
    url = upload_to_r2(output.getvalue(), "split.pdf")
    return {"status": "done", "download_url": url}


@app.post("/convert/jpg-to-pdf")
async def jpg_to_pdf(file: UploadFile = File(...)):
    from PIL import Image
    contents = await file.read()
    img = Image.open(io.BytesIO(contents)).convert("RGB")
    output = io.BytesIO()
    img.save(output, "PDF")
    url = upload_to_r2(output.getvalue(), "converted.pdf")
    return {"status": "done", "download_url": url}


@app.post("/convert/pdf-to-jpg")
async def pdf_to_jpg(file: UploadFile = File(...)):
    from pdf2image import convert_from_bytes
    contents = await file.read()
    images = convert_from_bytes(contents, first_page=1, last_page=1, dpi=150)
    output = io.BytesIO()
    images[0].save(output, "JPEG")
    url = upload_to_r2(output.getvalue(), "page1.jpg")
    return {"status": "done", "download_url": url}