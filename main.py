from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from PyPDF2 import PdfReader
import os
from pdf2image import convert_from_bytes
import pytesseract
import io

# Initialize FastAPI
app = FastAPI()

# Allow frontend to talk to backend
app.add_middleware(
    CORSMiddleware, 
    allow_origins=["http://127.0.0.1:5500", "http://localhost:5500"], 
    allow_methods=["*"], 
    allow_headers=["*"]
)

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
api_key = os.environ.get("GOOGLE_API_KEY", "__dummy__") 

llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0, google_api_key=api_key)
structured_llm = llm.with_structured_output(ExtractedReferralData)

@app.post("/extract")
async def extract_data(file: UploadFile = File(...)):
    print(f"\n--- DEBUG: STARTING EXTRACTION FOR {file.filename} ---")
    
    try:
        # 3. READ THE PDF AND EXTRACT TEXT
        file_bytes = await file.read()
        
        # Try standard text extraction first (Fast)
        print("Attempting standard text extraction...")
        pdf_reader = PdfReader(io.BytesIO(file_bytes))
        text = ""
        for page in pdf_reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text
                
        # OCR FALLBACK (If standard extraction is empty)
        if not text.strip():
            print("Standard extraction failed (likely a scanned fax). Falling back to OCR...")
            try:
                images = convert_from_bytes(file_bytes)
                for i, image in enumerate(images):
                    print(f"Running OCR on page {i + 1}...")
                    text += pytesseract.image_to_string(image)
            except Exception as e:
                print(f"OCR Failed: {str(e)}")
                raise HTTPException(status_code=500, detail=f"OCR processing failed: {str(e)}")
                
Medico_Extractor
Public
            if not text.strip():
                raise HTTPException(
                    status_code=400, 
                    detail="Could not extract text via standard reading or OCR. The document may be blank."
                )
                
        print(f"Extraction successful. Total characters: {len(text)}")
        
        # 4. CREATE THE PROMPT
        system_instruction = (
            "You are an expert medical data extraction algorithm. "
            "Extract the requested patient, insurance, and referral information from the text. "
            "Do not make up information or guess. If a specific piece of information is missing, "
            "return an empty string for that field."
        )
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", system_instruction),
            ("human", "{text}")
        ])
        
        # 5. CHAIN AND EXECUTE
        print("Sending text to Gemini...")
        chain = prompt | structured_llm
        result = chain.invoke({"text": text[:50000]}) 
        
        print("--- DEBUG: EXTRACTION COMPLETE ---")
        return result
        
    except HTTPException:
        raise # Re-raise HTTP exceptions so FastAPI handles them properly
    except Exception as e:
        print(f"CRITICAL ERROR: {str(e)}") 
        raise HTTPException(status_code=500, detail=str(e))