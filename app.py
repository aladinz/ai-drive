import json
import mimetypes
import os
import re
import shutil
import sys
import zipfile
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import quote, unquote
from urllib.error import URLError
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

try:
  import fitz
except ImportError:
  fitz = None

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


PORT = 8899
DOCS_DIR = "docs"
CHUNK_WORDS = 300
CHUNK_OVERLAP = 50
TOP_K = 3
LLM_ENDPOINT = "http://localhost:8080/v1/chat/completions"
LLM_HEALTHCHECK = "http://localhost:8080/v1/models"
MIN_DIRECT_TEXT_WORDS = 20


HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Estate Knowledge Base</title>
  <style>
    :root {
      --bg: #1a1a2e;
      --card: #16213e;
      --accent: #7c3aed;
      --text: #e2e8f0;
      --muted: #94a3b8;
      --border: #253152;
      --card-2: #1c2a4b;
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background: radial-gradient(circle at top, #22345f 0%, var(--bg) 45%);
      color: var(--text);
      min-height: 100vh;
      display: flex;
      justify-content: center;
      padding: 22px 12px;
    }

    .app {
      width: 100%;
      max-width: 860px;
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 18px;
      box-shadow: 0 20px 40px rgba(0, 0, 0, 0.35);
      overflow: hidden;
      display: flex;
      flex-direction: column;
      height: min(90vh, 980px);
    }

    .header {
      padding: 18px 20px;
      border-bottom: 1px solid var(--border);
      background: linear-gradient(180deg, rgba(124, 58, 237, 0.14) 0%, rgba(124, 58, 237, 0.02) 100%);
    }

    .title {
      margin: 0;
      font-size: 1.3rem;
      display: flex;
      align-items: center;
      gap: 10px;
    }

    .subtitle {
      margin-top: 6px;
      color: var(--muted);
      font-size: 0.94rem;
    }

    .toolbar {
      padding: 14px 16px;
      border-bottom: 1px solid var(--border);
      background: rgba(0, 0, 0, 0.15);
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 10px;
    }

    .original-banner {
      display: none;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 12px 16px;
      border-bottom: 1px solid var(--border);
      background: linear-gradient(90deg, rgba(124, 58, 237, 0.2), rgba(124, 58, 237, 0.05));
    }

    .original-banner-copy {
      color: #ddd6fe;
      font-size: 0.9rem;
      line-height: 1.4;
    }

    .search {
      width: 100%;
      border-radius: 12px;
      border: 1px solid #3a4f7f;
      padding: 11px 12px;
      background: #1c2a4b;
      color: var(--text);
      font-size: 0.95rem;
      outline: none;
    }

    .search:focus {
      border-color: var(--accent);
      box-shadow: 0 0 0 3px rgba(124, 58, 237, 0.25);
    }

    .clear-btn {
      border: none;
      border-radius: 12px;
      background: var(--accent);
      color: white;
      font-weight: 600;
      padding: 0 16px;
      cursor: pointer;
    }

    .original-link {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      text-decoration: none;
      white-space: nowrap;
      padding: 9px 14px;
      background: #7c3aed;
      border: 1px solid #9f6eff;
      box-shadow: 0 8px 16px rgba(124, 58, 237, 0.25);
    }

    .count {
      color: var(--muted);
      font-size: 0.84rem;
      margin-top: 2px;
      grid-column: 1 / -1;
    }

    .sections {
      padding: 16px;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }

    .section-card {
      background: var(--card-2);
      border: 1px solid #2d3f68;
      border-radius: 12px;
      overflow: hidden;
    }

    .section-head {
      padding: 10px 12px;
      border-bottom: 1px solid #2d3f68;
      background: rgba(124, 58, 237, 0.12);
    }

    .section-title {
      margin: 0;
      font-size: 0.95rem;
      font-weight: 700;
    }

    .section-meta {
      margin-top: 3px;
      font-size: 0.78rem;
      color: var(--muted);
    }

    .section-body {
      padding: 12px;
      font-size: 0.92rem;
      line-height: 1.6;
      white-space: pre-wrap;
      color: #dbe5f5;
    }

    mark {
      background: rgba(124, 58, 237, 0.35);
      color: #f6f2ff;
      border-radius: 4px;
      padding: 0 2px;
    }

    .empty {
      border: 1px dashed #3b4f7d;
      color: var(--muted);
      border-radius: 12px;
      padding: 18px;
      text-align: center;
      background: rgba(148, 163, 184, 0.04);
    }

    .empty-title {
      margin: 0 0 8px;
      color: var(--text);
      font-size: 1rem;
      font-weight: 700;
    }

    .empty-copy {
      margin: 0;
      line-height: 1.6;
    }

    .empty-path {
      display: inline-block;
      margin: 10px 0 0;
      padding: 6px 10px;
      border-radius: 999px;
      border: 1px solid #3a4f7f;
      background: rgba(28, 42, 75, 0.9);
      color: #dbe5f5;
      font-family: Consolas, "Courier New", monospace;
      font-size: 0.85rem;
    }

    .empty-steps {
      margin: 14px 0 0;
      padding: 0;
      list-style: none;
      display: grid;
      gap: 8px;
      text-align: left;
    }

    .empty-step {
      border: 1px solid #2d3f68;
      border-radius: 10px;
      padding: 10px 12px;
      background: rgba(0, 0, 0, 0.12);
      color: #dbe5f5;
    }

    .search:disabled,
    .clear-btn:disabled {
      opacity: 0.55;
      cursor: not-allowed;
    }

    @media (max-width: 640px) {
      .title { font-size: 1.07rem; }
      .subtitle { font-size: 0.86rem; }
      .original-banner {
        flex-direction: column;
        align-items: stretch;
      }
      .original-link {
        width: 100%;
      }
      .toolbar { grid-template-columns: 1fr; }
      .clear-btn { height: 40px; }
    }
  </style>
</head>
<body>
  <main class="app">
    <header class="header">
      <h1 class="title">📋 Estate Knowledge Base</h1>
      <div class="subtitle" id="subtitle">Loading document reference...</div>
    </header>

    <section id="originalBanner" class="original-banner">
      <div class="original-banner-copy">Viewing HTML? Open the original file for exact formatting and interactive behavior.</div>
      <a id="originalLink" class="clear-btn original-link" href="#" target="_blank" rel="noopener noreferrer">Open Original HTML</a>
    </section>

    <section class="toolbar">
      <input id="search" class="search" placeholder="Search this document (or use Ctrl+F)..." autocomplete="off" />
      <button id="clearBtn" class="clear-btn" type="button">Clear</button>
      <div id="count" class="count"></div>
    </section>

    <section id="sections" class="sections"></section>
  </main>

  <script>
    window.__REFERENCE_BOOTSTRAP__ = __BOOTSTRAP_JSON__;
  </script>

  <script>
    const subtitleEl = document.getElementById("subtitle");
    const searchEl = document.getElementById("search");
    const clearBtnEl = document.getElementById("clearBtn");
    const originalBannerEl = document.getElementById("originalBanner");
    const originalLinkEl = document.getElementById("originalLink");
    const sectionsEl = document.getElementById("sections");
    const countEl = document.getElementById("count");
    const boot = window.__REFERENCE_BOOTSTRAP__ || { documents: 0, sections: [], status_message: "", docs_path: "docs", original_html_url: "" };

    let allSections = [];

    function escapeHtml(text) {
      return (text || "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
    }

    function highlight(text, query) {
      const safe = escapeHtml(text);
      if (!query) return safe;
      const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      const regex = new RegExp("(" + escaped + ")", "ig");
      return safe.replace(regex, "<mark>$1</mark>");
    }

    function renderSections(sections, query) {
      sectionsEl.innerHTML = "";

      if (!sections.length) {
        if (query) {
          sectionsEl.innerHTML = '<div class="empty">No matching sections. Try a different word or clear the search.</div>';
        } else {
          const docsPath = boot.docs_path || "docs";
          const message = boot.status_message || "No documents indexed yet. Add PDF or DOCX files to the docs folder.";
          sectionsEl.innerHTML =
            '<div class="empty">' +
              '<h2 class="empty-title">Add documents to begin</h2>' +
              '<p class="empty-copy">' + escapeHtml(message) + '</p>' +
              '<div class="empty-path">' + escapeHtml(docsPath) + '</div>' +
              '<ul class="empty-steps">' +
                '<li class="empty-step">Place .pdf, .docx, or .html files in this folder.</li>' +
                '<li class="empty-step">Keep this window open, then refresh after copying files.</li>' +
                '<li class="empty-step">Search will unlock automatically once documents are indexed.</li>' +
              '</ul>' +
            '</div>';
        }
        countEl.textContent = "0 sections shown";
        return;
      }

      sections.forEach((sec) => {
        const card = document.createElement("article");
        card.className = "section-card";

        const title = highlight(sec.title, query);
        const body = highlight(sec.content, query);

        card.innerHTML =
          '<div class="section-head">' +
            '<h3 class="section-title">' + title + '</h3>' +
            '<div class="section-meta">' + escapeHtml(sec.source) + '</div>' +
          '</div>' +
          '<div class="section-body">' + body + '</div>';

        sectionsEl.appendChild(card);
      });

      countEl.textContent = sections.length + " section(s) shown";
    }

    function applyFilter() {
      const q = searchEl.value.trim().toLowerCase();
      if (!q) {
        renderSections(allSections, "");
        return;
      }

      const filtered = allSections.filter((s) => {
        return (s.title + " " + s.content + " " + s.source).toLowerCase().includes(q);
      });

      renderSections(filtered, q);
    }

    function loadReference() {
      allSections = boot.sections || [];
      const hasSections = allSections.length > 0;
      searchEl.disabled = !hasSections;
      clearBtnEl.disabled = !hasSections;
      if (boot.original_html_url) {
        originalLinkEl.href = boot.original_html_url;
        originalBannerEl.style.display = "flex";
      } else {
        originalBannerEl.style.display = "none";
      }
      searchEl.placeholder = hasSections
        ? "Search this document (or use Ctrl+F)..."
        : "Add PDF, DOCX, or HTML files to E:\\docs to enable search";
      subtitleEl.textContent = `${boot.documents} document(s) • ${allSections.length} section(s) • Structured Reference`;
      renderSections(allSections, "");
    }

    searchEl.addEventListener("input", applyFilter);
    clearBtnEl.addEventListener("click", () => {
      searchEl.value = "";
      applyFilter();
      searchEl.focus();
    });

    loadReference();
  </script>
</body>
</html>
"""


@dataclass
class Chunk:
    text: str
    source: str
    pages: list
    page_label: str


class EstateSearchEngine:
  def __init__(self, docs_path: str):
    self.docs_path = docs_path
    self.source_files = []
    self.chunks = []
    self.reference_sections = []
    self.document_count = 0
    self.vectorizer = None
    self.matrix = None
    self.status_message = ""

  def load(self):
    source_files = []
    for name in sorted(os.listdir(self.docs_path)):
      lower = name.lower()
      if lower.endswith((".pdf", ".docx", ".html", ".htm")):
        source_files.append(name)

    self.source_files = source_files

    if not source_files:
      self.status_message = (
        f"No PDF, DOCX, or HTML files found in {os.path.abspath(self.docs_path)}. "
        "Add your files there, then refresh or run start.bat again."
      )
      print(f"No PDF, DOCX, or HTML files found in: {os.path.abspath(self.docs_path)}")
      print("Add your files there, then run start.bat again.")
      return True

    all_chunks = []
    all_sections = []
    warned_missing_pymupdf = False

    for filename in source_files:
      print(f"📄 Reading: {filename}...")
      file_path = os.path.join(self.docs_path, filename)
      page_word_stream = []
      used_ocr_on_file = False
      ocr_unavailable_detected = False

      lower = filename.lower()

      if lower.endswith(".docx"):
        try:
          docx_text = extract_docx_text(file_path)
          words = tokenize(docx_text)
          page_word_stream = [(word, 1) for word in words]
          all_sections.extend(build_reference_sections(docx_text, filename))
        except Exception as exc:
          print(f"Skipping {filename}: {exc}")
          continue
      elif lower.endswith((".html", ".htm")):
        try:
          html_sections = extract_html_sections(file_path, filename)
          if html_sections:
            html_text = "\n\n".join(
              f"{sec['title']}\n{sec['content']}"
              for sec in html_sections
              if sec.get("content")
            )
            all_sections.extend(html_sections)
          else:
            html_text = extract_html_text(file_path)
            all_sections.extend(build_reference_sections(html_text, filename))

          words = tokenize(html_text)
          page_word_stream = [(word, 1) for word in words]
        except Exception as exc:
          print(f"Skipping {filename}: {exc}")
          continue
      else:
        if fitz is None:
          if not warned_missing_pymupdf:
            print("PyMuPDF is not installed. PDF files will be skipped. Run setup.bat or install pymupdf in the selected Python environment.")
            warned_missing_pymupdf = True
          continue
        try:
          with fitz.open(file_path) as doc:
            page_texts = []
            for page_index, page in enumerate(doc):
              text, used_ocr, ocr_available = extract_page_text(page)
              words = tokenize(text)
              page_num = page_index + 1
              if text.strip():
                page_texts.append(f"Page {page_num}\n{text}")
              if used_ocr:
                used_ocr_on_file = True
              if not ocr_available:
                ocr_unavailable_detected = True
              for word in words:
                page_word_stream.append((word, page_num))
            if page_texts:
              all_sections.extend(build_reference_sections("\n\n".join(page_texts), filename))
        except Exception as exc:
          print(f"Skipping {filename}: {exc}")
          continue

      if used_ocr_on_file:
        print(f"   OCR used for scanned page(s) in {filename}")
      elif lower.endswith(".pdf") and (not page_word_stream) and ocr_unavailable_detected:
        print("   OCR not available. Install Tesseract OCR to read scanned/image PDFs.")
      elif lower.endswith(".docx") and not page_word_stream:
        print("   No extractable text found in DOCX (it may contain images/scans only).")
      elif lower.endswith((".html", ".htm")) and not page_word_stream:
        print("   No extractable text found in HTML.")

      file_chunks = build_chunks(page_word_stream, filename)
      all_chunks.extend(file_chunks)

    if not all_chunks:
      self.status_message = (
        "Files were found, but no readable text was extracted. "
        "If PDFs are scanned or image-only, install Tesseract OCR and try again."
      )
      print("Files were found, but no readable text was extracted.")
      print("If PDFs are scanned/image-only, install Tesseract OCR and re-run start.bat.")
      return True

    self.chunks = all_chunks
    self.reference_sections = all_sections if all_sections else [
      {
        "title": f"Passage {i + 1}",
        "source": chunk.source,
        "content": chunk.text,
      }
      for i, chunk in enumerate(self.chunks)
    ]
    self.document_count = len(source_files)
    self.status_message = ""

    self.vectorizer = TfidfVectorizer(stop_words="english")
    self.matrix = self.vectorizer.fit_transform([chunk.text for chunk in self.chunks])

    print(
      f"✅ Created {len(self.chunks)} searchable passages and "
      f"{len(self.reference_sections)} reference sections from {self.document_count} documents"
    )
    return True

  def original_html_url(self):
    html_files = [
      name for name in self.source_files
      if name.lower().endswith((".html", ".htm"))
    ]
    if len(html_files) == 1:
      return "/docs/" + quote(html_files[0])
    return ""

    def search(self, question: str, top_k: int = TOP_K):
        if not question.strip() or self.matrix is None:
            return []

        question_vec = self.vectorizer.transform([question])
        scores = cosine_similarity(question_vec, self.matrix).flatten()

        # Keyword fallback: when TF-IDF finds no overlap (all scores are 0),
        # score chunks by how many query words they contain verbatim.
        if scores.max() == 0:
            stop = getattr(self.vectorizer, "stop_words_", set()) or set()
            query_words = [
                w.lower()
                for w in re.findall(r"\S+", question)
                if w.lower().rstrip("?.,!") not in stop
            ]
            if query_words:
                for i, chunk in enumerate(self.chunks):
                    chunk_lower = chunk.text.lower()
                    hits = sum(1 for w in query_words if w.rstrip("?.,!") in chunk_lower)
                    scores[i] = hits / len(query_words)

        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
        results = []
        for idx, score in ranked[:top_k]:
            chunk = self.chunks[idx]
            results.append(
                {
                    "text": chunk.text,
                    "source": chunk.source,
                    "pages": chunk.pages,
                    "page_label": chunk.page_label,
                    "score": float(score),
                }
            )
        return results


def tokenize(text: str):
    return re.findall(r"\S+", text or "")


def extract_page_text(page):
    text = page.get_text("text") or ""
    if len(tokenize(text)) >= MIN_DIRECT_TEXT_WORDS:
        return text, False, True

    # Fallback for scanned PDFs: use PyMuPDF OCR when available (requires Tesseract).
    try:
        textpage = page.get_textpage_ocr(language="eng", dpi=300)
        ocr_text = page.get_text("text", textpage=textpage) or ""
        if len(tokenize(ocr_text)) > len(tokenize(text)):
            return ocr_text, True, True
        return text, False, True
    except Exception:
        return text, False, False


def extract_docx_text(file_path):
  with zipfile.ZipFile(file_path, "r") as zf:
    xml_data = zf.read("word/document.xml")

  root = ET.fromstring(xml_data)
  ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
  paragraphs = []
  for para in root.findall(".//w:p", ns):
    parts = []
    for node in para.findall(".//w:t", ns):
      if node.text:
        parts.append(node.text)
    line = " ".join(parts).strip()
    if line:
      paragraphs.append(line)

  return "\n\n".join(paragraphs)


class HTMLTextExtractor(HTMLParser):
  def __init__(self):
    super().__init__()
    self._chunks = []
    self._skip_depth = 0

  def handle_starttag(self, tag, attrs):
    tag = tag.lower()
    if tag in {"script", "style", "noscript"}:
      self._skip_depth += 1
      return
    if self._skip_depth == 0 and tag in {"h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "div", "section", "article", "br", "tr"}:
      self._chunks.append("\n")

  def handle_endtag(self, tag):
    tag = tag.lower()
    if tag in {"script", "style", "noscript"} and self._skip_depth > 0:
      self._skip_depth -= 1
      return
    if self._skip_depth == 0 and tag in {"h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "div", "section", "article", "td", "th"}:
      self._chunks.append("\n")

  def handle_data(self, data):
    if self._skip_depth == 0 and data.strip():
      self._chunks.append(data.strip())

  def get_text(self):
    text = " ".join(self._chunks)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def extract_html_text(file_path):
  with open(file_path, "r", encoding="utf-8", errors="ignore") as html_file:
    html_text = html_file.read()

  parser = HTMLTextExtractor()
  parser.feed(html_text)
  return parser.get_text()


def _clean_html_text(text):
  text = unescape(text or "")
  text = re.sub(r"\s+", " ", text)
  text = text.replace(" | ", "|")
  return text.strip()


def _normalize_lines(chunks):
  text = "".join(chunks)
  text = unescape(text)
  text = re.sub(r"[ \t\r\f\v]+", " ", text)
  text = re.sub(r"\n[ \t]+", "\n", text)
  text = re.sub(r"\n{3,}", "\n\n", text)
  return text.strip()


class HTMLSectionExtractor(HTMLParser):
  def __init__(self, source):
    super().__init__()
    self.source = source
    self.sections = []
    self._skip_depth = 0
    self._in_section_article = False
    self._in_section_content = False
    self._current_title = ""
    self._current_chunks = []

  def handle_starttag(self, tag, attrs):
    t = tag.lower()
    attrs_map = {k.lower(): v for k, v in attrs}

    if t in {"script", "style", "noscript"}:
      self._skip_depth += 1
      return

    if self._skip_depth > 0:
      return

    classes = attrs_map.get("class", "")

    if t == "article" and "section-card" in classes:
      self._in_section_article = True
      self._in_section_content = False
      self._current_chunks = []
      self._current_title = _clean_html_text(attrs_map.get("data-title", "Section")) or "Section"
      return

    if not self._in_section_article:
      return

    if t == "div" and "section-content" in classes:
      self._in_section_content = True
      return

    if not self._in_section_content:
      return

    if t in {"h3", "h4", "p", "li", "tr", "br"}:
      self._current_chunks.append("\n")
    if t in {"th", "td"}:
      self._current_chunks.append(" ")

  def handle_endtag(self, tag):
    t = tag.lower()

    if t in {"script", "style", "noscript"} and self._skip_depth > 0:
      self._skip_depth -= 1
      return

    if self._skip_depth > 0:
      return

    if t == "div" and self._in_section_content:
      self._in_section_content = False
      return

    if t == "article" and self._in_section_article:
      content = _normalize_lines(self._current_chunks)
      if content:
        self.sections.append(
          {
            "title": self._current_title,
            "source": self.source,
            "content": content,
          }
        )
      self._in_section_article = False
      self._in_section_content = False
      self._current_title = ""
      self._current_chunks = []
      return

    if self._in_section_content and t in {"h3", "h4", "p", "li", "tr"}:
      self._current_chunks.append("\n")

  def handle_data(self, data):
    if self._skip_depth > 0 or not self._in_section_content:
      return
    value = _clean_html_text(data)
    if value:
      self._current_chunks.append(value)


def extract_html_sections(file_path, source):
  with open(file_path, "r", encoding="utf-8", errors="ignore") as html_file:
    html_text = html_file.read()

  parser = HTMLSectionExtractor(source)
  parser.feed(html_text)
  parser.close()
  return parser.sections


def is_reference_heading(line):
    t = (line or "").strip()
    if not t:
        return False

    words = t.split()
    letters = [c for c in t if c.isalpha()]
    upper_ratio = 0.0
    if letters:
        upper_ratio = sum(1 for c in letters if c.isupper()) / len(letters)

    if len(words) <= 12 and (t.endswith(":") or upper_ratio >= 0.72):
        return True

    lower = t.lower()
    if re.match(r"^(step\s*\d+|section\s*\d+|part\s*\d+)", lower):
        return True
    if lower.startswith(("what to do", "final note", "recap", "summary", "important", "p.s.")):
        return True

    return False


def build_reference_sections(text, source):
    lines = [line.strip() for line in re.split(r"\n+", text or "") if line.strip()]
    if not lines:
        return []

    sections = []
    current_title = "Overview"
    current_body = []

    def flush_section():
        if current_body:
            sections.append(
                {
                    "title": current_title,
                    "source": source,
                    "content": "\n\n".join(current_body).strip(),
                }
            )

    for line in lines:
        if is_reference_heading(line):
            flush_section()
            current_title = line[:120]
            current_body = []
        else:
            current_body.append(line)

    flush_section()
    return sections


def configure_tesseract():
    # Try PATH first, then common Windows install paths, then USB-local folders.
    candidates = []
    existing = shutil.which("tesseract")
    if existing:
        candidates.append(existing)

    base_dir = os.path.dirname(os.path.abspath(__file__))
    candidates.extend(
        [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            os.path.join(base_dir, "Tesseract-OCR", "tesseract.exe"),
            os.path.join(base_dir, "tesseract", "tesseract.exe"),
        ]
    )

    for exe_path in candidates:
        if not exe_path:
            continue
        if not os.path.isfile(exe_path):
            continue

        exe_dir = os.path.dirname(exe_path)
        current_path = os.environ.get("PATH", "")
        if exe_dir not in current_path:
            os.environ["PATH"] = exe_dir + os.pathsep + current_path

        tessdata = os.path.join(exe_dir, "tessdata")
        if os.path.isdir(tessdata):
          os.environ.setdefault("TESSDATA_PREFIX", tessdata + os.sep)

        return exe_path

    return None


def compress_pages(page_numbers):
    if not page_numbers:
        return ""
    if len(page_numbers) == 1:
        return f"p. {page_numbers[0]}"

    ranges = []
    start = page_numbers[0]
    end = page_numbers[0]

    for num in page_numbers[1:]:
        if num == end + 1:
            end = num
        else:
            ranges.append((start, end))
            start = num
            end = num
    ranges.append((start, end))

    labels = []
    for s, e in ranges:
        if s == e:
            labels.append(str(s))
        else:
            labels.append(f"{s}-{e}")

    return "pp. " + ", ".join(labels)


def build_chunks(word_stream, source_name):
    chunks = []
    if not word_stream:
        return chunks

    step = CHUNK_WORDS - CHUNK_OVERLAP
    i = 0
    while i < len(word_stream):
        window = word_stream[i : i + CHUNK_WORDS]
        if not window:
            break

        words = [w for w, _ in window]
        pages = sorted(set(p for _, p in window))
        chunks.append(
            Chunk(
                text=" ".join(words),
                source=source_name,
                pages=pages,
                page_label=compress_pages(pages),
            )
        )

        if i + CHUNK_WORDS >= len(word_stream):
            break
        i += step

    return chunks


def check_llm_available():
    try:
        req = Request(LLM_HEALTHCHECK, method="GET")
        with urlopen(req, timeout=1.5) as res:
            return 200 <= res.status < 500
    except Exception:
        return False


def build_passage_answer(results):
    if not results:
        return "I could not find relevant information in the indexed documents.", []

    lines = ["Here are the most relevant sections from your documents:\n"]
    sources = []
    for idx, item in enumerate(results, start=1):
        score_pct = round(item["score"] * 100, 1)
        lines.append(f"[{idx}] {item['source']} ({item['page_label']}) - similarity {score_pct}%")
        lines.append(item["text"][:1200])
        lines.append("")
        sources.append(f"{item['source']} {item['page_label']}")

    return "\n".join(lines).strip(), sources


def ask_llm(question, results):
    excerpts = []
    for i, item in enumerate(results, start=1):
        excerpts.append(
            f"Excerpt {i}\\nDocument: {item['source']}\\nPages: {item['page_label']}\\nText: {item['text']}"
        )

    user_prompt = (
        "Question:\n"
        + question
        + "\n\n"
        + "Document Excerpts:\n"
        + "\n\n".join(excerpts)
    )

    payload = {
        "model": "local-model",
        "messages": [
            {
                "role": "system",
                "content": "You are a helpful estate document assistant. Answer the question using ONLY the provided document excerpts. If the information isn't in the excerpts, say so honestly. Always cite which document and page the information comes from.",
            },
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,
    }

    req = Request(
        LLM_ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urlopen(req, timeout=20) as res:
        body = json.loads(res.read().decode("utf-8"))

    content = body.get("choices", [{}])[0].get("message", {}).get("content", "")
    return content.strip() or "I could not generate an answer from the provided excerpts."


class AppState:
    def __init__(self, engine, llm_enabled):
        self.engine = engine
        self.llm_enabled = llm_enabled

    @property
    def mode(self):
        return "llm" if self.llm_enabled else "passage"


def make_handler(state: AppState):
    class Handler(BaseHTTPRequestHandler):
        def _send_json(self, code, payload):
            data = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_text(self, code, body, content_type="text/plain; charset=utf-8"):
            data = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_file(self, file_path):
            try:
                with open(file_path, "rb") as f:
                    data = f.read()
            except OSError:
                self._send_json(404, {"error": "File not found"})
                return

            mime, _ = mimetypes.guess_type(file_path)
            content_type = mime or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/":
                bootstrap = {
                    "documents": state.engine.document_count,
                    "sections": state.engine.reference_sections,
                    "status_message": state.engine.status_message,
                    "docs_path": os.path.abspath(state.engine.docs_path),
                    "original_html_url": state.engine.original_html_url(),
                }
                boot_json = json.dumps(bootstrap).replace("</", "<\\/")
                page = HTML_PAGE.replace("__BOOTSTRAP_JSON__", boot_json)
                self._send_text(200, page, "text/html; charset=utf-8")
                return

            if self.path.startswith("/docs/"):
                rel_part = unquote(self.path[len("/docs/"):])
                candidate = os.path.abspath(os.path.join(state.engine.docs_path, rel_part))
                docs_root = os.path.abspath(state.engine.docs_path)
                if os.path.commonpath([candidate, docs_root]) != docs_root:
                    self._send_json(403, {"error": "Forbidden"})
                    return
                self._send_file(candidate)
                return

            if self.path == "/api/status":
                self._send_json(
                    200,
                    {
                        "documents": state.engine.document_count,
                        "passages": len(state.engine.chunks),
                        "sections": len(state.engine.reference_sections),
                        "status_message": state.engine.status_message,
                        "mode": state.mode,
                    },
                )
                return

            if self.path == "/api/reference":
                self._send_json(
                    200,
                    {
                        "documents": state.engine.document_count,
                        "sections": state.engine.reference_sections,
                        "status_message": state.engine.status_message,
                    },
                )
                return

            self._send_json(404, {"error": "Not found"})

        def do_POST(self):
            if self.path != "/api/query":
                self._send_json(404, {"error": "Not found"})
                return

            try:
                content_len = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(content_len)
                payload = json.loads(raw.decode("utf-8"))
                question = (payload.get("question") or "").strip()
            except Exception:
                self._send_json(400, {"error": "Invalid JSON"})
                return

            if not question:
                self._send_json(400, {"error": "Question is required"})
                return

            results = state.engine.search(question, top_k=TOP_K)

            llm_answer = None
            llm_sources = []
            if state.llm_enabled and results:
                try:
                    llm_answer = ask_llm(question, results)
                    llm_sources = [f"{r['source']} {r['page_label']}" for r in results]
                except Exception:
                    llm_answer = None

            results_payload = [
                {
                    "source": r["source"],
                    "page_label": r["page_label"],
                    "score": round(r["score"], 3),
                    "text": (r["text"][:500] + "\u2026") if len(r["text"]) > 500 else r["text"],
                }
                for r in results
            ]

            self._send_json(200, {
                "answer": llm_answer,
                "sources": llm_sources,
                "results": results_payload,
            })

        def log_message(self, format_str, *args):
            return

    return Handler


def main():
  base_dir = os.path.dirname(os.path.abspath(__file__))
  docs_dir = os.path.join(base_dir, DOCS_DIR)
  tesseract_path = configure_tesseract()

  if not os.path.isdir(docs_dir):
    os.makedirs(docs_dir, exist_ok=True)

  if tesseract_path:
    print(f"OCR engine detected: {tesseract_path}")
  else:
    print("OCR engine not detected (Tesseract). Scanned PDFs may not be readable.")

  engine = EstateSearchEngine(docs_dir)
  engine.load()

  llm_enabled = check_llm_available()
  if llm_enabled:
    print("🤖 AI mode: Connected to local LLM")
  else:
    print("📑 Passage mode: Showing relevant document sections (no LLM detected)")

  state = AppState(engine, llm_enabled)
  server = HTTPServer(("", PORT), make_handler(state))

  print(f"🌐 Ready at http://localhost:{PORT}")

  try:
    server.serve_forever()
  except KeyboardInterrupt:
    print("\nShutting down...")
  finally:
    server.server_close()


if __name__ == "__main__":
    main()
