# 📄 ATS Resume Checker

A Streamlit app that scores a resume for ATS (Applicant Tracking System) friendliness and suggests improvements, powered by Google's Gemini Flash model.

## Features
- Upload a resume as **PDF** or **DOCX**
- Optional **job description** for a more accurate keyword match
- ATS score out of 100 with a section-by-section breakdown
- Strengths, weaknesses, missing keywords
- Prioritised improvement tips and example bullet-point rewrites
- Instant rule-based checks (email, phone, sections, length)
- Download the report as JSON

## Run locally

1. Install Python 3.10+.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Get a free API key from [Google AI Studio](https://aistudio.google.com/apikey).
4. Set the key (or paste it into the app's sidebar):
   ```bash
   # macOS / Linux
   export GEMINI_API_KEY="your-key"
   # Windows PowerShell
   $env:GEMINI_API_KEY="your-key"
   ```
5. Start the app:
   ```bash
   streamlit run app.py
   ```

## Configuration
| Setting | Where | Default |
|---|---|---|
| `GEMINI_API_KEY` | environment variable or Streamlit secret | none (can be typed in sidebar) |
| `GEMINI_MODEL` | environment variable or sidebar box | `gemini-2.5-flash` |

## Deploy on Streamlit Community Cloud
1. Push this repo to GitHub (public or private).
2. Go to [share.streamlit.io](https://share.streamlit.io) and click **Create app**.
3. Choose your repo, branch `main`, and main file `app.py`.
4. Open **Advanced settings → Secrets** and add:
   ```toml
   GEMINI_API_KEY = "your-key"
   ```
5. Click **Deploy**.

> Never commit your API key to GitHub. Use Secrets or environment variables only.

## Limitations
- Scanned/image-only resumes cannot be read (ATS systems can't read them either).
- The score is an AI estimate, not the output of a real company's ATS.
- Resume text is sent to the Gemini API for analysis.

## Project structure
```
app.py             # Streamlit app
requirements.txt   # Python dependencies
README.md          # This file
```
