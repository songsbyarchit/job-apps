import os
import logging
from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build
import openai
from googleapiclient.errors import HttpError

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

def read_job_description() -> str:
    """
    Prompt for a multi‑line job description in the terminal.
    Finish input by hitting Enter on an empty line twice.
    """
    print("Paste the full job description. When done, press Enter on an empty line twice:")
    lines = []
    empty_count = 0
    while True:
        line = input()
        if not line.strip():
            empty_count += 1
            if empty_count >= 2:
                break
            continue
        empty_count = 0
        lines.append(line)
    return "\n".join(lines)

def main():
    # 1. Get user inputs
    cv_type   = input("CV template (TME/SDR/Data/Systems): ")
    company   = input("Company name: ")
    job_title = input("Job title: ")
    jd        = read_job_description()
    orig_id   = TEMPLATES[cv_type]
    doc_id    = copy_template(orig_id, cv_type, company)

    # Grant edit access to anyone with the link
    drive.permissions().create(
        fileId=doc_id,
        body={"type": "anyone", "role": "writer"}
    ).execute()

    print("Created new CV copy with ID:", doc_id)

    # 2. Fetch doc structure
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
    orig_skills = orig_skills_map.get(cv_type, "")

    def read_cv_text(cv_type: str) -> str:
        filename = f"cv_{cv_type}.txt"
        with open(filename, "r", encoding="utf-8") as f:
            return f.read()

    cv_text = read_cv_text(cv_type)

    # 3. Prepare prompts
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
            f"Write a concise headline for a {job_title} role (MUST be a maximum of 50 words and no more than this). "
            "Begin the first sentence by restating a SIMPLIFIED version of the job title "
            "For example: if the job title is 'Head of Brand Marketing', start with 'Brand marketer with...'; "
            "if 'Senior Data Engineer', start with 'Data engineer with...'; "
            "if 'Systems Engineering/Architecture Expert', start with 'Systems engineer with...'. "
            "Retain mention of your TEDx talk. Link your core strength to this job. "
            "Use British English. Avoid passive voice. Do not use participle phrases. No em dashes. "
            "Do not use first person (no 'I', 'my', or 'me')."
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
            "Write in British English. Avoid passive voice. Do not use participle phrases. No em dashes. "
            "Conclude with the following closing exactly:\n"
            "\"Thank you for considering my application, and I look forward to hearing from you.\n\nBest regards,\n\nArchit Sachdeva\narchit.sachdeva007@gmail.com\n+44 7925 218447\nReading, UK\""
        )
    }

    # 4. Generate and apply each section
    new_text = generate_section(prompts["headline"])
    print(f"DEBUG: Generated headline -> {new_text!r}")
    replace_placeholder_text(doc_id, "<<<HEADLINE_PLACEHOLDER>>>", new_text)

    # 4b. Generate and apply skills
    for key in ("skills",):
        new_text = generate_section(prompts[key])
        replace_placeholder_text(doc_id, "<<<SKILLS_PLACEHOLDER>>>", new_text)

    # 5. Generate cover letter in its own document
    cover = generate_section(prompts["cover"])
    cover_doc = docs.documents().create(body={"title": f"{cv_type} Cover Letter"}).execute()
    cover_doc_id = cover_doc["documentId"]
    docs.documents().batchUpdate(documentId=cover_doc_id, body={
        "requests": [{"insertText": {
            "location": {"index": 1},
            "text": cover
        }}]
    }).execute()
    drive.permissions().create(
        fileId=cover_doc_id,
        body={"type": "anyone", "role": "writer"}
    ).execute()

    # 7. Export PDF
    pdf_path = export_pdf(doc_id)

    print("\n\n\n========================")  # Three empty lines + divider bar!

    # 🚨🚨🚨 Cover letter and CV created. Edit them here:
    print("🚨 Cover letter link:", f"https://docs.google.com/document/d/{cover_doc_id}/edit")
    print("🚨 New CV edit link:", f"https://docs.google.com/document/d/{doc_id}/edit")

if __name__ == "__main__":
    main()