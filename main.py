from fastapi import FastAPI, UploadFile, File
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
        writer.add_page(page)
    writer.compress_identical_objects(remove_identicals=True, remove_orphans=True)
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
    import tempfile
    contents = await file.read()
    ext = os.path.splitext(file.filename)[1].lower() if file.filename else ".jpg"
    if ext not in [".jpg", ".jpeg", ".png", ".webp", ".bmp"]:
        ext = ".jpg"
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(contents)
        tmp_path = tmp.name
    img = Image.open(tmp_path).convert("RGB")
    output = io.BytesIO()
    img.save(output, "PDF")
    os.unlink(tmp_path)
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


@app.post("/convert/pdf-to-word")
async def pdf_to_word(file: UploadFile = File(...)):
    from pdf2docx import Converter
    import tempfile
    contents = await file.read()
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_in:
        tmp_in.write(contents)
        tmp_in_path = tmp_in.name
    tmp_out_path = tmp_in_path.replace(".pdf", ".docx")
    cv = Converter(tmp_in_path)
    cv.convert(tmp_out_path, start=0, end=None)
    cv.close()
    with open(tmp_out_path, "rb") as f:
        data = f.read()
    os.unlink(tmp_in_path)
    os.unlink(tmp_out_path)
    url = upload_to_r2(data, "converted.docx")
    return {"status": "done", "download_url": url}


@app.post("/convert/word-to-pdf")
async def word_to_pdf(file: UploadFile = File(...)):
    import subprocess
    import tempfile
    import glob
    contents = await file.read()
    suffix = ".docx" if file.filename.endswith(".docx") else ".doc"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp_in:
        tmp_in.write(contents)
        tmp_in_path = tmp_in.name
    tmp_out_dir = tempfile.mkdtemp()
    result = subprocess.run(
        ["libreoffice", "--headless", "--convert-to", "pdf", "--outdir", tmp_out_dir, tmp_in_path],
        capture_output=True, text=True
    )
    output_files = glob.glob(f"{tmp_out_dir}/*.pdf")
    if not output_files:
        raise Exception(f"LibreOffice failed: {result.stderr}")
    out_path = output_files[0]
    with open(out_path, "rb") as f:
        data = f.read()
    os.unlink(tmp_in_path)
    os.unlink(out_path)
    url = upload_to_r2(data, "converted.pdf")
    return {"status": "done", "download_url": url}
@app.post("/convert/rotate-pdf")
async def rotate_pdf(file: UploadFile = File(...), degrees: int = 90):
    import pypdf
    contents = await file.read()
    reader = pypdf.PdfReader(io.BytesIO(contents))
    writer = pypdf.PdfWriter()
    for page in reader.pages:
        page.rotate(degrees)
        writer.add_page(page)
    output = io.BytesIO()
    writer.write(output)
    url = upload_to_r2(output.getvalue(), "rotated.pdf")
    return {"status": "done", "download_url": url}