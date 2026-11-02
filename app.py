"""ATS Resume Checker - Streamlit + Gemini Flash.

Upload a resume (PDF or DOCX), optionally paste a job description, and get:
  * an ATS score out of 100
  * a section-by-section breakdown
  * missing keywords
  * concrete suggestions to improve the resume
"""

import io
import json
import os
import re

import streamlit as st
from docx import Document
from google import genai
from google.genai import types
from pypdf import PdfReader

DEFAULT_MODEL = "gemini-3.2-flash"
MAX_RESUME_CHARS = 15000  # keeps requests small and cheap
MAX_JD_CHARS = 6000

SYSTEM_PROMPT = """You are an expert ATS (Applicant Tracking System) analyst and \
professional resume coach. You evaluate resumes strictly and honestly. \
Never invent experience, skills, or numbers that are not in the resume. \
Respond with JSON only."""

JSON_INSTRUCTIONS = """Return a single JSON object with exactly these keys:
{
  "ats_score": integer 0-100,
  "summary": string (2-3 sentences, overall verdict),
  "section_scores": {
    "formatting_and_structure": integer 0-100,
    "keywords_and_skills": integer 0-100,
    "work_experience_impact": integer 0-100,
    "education_and_certifications": integer 0-100,
    "clarity_and_grammar": integer 0-100
  },
  "strengths": [string, ...],
  "weaknesses": [string, ...],
  "missing_keywords": [string, ...],
  "improvements": [
    {"priority": "High" | "Medium" | "Low", "issue": string, "fix": string}
  ],
  "rewritten_examples": [
    {"original": string, "improved": string}
  ]
}
Scoring guide: 90+ excellent, 75-89 good, 60-74 average, below 60 needs major work.
Give 3-8 items for strengths, weaknesses and improvements, and up to 3 rewritten_examples
(only rewrite bullet points that actually appear in the resume, without adding fake facts)."""


# --------------------------------------------------------------------------- #
# Text extraction
# --------------------------------------------------------------------------- #
def extract_text(uploaded_file) -> str:
    """Return plain text from an uploaded PDF or DOCX file."""
    name = uploaded_file.name.lower()
    data = uploaded_file.getvalue()

    if name.endswith(".pdf"):
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception:
                raise ValueError("This PDF is password protected.")
        pages = [(page.extract_text() or "") for page in reader.pages]
        return "\n".join(pages).strip()

    if name.endswith(".docx"):
        doc = Document(io.BytesIO(data))
        parts = [p.text for p in doc.paragraphs]
        for table in doc.tables:  # many resumes use tables for layout
            for row in table.rows:
                for cell in row.cells:
                    parts.append(cell.text)
        return "\n".join(parts).strip()

    raise ValueError("Unsupported file type. Please upload a PDF or DOCX.")


# --------------------------------------------------------------------------- #
# Quick rule-based checks (no AI needed, instant)
# --------------------------------------------------------------------------- #
def basic_checks(text: str) -> list[tuple[bool, str]]:
    """Return (passed, message) pairs; the message already matches the result."""
    lower = text.lower()
    words = len(text.split())

    def check(passed: bool, ok_msg: str, bad_msg: str) -> tuple[bool, str]:
        return passed, ok_msg if passed else bad_msg

    return [
        check(bool(re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text)),
              "Email address found", "Email address not found"),
        check(bool(re.search(r"(\+?\d[\d\s().-]{8,}\d)", text)),
              "Phone number found", "Phone number not found"),
        check(bool(re.search(r"linkedin\.com|github\.com", lower)),
              "LinkedIn / GitHub link found", "No LinkedIn / GitHub link found"),
        check(any(k in lower for k in ("experience", "internship", "employment")),
              "Experience section found", "Experience section not found"),
        check(any(k in lower for k in ("education", "university", "bachelor", "degree")),
              "Education section found", "Education section not found"),
        check(any(k in lower for k in ("skills", "technologies", "tools")),
              "Skills section found", "Skills section not found"),
        check(250 <= words <= 1200,
              f"Length looks reasonable ({words} words)",
              f"Length is {words} words (ideal is about 300-900)"),
    ]


# --------------------------------------------------------------------------- #
# Gemini call
# --------------------------------------------------------------------------- #
def parse_json(raw: str) -> dict:
    """Parse model output into a dict, tolerating ```json fences."""
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise


def clamp(value, low=0, high=100) -> int:
    try:
        return max(low, min(high, int(round(float(value)))))
    except (TypeError, ValueError):
        return 0


def analyze_resume(resume_text: str, job_description: str, api_key: str, model: str) -> dict:
    client = genai.Client(api_key=api_key)

    prompt = f"{JSON_INSTRUCTIONS}\n\n"
    if job_description.strip():
        prompt += (
            "Evaluate the resume against this job description. Keyword and skill "
            "matching should be judged against it.\n"
            f"--- JOB DESCRIPTION ---\n{job_description[:MAX_JD_CHARS]}\n\n"
        )
    else:
        prompt += "No job description was given; evaluate for general ATS-friendliness.\n\n"
    prompt += f"--- RESUME ---\n{resume_text[:MAX_RESUME_CHARS]}"

    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            temperature=0.2,
        ),
    )
    if not response.text:
        raise RuntimeError("The model returned an empty response. Please try again.")

    result = parse_json(response.text)

    # Normalise so the UI never crashes on a slightly-off response.
    result["ats_score"] = clamp(result.get("ats_score"))
    sections = result.get("section_scores") or {}
    result["section_scores"] = {k: clamp(v) for k, v in sections.items()}
    for key in ("strengths", "weaknesses", "missing_keywords", "improvements", "rewritten_examples"):
        if not isinstance(result.get(key), list):
            result[key] = []
    result["summary"] = str(result.get("summary", ""))
    return result


