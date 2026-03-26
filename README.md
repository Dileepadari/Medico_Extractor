# Linear Health - Medical Referral Extractor 📄🩺

A full-stack application designed to automate the extraction of critical patient, insurance, and clinical data from medical referral documents. The system intelligently processes both native digital PDFs and scanned faxes using a hybrid extraction approach (PyPDF2 + Tesseract OCR) and leverages Google's Gemini 2.5 Flash model via LangChain to guarantee structured, predictable JSON outputs.

## ✨ Features

  * **Intelligent Text Extraction:** Attempts fast, native text extraction first.
  * **Smart OCR Fallback:** Automatically detects scanned faxes/images and falls back to Optical Character Recognition (OCR) to read the text.
  * **Structured AI Parsing:** Uses LangChain and Pydantic nested models to force the Gemini LLM to return strictly typed JSON matching the frontend schema.
  * **Resilient Fallbacks:** Gracefully handles missing document data by returning empty strings instead of breaking or hallucinating.
  * **Modern UI:** A clean, responsive drag-and-drop web interface built with Vanilla JS and CSS.

-----

## 💻 System Prerequisites

Because this application reads scanned faxes, you must have the underlying OCR engines installed on your operating system before running the Python code.

**Ubuntu / Debian (Linux):**

```bash
sudo apt-get update
sudo apt-get install tesseract-ocr poppler-utils
```

**macOS (via Homebrew):**

```bash
brew install tesseract poppler
```

**Windows:**

  * Download and install the [Tesseract executable](https://www.google.com/search?q=https://github.com/UB-Mannheim/tesseract/wiki).
  * Download [Poppler for Windows](https://github.com/oschwartz10612/poppler-windows/releases/) and add it to your system PATH.

-----

## 🚀 Installation & Setup

### 1\. Clone the repository

```bash
git clone https://github.com/Dileepadari/Medico_Extractor.git
cd Medico_Extractor
```

### 2\. Set up the Python Virtual Environment

It is highly recommended to run this project inside an isolated virtual environment.

```bash
python3 -m venv venv

# On macOS/Linux:
source venv/bin/activate  

# On Windows:
venv\Scripts\activate
```

### 3\. Install Dependencies

Install all required Python packages using the provided requirements file:

```bash
pip install -r requirements.txt
```

### 4\. Configure Environment Variables

You need a Google Gemini API key to run the extraction engine. Set the key in your terminal before starting the server:

**Linux / macOS:**

```bash
export GOOGLE_API_KEY="your_actual_api_key_here"
```

**Windows (Command Prompt):**

```cmd
set GOOGLE_API_KEY="your_actual_api_key_here"
```

or just add it to .env file

-----

## 🏃‍♂️ Running the Application

You will need two terminal windows open to run the backend and frontend simultaneously.

### 1\. Start the Backend (FastAPI)

In your first terminal (make sure your `venv` is active), run the Uvicorn server:

```bash
uvicorn main:app --reload
```

*The API will be available at `http://localhost:8000`*
*Interactive API documentation is available at `http://localhost:8000/docs`*

### 2\. Start the Frontend

In your second terminal, navigate to the folder containing your `index.html` file and start a local web server:

```bash
python3 -m http.server 5500
```

Open your browser and navigate to `http://localhost:5500`.

-----

## 📡 API Reference

### `POST /extract`

Accepts a PDF file upload and returns structured extracted data.

**Request:**

  * **Method:** `POST`
  * **Content-Type:** `multipart/form-data`
  * **Body:** `file` (The PDF document)

**Response:**
Returns a JSON object matching the `ExtractedReferralData` Pydantic model.

```json
{
  "patient_demographics": {
    "name": "Jane Doe",
    "dob": "01/15/1980",
    "phone": "555-0198",
    "email": "jane.doe@email.com"
  },
  "primary_insurance": {
    "member_id": "ABC123456789",
    "group_id": "GRP987",
    "insurance_name": "Blue Cross",
    "plan_name": "PPO"
  },
  "secondary_insurance": {
    "member_id": "",
    "group_id": ""
  },
  "referral_source": {
    "provider_name": "Dr. Smith",
    "clinic_name": "City General Hospital",
    "title": "MD",
    "phone": "555-1000"
  },
  "referral_received_date": {
    "date": "10/24/2023"
  }
}
```
