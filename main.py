import os
import logging
from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build
import openai

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

def copy_template(template_id: str, cv_type: str) -> str:
    """
    Make a copy of the template in Drive and return its new document ID.
    """
    copy_title = f"{cv_type} CV – Tailored"
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

def replace_range(doc_id: str, start_index: int, end_index: int, text: str):
    """Delete the content in [start, end) and insert new text."""
    # Skip any empty ranges—Google Docs API rejects start==end
    if start_index >= end_index:
        logging.warning(
            f"Empty replacement range for doc {doc_id}: "
            f"startIndex={start_index}, endIndex={end_index}. Skipping."
        )
        return

    requests = [
        {"deleteContentRange": {"range": {"startIndex": start_index, "endIndex": end_index}}},
        {"insertText":        {"location": {"index": start_index}, "text": text}}
    ]
    docs.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()

def find_section_ranges(doc):
    """
    Find byte‑ranges between each [[XXX_START]]/[[XXX_END]] marker,
    even when they’re inside tables.
    """
    content = doc["body"]["content"]

    def iter_elements(elems):
        for el in elems:
            yield el
            # Recurse into tables
            if "table" in el:
                for row in el["table"]["tableRows"]:
                    for cell in row["tableCells"]:
                        yield from iter_elements(cell.get("content", []))

    def find_marker(name):
        logging.debug(f"Looking for marker {name!r}...")
        for el in iter_elements(content):
            idx = el.get("startIndex")
            logging.debug(f"  Element at index {idx}: keys = {list(el.keys())}")
            if "paragraph" not in el:
                continue
            text = "".join(
                run.get("textRun", {}).get("content", "")
                for run in el["paragraph"]["elements"]
            )
            snippet = text.strip().replace("\n", " ")[:60]
            logging.debug(f"    Text snippet: {snippet!r}")
            if name in text:
                logging.info(f"Found marker {name!r} at index {idx}")
                return idx
        logging.error(f"Marker {name!r} not found in any scanned element")
        raise RuntimeError(f"Marker {name} not found")

    return {
        "headline": (
            find_marker("[[HEADLINE_START]]"),
            find_marker("[[HEADLINE_END]]")
        ),
        "skills": (
            find_marker("[[SKILLS_START]]"),
            find_marker("[[SKILLS_END]]")
        ),
        "highlights": (
            find_marker("[[HIGHLIGHTS_START]]"),
            find_marker("[[HIGHLIGHTS_END]]")
        )
    }

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
    cv_type = input("CV template (TME/SDR/Data/Systems): ")
    jd      = read_job_description()
    orig_id = TEMPLATES[cv_type]
    doc_id  = copy_template(orig_id, cv_type)

    # Grant edit access to anyone with the link
    drive.permissions().create(
        fileId=doc_id,
        body={"type": "anyone", "role": "writer"}
    ).execute()

    print("Created new CV copy with ID:", doc_id)

    # 2. Fetch doc structure
    doc = docs.documents().get(documentId=doc_id).execute()
    ranges = find_section_ranges(doc)

    # 3. Prepare prompts
    prompts = {
        "headline": (
            f"Write a concise headline for a {cv_type} role, maximum 50 words. "
            "Retain mention of your TEDx talk. Link your core strength to this job."
        ),
        "skills": (
            "List 6–8 bullet‑point skills for this role. "
            "Keep the first two generic skills from my CV unchanged. "
            "Replace up to three outdated or irrelevant skills (e.g. crypto or old languages) "
            "with skills directly tied to the job description below. "
            f"Use the following job description:\n{jd}\n"
            "Maintain a total of 6–8 skills."
        ),
        "highlights": (
            "Write three standout highlights (3–5 lines each). "
            "Keep any generic highlights at the top. "
            "For each outdated or irrelevant highlight (e.g. crypto or prior‑role specifics), "
            "remove it and replace it with a highlight directly tied to the job description below. "
            f"Use the following job description:\n{jd}\n"
            "Maintain exactly three highlights."
        ),
        "cover": (
            f"Draft a 200‑word cover letter for a {cv_type} role. "
            "Use my skills and experience, including my TEDx talk, to show why I’m passionate about this role "
            "and how I can contribute to the organization. "
            f"Integrate details from the job description below:\n{jd}\n"
            "End with a paragraph focused on the specific responsibilities of the role, and conclude with the following closing exactly:\n"
            "\"Thank you for considering my application, and I look forward to hearing from you.\n\nBest regards,\n\nArchit Sachdeva\n\narchit.sachdeva007@gmail.com\n\n+44 7925 218447\n\nReading, UK\""
        )
    }

    # 4. Generate and apply each section
    for key in ("headline","skills","highlights"):
        new_text = generate_section(prompts[key])
        s, e = ranges[key]
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