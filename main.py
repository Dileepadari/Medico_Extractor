from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage
import os
import base64
from pathlib import Path
from dotenv import load_dotenv

# Initialize FastAPI
app = FastAPI()

# Allow frontend to talk to backend
app.add_middleware(
    CORSMiddleware, 
    allow_origins=["*"], 
    allow_methods=["*"], 
    allow_headers=["*"],
)

# Serve static files (optional folder: ./static)
static_dir = Path(__file__).resolve().parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

@app.get("/", include_in_schema=False)
async def serve_index():
    # Try project root index.html first, then static/index.html
    root_index = Path(__file__).resolve().parent / "index.html"
    static_index = static_dir / "index.html"
    if root_index.exists():
        return FileResponse(str(root_index))
    if static_index.exists():
        return FileResponse(str(static_index))
    raise HTTPException(status_code=404, detail="index.html not found. Place index.html in project root or ./static/")


# 1. DEFINE NESTED STRUCTURED DATA FORMAT (Pydantic)
class PatientDemographics(BaseModel):
    name: str = Field(default="", description="Patient's Name. Leave empty if not found.")
    dob: str = Field(default="", description="Patient's Date of Birth. Leave empty if not found.")
    phone: str = Field(default="", description="Patient's phone number. Leave empty if not found.")
    email: str = Field(default="", description="Patient's email address. Leave empty if not found.")

class PrimaryInsurance(BaseModel):
    member_id: str = Field(default="", description="Primary insurance member ID. Leave empty if not found.")
    group_id: str = Field(default="", description="Primary insurance group ID. Leave empty if not found.")
    insurance_name: str = Field(default="", description="Name of the primary insurance provider. Leave empty if not found.")
    plan_name: str = Field(default="", description="Name of the specific insurance plan. Leave empty if not found.")

class SecondaryInsurance(BaseModel):
    member_id: str = Field(default="", description="Secondary insurance member ID. Leave empty if not found.")
    group_id: str = Field(default="", description="Secondary insurance group ID. Leave empty if not found.")

class ReferralSource(BaseModel):
    provider_name: str = Field(default="", description="Name of the referring provider or doctor. Leave empty if not found.")
    clinic_name: str = Field(default="", description="Name of the referring clinic or hospital. Leave empty if not found.")
    title: str = Field(default="", description="Title of the referring provider (e.g., MD, DO, NP). Leave empty if not found.")
    phone: str = Field(default="", description="Phone number of the referring clinic or provider. Leave empty if not found.")

class ReferralReceivedDate(BaseModel):
    date: str = Field(default="", description="The date the referral was received, created, or faxed. Leave empty if not found.")

class ExtractedReferralData(BaseModel):
    patient_demographics: PatientDemographics
    primary_insurance: PrimaryInsurance
    secondary_insurance: SecondaryInsurance
    referral_source: ReferralSource
    referral_received_date: ReferralReceivedDate

# 2. SETUP THE LLM
load_dotenv()
api_key = os.environ.get("GOOGLE_API_KEY", "__dummy__") 

llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0, google_api_key=api_key)
structured_llm = llm.with_structured_output(ExtractedReferralData)

@app.post("/extract")
async def extract_data(file: UploadFile = File(...)):
    print(f"\n--- DEBUG: STARTING EXTRACTION FOR {file.filename} ---")
    
    try:
        # 3. READ THE FILE
        file_bytes = await file.read()
        
        # Determine the mime type so Gemini knows what kind of file it is looking at
        mime_type = file.content_type
        if not mime_type:
            # Fallback based on extension
            if file.filename.lower().endswith(".pdf"):
                mime_type = "application/pdf"
            else:
                mime_type = "image/jpeg"
                
        # 4. CONVERT TO BASE64
        # Gemini expects file data encoded as a base64 string
        encoded_file = base64.b64encode(file_bytes).decode("utf-8")
        
        # 5. CREATE THE PROMPT
        system_instruction = (
            "You are an expert medical data extraction algorithm. "
            "Extract the requested patient, insurance, and referral information from the provided document. "
            "Do not make up information or guess. If a specific piece of information is missing, "
            "return an empty string for that field."
        )
        
        # 6. CONSTRUCT MULTIMODAL MESSAGE
        # We pass the text instructions and the raw file data in a single message payload
        messages = [
            SystemMessage(content=system_instruction),
            HumanMessage(
                content=[
                    {"type": "text", "text": "Please extract the required data from this document."},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{encoded_file}"}
                    }
                ]
            )
        ]
        
        # 7. EXECUTE
        print("Sending document directly to Gemini (Multimodal)...")
        result = structured_llm.invoke(messages)
        
        print("--- DEBUG: EXTRACTION COMPLETE ---")
        return result
        
    except Exception as e:
        print(f"CRITICAL ERROR: {str(e)}") 
        raise HTTPException(status_code=500, detail=str(e))