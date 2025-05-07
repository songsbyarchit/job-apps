import os
from flask import Flask, render_template, request
import logging
from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build
import openai
from googleapiclient.errors import HttpError

app = Flask(__name__)

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        cv_type   = request.form["cv_type"]
        company   = request.form["company"]
        job_title = request.form["job_title"]
        jd        = request.form["job_description"]

        orig_id   = TEMPLATES[cv_type]
        doc_id    = copy_template(orig_id, cv_type, company)

        drive.permissions().create(
            fileId=doc_id,
            body={"type": "anyone", "role": "writer"}
        ).execute()

        doc = docs.documents().get(documentId=doc_id).execute()

        orig_skills_map = {
            "TME": (
                "Go‑to‑Market Strategy\n"
                "Sales Enablement & Campaign Content\n"
                "Customer Education & Retention\n"
                "Public Speaking (TEDx)"
            ),
            "SDR": (
                "Outbound Prospecting\n"
                "Discovery Questioning & Pitching\n"
                "Sales Enablement Messaging\n"
                "TEDx Speaking & Storytelling"
            ),
            "Data": (
                "ETL Pipelines (SQL, Python)\n"
                "Data Warehousing & Modelling\n"
                "Business Intelligence Tools\n"
                "Public Speaking (TEDx)"
            ),
            "Systems": (
                "Go‑to‑Market Strategy\n"
                "Pre‑Sales Engineering\n"
                "Cross‑Team Product Coordination\n"
                "Infrastructure Storytelling (TEDx)"
            )
        }
        orig_skills = orig_skills_map[cv_type]

        with open(f"cv_{cv_type}.txt", "r", encoding="utf-8") as f:
            cv_text = f.read()

        prompts = {
            "skills": (
                "Here are my existing skills:\n"
                f"{orig_skills}\n\n"
                "Now, list 4 plain text skills (no bullets, no numbering, no asterisks). "
                "Each skill must be 4–6 words maximum. "
                "You may keep some existing ones if they align closely with the job description. "
                "Replace others as needed to reflect the exact skills the employer asks for. "
                "Maintain the same number of lines as the original. "
                "Use this job description for reference:\n\n"
                f"{jd}"
            ),
            "headline": (
                f"Write a personal CV headline for a {job_title} role, NOT a job advert. "
                "The headline should describe the applicant, not the company. "
                "It must sound like a summary at the top of a CV, not an employer's description. "
                "Use third-person voice, no first-person or company language. "
                "Begin with a simplified version of the job title: "
                "e.g., 'Data engineer with...', 'Brand marketer with...', etc. "
                "Retain mention of TEDx talk. Focus on specific strengths linked to the job. "
                "Maximum 50 words. British English only. Avoid passive voice. No participle phrases. No em dashes."
            ),
            "cover": (
                f"Draft a 200‑word cover letter for a {cv_type} role. "
                "Begin with “Dear Hiring Manager,” and do not include any address or date. "
                "Use my skills and TEDx experience to show why I’m passionate about this role and how I can contribute. "
                "Seamlessly integrate specific details from the job description below. "
                "Be deliberate about linking specifically mentioned traits smoothly to values which I have, proven by outcomes I have driven based on the CV contents.\n\n"
                "CV:\n"
                f"{cv_text}\n\n"
                "Job description:\n"
                f"{jd}\n\n"
                "Write in British English. Avoid passive voice. No em dashes.\n"
                "Conclude with the following closing exactly:\n"
                "\"Thank you for considering my application, and I look forward to hearing from you.\n\nBest regards,\n\nArchit Sachdeva\narchit.sachdeva007@gmail.com\n+44 7925 218447\nReading, UK\""
            )
        }

        new_text = generate_section(prompts["headline"])
        replace_placeholder_text(doc_id, "<<<HEADLINE_PLACEHOLDER>>>", new_text)

        new_text = generate_section(prompts["skills"])
        replace_placeholder_text(doc_id, "<<<SKILLS_PLACEHOLDER>>>", new_text)

        cover = generate_section(prompts["cover"])
        cover_doc = docs.documents().create(body={"title": f"{cv_type} Cover Letter"}).execute()
        cover_doc_id = cover_doc["documentId"]
        docs.documents().batchUpdate(documentId=cover_doc_id, body={
            "requests": [{"insertText": {"location": {"index": 1}, "text": cover}}]
        }).execute()

        drive.permissions().create(
            fileId=cover_doc_id,
            body={"type": "anyone", "role": "writer"}
        ).execute()

        pdf_path = export_pdf(doc_id)

        return f"""
        <p>🚨 Cover letter link: <a href="https://docs.google.com/document/d/{cover_doc_id}/edit" target="_blank">Open</a></p>
        <p>🚨 New CV edit link: <a href="https://docs.google.com/document/d/{doc_id}/edit" target="_blank">Open</a></p>
        <p>✅ PDF saved as: {pdf_path}</p>
        """
    return render_template("index.html")

# Configure logging
logging.basicConfig(level=logging.DEBUG, format="%(levelname)s:%(message)s")
logging.getLogger("googleapiclient.discovery_cache").setLevel(logging.WARNING)

# 1. Load secrets
load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

# 2. Google credentials & clients
SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive"
]
creds = service_account.Credentials.from_service_account_file(
    os.getenv("GOOGLE_APPLICATION_CREDENTIALS"),
    scopes=SCOPES
)
docs = build("docs", "v1", credentials=creds)
drive = build("drive", "v3", credentials=creds)

# 3. Map CV types to your Google Doc template IDs
TEMPLATES = {
    "TME":     "1o4jRSJWVksGm73Tg1kGU8TyDF-4sT4NZ14HXXaYyxtU",
    "SDR":     "1EzrvMRQmGE8iKW2iRD7t2W2DWoX7t9Y6j2jadNMADho",
    "Data":    "1BHfjKacvRCRKWqkZVwfOaiNmt8JmZvUIIuJlhFKYepA",
    "Systems": "1xtokZv7OgVV_bmp2OGBz9bT5xiIw2JeX0FUsoTVm3lI"
}

def replace_placeholder_text(doc_id: str, placeholder: str, new_text: str):
    """Replaces the exact placeholder with new text safely."""
    try:
        docs.documents().batchUpdate(documentId=doc_id, body={
            "requests": [
                {
                    "replaceAllText": {
                        "containsText": {"text": placeholder, "matchCase": True},
                        "replaceText": new_text
                    }
                }
            ]
        }).execute()
    except HttpError as e:
        logging.warning(f"Failed to replace placeholder {placeholder} in doc {doc_id}. Error: {e}")

def copy_template(template_id: str, cv_type: str, company: str) -> str:
    copy_title = f"{cv_type} CV – {company} – Tailored"
    body = {"name": copy_title}
    copied = drive.files().copy(fileId=template_id, body=body).execute()
    return copied["id"]

def generate_section(prompt: str) -> str:
    """Call OpenAI to draft a section."""
    resp = openai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role":"user","content": prompt}],
        max_tokens=500
    )
    return resp.choices[0].message.content.strip()

def export_pdf(doc_id: str) -> str:
    """Export the doc to PDF and return download URL."""
    request = drive.files().export_media(fileId=doc_id, mimeType="application/pdf")
    path = f"{doc_id}.pdf"
    with open(path, "wb") as f:
        f.write(request.execute())
    return path

if __name__ == "__main__":
    app.run(debug=True)