# --------------------------------------------------------------------------- #
# UI
# --------------------------------------------------------------------------- #
def score_label(score: int) -> tuple[str, str]:
    if score >= 90:
        return "Excellent", "green"
    if score >= 75:
        return "Good", "green"
    if score >= 60:
        return "Average", "orange"
    return "Needs work", "red"


def get_api_key() -> str:
    try:
        if "GEMINI_API_KEY" in st.secrets:
            return st.secrets["GEMINI_API_KEY"]
    except Exception:
        pass  # no secrets file locally
    return os.environ.get("GEMINI_API_KEY", "")


def render_results(result: dict, resume_text: str) -> None:
    score = result["ats_score"]
    label, color = score_label(score)

    st.subheader("Your ATS score")
    col1, col2 = st.columns([1, 3])
    col1.metric("Score", f"{score}/100")
    col2.markdown(f"**:{color}[{label}]**")
    col2.progress(score / 100)
    if result["summary"]:
        st.write(result["summary"])

    st.subheader("Section breakdown")
    for key, value in result["section_scores"].items():
        st.write(key.replace("_", " ").title())
        st.progress(value / 100, text=f"{value}/100")

    st.subheader("Quick checks")
    for ok, message in basic_checks(resume_text):
        st.write(("✅ " if ok else "⚠️ ") + message)

    left, right = st.columns(2)
    with left:
        st.subheader("Strengths")
        for item in result["strengths"]:
            st.write(f"- {item}")
    with right:
        st.subheader("Weaknesses")
        for item in result["weaknesses"]:
            st.write(f"- {item}")

    if result["missing_keywords"]:
        st.subheader("Missing keywords")
        st.write(", ".join(f"`{k}`" for k in result["missing_keywords"]))

    st.subheader("How to improve")
    icons = {"high": "🔴", "medium": "🟠", "low": "🟢"}
    for item in result["improvements"]:
        if not isinstance(item, dict):
            continue
        icon = icons.get(str(item.get("priority", "")).lower(), "🔹")
        with st.expander(f"{icon} {item.get('priority', '')}: {item.get('issue', '')}"):
            st.write(item.get("fix", ""))

    if result["rewritten_examples"]:
        st.subheader("Example rewrites")
        for ex in result["rewritten_examples"]:
            if isinstance(ex, dict):
                st.markdown(f"**Before:** {ex.get('original', '')}")
                st.markdown(f"**After:** {ex.get('improved', '')}")
                st.divider()

    st.download_button(
        "Download report (JSON)",
        data=json.dumps(result, indent=2),
        file_name="ats_report.json",
        mime="application/json",
    )


def main() -> None:
    st.set_page_config(page_title="ATS Resume Checker", page_icon="📄", layout="wide")
    st.title("📄 ATS Resume Checker")
    st.caption("Upload your resume to get an ATS score and tips to improve it.")

    with st.sidebar:
        st.header("Settings")
        api_key = get_api_key()
        if api_key:
            st.success("API key loaded")
        else:
            api_key = st.text_input("Gemini API key", type="password",
                                    help="Get a free key at aistudio.google.com")
        model = st.text_input("Gemini model", value=os.environ.get("GEMINI_MODEL", DEFAULT_MODEL))
        st.caption("Your resume is sent to Google's Gemini API for analysis.")

    uploaded = st.file_uploader("Upload resume (PDF or DOCX)", type=["pdf", "docx"])
    job_description = st.text_area(
        "Job description (optional, but gives a more accurate score)", height=150
    )

    if st.button("Analyze resume", type="primary"):
        if not uploaded:
            st.warning("Please upload a resume first.")
            return
        if not api_key:
            st.warning("Please add your Gemini API key in the sidebar.")
            return

        try:
            with st.spinner("Reading your resume..."):
                resume_text = extract_text(uploaded)
        except Exception as exc:
            st.error(f"Could not read the file: {exc}")
            return

        if len(resume_text.split()) < 50:
            st.error(
                "Very little text was found. If your resume is a scanned image, "
                "ATS systems can't read it either. Export it as a text-based PDF or DOCX."
            )
            return

        try:
            with st.spinner("Analyzing with Gemini..."):
                result = analyze_resume(resume_text, job_description, api_key, model)
        except json.JSONDecodeError:
            st.error("The AI response was not valid JSON. Please click Analyze again.")
            return
        except Exception as exc:
            st.error(f"Analysis failed: {exc}")
            return

        st.session_state["result"] = result
        st.session_state["resume_text"] = resume_text

    if "result" in st.session_state:
        render_results(st.session_state["result"], st.session_state["resume_text"])


if __name__ == "__main__":
    main()
