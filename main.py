import os
from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build
import openai

# 1. Load secrets
load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

# 2. Google credentials and services
SCOPES = ["https://www.googleapis.com/auth/documents",
          "https://www.googleapis.com/auth/drive"]
creds = service_account.Credentials.from_service_account_file(
    os.getenv("GOOGLE_APPLICATION_CREDENTIALS"), scopes=SCOPES)
docs = build("docs", "v1", credentials=creds)
drive = build("drive", "v3", credentials=creds)

# 3. Map CV types to Google Doc IDs
TEMPLATES = {
    "TME": "GOOGLE_DOC_ID_1",
    "SDR": "GOOGLE_DOC_ID_2",
    "Data": "GOOGLE_DOC_ID_3",
    "AI/ML": "GOOGLE_DOC_ID_4",
}

def generate_section(prompt: str) -> str:
    """Call OpenAI to draft a section."""
    resp = openai.ChatCompletion.create(
        model="gpt-4o-mini",
        messages=[{"role":"user","content": prompt}],
        max_tokens=500
    )
    return resp.choices[0].message.content.strip()

def replace_range(doc_id: str, start_index: int, end_index: int, text: str):
    """Delete the content in [start, end) and insert new text."""
    requests = [
        {"deleteContentRange": {"range": {"startIndex": start_index, "endIndex": end_index}}},
        {"insertText":        {"location": {"index": start_index}, "text": text}}
    ]
    docs.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()

def find_section_ranges(doc):
    """
    Scan doc['body']['content'].
    Identify start/end indexes for:
      - Headline paragraph (Heading 1)
      - Skills (Heading 2 “SKILLS”)
      - Standout Highlights (Heading 2 “STANDOUT HIGHLIGHTS”)
    Return a dict: {'headline':(s,e), 'skills':(s,e), 'highlights':(s,e)}
    """
    ranges = {}
    content = doc["body"]["content"]
    for i, el in enumerate(content):
        if "paragraph" not in el: continue
        text = "".join([run.get("text", "") for run in el["paragraph"]["elements"]])
        style = el["paragraph"]["paragraphStyle"].get("namedStyleType", "")
        if style == "HEADING_1" and "Archit Sachdeva" in text:
            # example: treat next paragraph(s) up to the next heading1 as the headline body
            ranges["headline"] = (el["startIndex"], el["endIndex"])
        if "SKILLS" in text:
            ranges["skills"] = (el["startIndex"], el["endIndex"])
        if "STANDOUT HIGHLIGHTS" in text:
            ranges["highlights"] = (el["startIndex"], el["endIndex"])
    return ranges

def export_pdf(doc_id: str) -> str:
    """Export the doc to PDF and return download URL."""
    request = drive.files().export_media(fileId=doc_id, mimeType="application/pdf")
    path = f"{doc_id}.pdf"
    with open(path, "wb") as f:
        f.write(request.execute())
    return path

def main():
    # 1. Get user inputs
    cv_type = input("CV template (TME/SDR/Data/AI/ML): ")
    jd = input("Paste job description:\n")
    doc_id = TEMPLATES[cv_type]

    # 2. Fetch doc structure
    doc = docs.documents().get(documentId=doc_id).execute()
    ranges = find_section_ranges(doc)

    # 3. Prepare prompts
    prompts = {
        "headline": (
            f"Write a one‑paragraph headline for a {cv_type} role. "
            "Keep TEDx talk. Tie your core strength to this job."
        ),
        "skills": (
            f"List bullet skills keyed to this job description:\n{jd}\n"
            "Include your key strengths but avoid stuffing every keyword."
        ),
        "highlights": (
            f"Write 3 standout highlights (3–5 lines each). "
            "Tie accomplishments to the role:\n{jd}"
        ),
        "cover": (
            f"Draft a 200‑word cover letter. Integrate my background as a {cv_type}. "
            f"Use the job description:\n{jd}"
        )
    }

    # 4. Generate and apply each section
    for key in ("headline","skills","highlights"):
        new_text = generate_section(prompts[key])
        s,e = ranges[key]
        replace_range(doc_id, s, e, new_text)

    # 5. Generate cover letter and append to bottom
    cover = generate_section(prompts["cover"])
    docs.documents().batchUpdate(documentId=doc_id, body={
        "requests": [{"insertText": {
            "location": {"index": doc["body"]["content"][-1]["endIndex"]},
            "text": "\n\nCOVER LETTER\n\n" + cover
        }}]
    }).execute()

    # 6. Export PDF
    pdf_path = export_pdf(doc_id)
    print("Tailored CV PDF:", pdf_path)
    print("Edit link:", f"https://docs.google.com/document/d/{doc_id}/edit")

if __name__ == "__main__":
    main()
