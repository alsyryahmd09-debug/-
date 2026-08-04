#!/usr/bin/env python3
"""Build the deploy-ready Sutoor search indexes from every supported project file."""

from __future__ import annotations

import csv
import html
import json
import re
import sys
import time
import unicodedata
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "sutoor-search"
INDEX_VERSION = "3.0.0"
MAX_BODY_CHARS = 16000
PASSAGE_CHARS = 3600
SUPPORTED = {".html", ".htm", ".json", ".jsonld", ".pdf", ".docx", ".txt", ".md", ".markdown", ".xml", ".rdf", ".owl", ".csv"}
SKIP_DIRS = {".git", ".netlify", "node_modules", "test-results", "__pycache__"}
GENERATED = {"search-index.json", "semantic-graph.json", "heritage.idx", "ontology.idx", "genealogy.idx", "books.idx", "articles.idx"}

FIELD_WEIGHT = {"title": 8, "keywords": 5, "section": 3.5, "heading": 2.5, "desc": 2, "body": 1, "alt": 1.5}
STOP = set(
    "في من على الى إلى عن مع هذا هذه ذلك تلك التي الذي الذين اللاتي كان كانت يكون قد لقد ثم او أو ام أم لا ما لم لن ان أن إن انه أنه هو هي هم هن نحن انت أنت بين بعد قبل عند حتى كل بعض غير سوى حيث لدى منذ خلال ضمن دون ايضا أيضا كما بها به لها له وهو وهي the a an of in on at to for and or but is are was were be been by with from that this these those it as".split()
)
AR_PREFIX = ["والت", "فالت", "بالت", "كالت", "وال", "فال", "بال", "كال", "لال", "ولل", "الت", "ال", "لل", "و", "ف", "ب", "ك", "ل", "س"]
AR_SUFFIX = ["اتهما", "اتهم", "اتكم", "اتها", "تهما", "هما", "كما", "تين", "هم", "هن", "كم", "كن", "نا", "ها", "ية", "ات", "ون", "ين", "ان", "تي", "ه", "ة", "ي", "ا"]

CATEGORY_TERMS = {
    "ontology": re.compile(r"انطولوج|أنطولوج|ontology|semantic|rdf|owl|skos|linked data|معرفي", re.I),
    "genealogy": re.compile(r"نسب|أنساب|انساب|مشجر|شجرة العائلة|قبيل|عشير|genealog|lineage|ansab", re.I),
    "books": re.compile(r"كتاب|مخطوط|مؤلف|مصنف|رسالة|دراسة|بحث|bibliograph|book|manuscript|publication", re.I),
    "articles": re.compile(r"مقال|article|خبر|دليل|تقرير|ورقة بحث", re.I),
    "heritage": re.compile(r"تراث|تاريخ|أثر|اثر|معلم|قلعة|مسجد|دلمون|أوال|البحرين|heritage|history|landmark", re.I),
}


@dataclass
class Document:
    title: str
    section: str
    type: str
    url: str
    desc: str = ""
    heading: str = ""
    keywords: str = ""
    alt: str = ""
    body: str = ""
    img: str = ""
    updated: str = ""
    rank: float = 1.0
    source: str = ""
    categories: set[str] = field(default_factory=set)


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()


def normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    text = re.sub(r"[\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06ed\u08d3-\u08e1\u08e3-\u08ff\u0640]", "", text)
    table = str.maketrans({
        "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ء": "", "ى": "ي", "ئ": "ي", "ؤ": "و", "ة": "ه",
        "گ": "ك", "ک": "ك", "چ": "ج", "پ": "ب", "ژ": "ز", "ڤ": "ف", "ی": "ي",
        "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4", "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
        "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4", "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9",
    })
    text = text.translate(table)
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def tokenize(value: Any) -> list[str]:
    return [token[:40] for token in normalize(value).split() if len(token) >= 2 or token.isdigit()]


def stem(token: str) -> str:
    word = token
    if re.search(r"[\u0600-\u06ff]", word):
        for prefix in AR_PREFIX:
            if word.startswith(prefix) and len(word) - len(prefix) >= 3:
                word = word[len(prefix):]
                break
        for suffix in AR_SUFFIX:
            if word.endswith(suffix) and len(word) - len(suffix) >= 3:
                word = word[:-len(suffix)]
                break
        return word
    if len(word) >= 4:
        if word.endswith("ies"):
            return word[:-3] + "y"
        for suffix in ("ments", "ment", "ingly", "edly", "ing", "ed", "es", "s"):
            if word.endswith(suffix) and len(word) - len(suffix) >= 3:
                return word[:-len(suffix)]
    return word


def public_url(path: Path) -> str:
    relative = path.relative_to(ROOT).as_posix()
    return "/" + "/".join(quote(part) for part in relative.split("/"))


def chunks(text: str, limit: int = PASSAGE_CHARS) -> list[str]:
    text = clean_text(text)
    if not text:
        return []
    if len(text) <= limit:
        return [text]
    sentences = re.split(r"(?<=[.!؟!؛])\s+|\n+", text)
    output: list[str] = []
    current = ""
    for sentence in sentences:
        sentence = clean_text(sentence)
        if not sentence:
            continue
        if len(current) + len(sentence) + 1 > limit and current:
            output.append(current)
            current = ""
        while len(sentence) > limit:
            output.append(sentence[:limit])
            sentence = sentence[limit:]
        current = (current + " " + sentence).strip()
    if current:
        output.append(current)
    return output


class PageParser(HTMLParser):
    BLOCKED = {"style", "noscript", "svg", "canvas"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.description = ""
        self.keywords = ""
        self.image = ""
        self.passages: list[tuple[str, str, str]] = []
        self.embedded: list[tuple[str, str]] = []
        self.jsonld: list[str] = []
        self._blocked = 0
        self._heading_level = 0
        self._heading_text: list[str] = []
        self._heading = ""
        self._anchor = ""
        self._buffer: list[str] = []
        self._capture_title = False
        self._in_script = False
        self._script_type = ""
        self._script_id = ""
        self._script_buffer: list[str] = []
        self._alts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): value or "" for key, value in attrs}
        tag = tag.lower()
        if tag in self.BLOCKED:
            self._blocked += 1
            return
        if tag == "script":
            self._in_script = True
            self._script_type = values.get("type", "").lower()
            self._script_id = values.get("id") or values.get("data-name") or f"embed-{len(self.embedded) + 1}"
            self._script_buffer = []
            return
        if tag == "iframe" and values.get("srcdoc"):
            self.embedded.append((values.get("id") or values.get("title") or f"frame-{len(self.embedded) + 1}", values["srcdoc"]))
        if tag == "title":
            self._capture_title = True
        if tag == "meta":
            name = (values.get("name") or values.get("property") or "").lower()
            content = values.get("content", "")
            if name in {"description", "og:description"} and not self.description:
                self.description = content
            elif name == "keywords":
                self.keywords = content
            elif name in {"og:image", "twitter:image"} and not self.image:
                self.image = content
        if tag == "img":
            self._alts.extend(filter(None, (values.get("alt"), values.get("title"))))
        if re.fullmatch(r"h[1-6]", tag):
            self._flush()
            self._heading_level = int(tag[1])
            self._heading_text = []
            self._anchor = values.get("id", "")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self.BLOCKED:
            self._blocked = max(0, self._blocked - 1)
            return
        if tag == "script":
            content = "".join(self._script_buffer).strip()
            if self._script_type == "text/plain" and len(re.sub(r"\s", "", content)) > 80:
                self.embedded.append((self._script_id, content))
            elif self._script_type == "application/ld+json" and content:
                self.jsonld.append(content)
            self._in_script = False
            self._script_type = ""
            self._script_buffer = []
            return
        if tag == "title":
            self._capture_title = False
        if re.fullmatch(r"h[1-6]", tag):
            self._heading = clean_text(" ".join(self._heading_text)) or self._heading
            self._heading_level = 0

    def handle_data(self, data: str) -> None:
        if self._in_script:
            self._script_buffer.append(data)
            return
        if self._blocked:
            return
        value = clean_text(data)
        if not value:
            return
        if self._capture_title:
            self.title = clean_text(self.title + " " + value)
        if self._heading_level:
            self._heading_text.append(value)
        else:
            self._buffer.append(value)

    def close(self) -> None:
        super().close()
        self._flush()

    def _flush(self) -> None:
        body = clean_text(" ".join(self._buffer))
        if body:
            self.passages.append((self._heading, self._anchor, body))
        self._buffer = []

    @property
    def alts(self) -> str:
        return clean_text(" ".join(self._alts))


def make_documents(title: str, section: str, kind: str, url: str, body: str, *, desc: str = "", heading: str = "", keywords: str = "", alt: str = "", img: str = "", source: str = "", rank: float = 1.0) -> list[Document]:
    output = []
    for index, passage in enumerate(chunks(body)):
        passage_title = heading or title
        if index:
            passage_title = f"{passage_title} — جزء {index + 1}"
        output.append(Document(
            title=clean_text(passage_title), section=clean_text(section or title), type=kind, url=url,
            desc=clean_text(desc or passage[:220]), heading=clean_text(heading), keywords=clean_text(keywords),
            alt=clean_text(alt), body=passage[:MAX_BODY_CHARS], img=img, rank=rank, source=source,
        ))
    return output


def parse_html_text(raw: str, url: str, source: str, depth: int = 0, label: str = "") -> tuple[list[Document], list[tuple[str, str, str]]]:
    parser = PageParser()
    parser.feed(raw)
    parser.close()
    page_title = parser.title or label or Path(source.split("#", 1)[0]).stem
    docs: list[Document] = []
    triples: list[tuple[str, str, str]] = []
    for heading, anchor, body in parser.passages:
        target = url + ("#" + quote(anchor) if anchor else "")
        docs.extend(make_documents(page_title, page_title, "صفحة", target, body, desc=parser.description, heading=heading, keywords=parser.keywords, alt=parser.alts, img=parser.image, source=source))
    for block in parser.jsonld:
        try:
            data = json.loads(block)
            json_docs, json_triples = parse_json_data(data, url, source + "#json-ld", "البيانات المنظّمة")
            docs.extend(json_docs)
            triples.extend(json_triples)
        except (ValueError, TypeError):
            continue
    if depth < 3:
        for embed_id, embedded in parser.embedded:
            embed_url = url + "#" + quote(embed_id)
            embedded_docs, embedded_triples = parse_html_text(embedded, embed_url, source + "#" + embed_id, depth + 1, embed_id)
            docs.extend(embedded_docs)
            triples.extend(embedded_triples)
    return docs, triples


def flatten_json(value: Any, path: str = "", lines: list[str] | None = None) -> list[str]:
    lines = lines if lines is not None else []
    if value is None:
        return lines
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "@context":
                continue
            flatten_json(child, f"{path}.{key}" if path else str(key), lines)
    elif isinstance(value, list):
        for child in value:
            flatten_json(child, path, lines)
    elif isinstance(value, (str, int, float, bool)):
        text = clean_text(value)
        if text:
            lines.append(f"{path}: {text}" if path else text)
    return lines


def parse_json_data(data: Any, url: str, source: str, section: str = "بيانات") -> tuple[list[Document], list[tuple[str, str, str]]]:
    docs: list[Document] = []
    triples: list[tuple[str, str, str]] = []

    def walk(value: Any, current_section: str, parent_id: str = "") -> None:
        if isinstance(value, list):
            for child in value:
                walk(child, current_section, parent_id)
            return
        if not isinstance(value, dict):
            return
        subject = clean_text(value.get("@id") or value.get("id") or value.get("url") or value.get("name") or value.get("title") or parent_id)
        title = clean_text(value.get("title") or value.get("name") or value.get("headline") or value.get("label") or value.get("الاسم") or value.get("العنوان"))
        if title:
            body = " · ".join(flatten_json(value))
            kind = clean_text(value.get("type") or value.get("@type") or value.get("النوع") or "سجلّ")
            item_url = clean_text(value.get("url") or value.get("link") or url)
            docs.extend(make_documents(title, clean_text(value.get("section") or value.get("القسم") or current_section), kind, item_url, body, desc=clean_text(value.get("description") or value.get("abstract") or value.get("الوصف")), keywords=clean_text(value.get("keywords") or value.get("tags")), source=source, rank=1.15))
        if subject:
            for predicate, child in value.items():
                if predicate == "@context":
                    continue
                if isinstance(child, dict):
                    target = clean_text(child.get("@id") or child.get("id") or child.get("name") or child.get("title"))
                    if target:
                        triples.append((subject, predicate, target))
                elif isinstance(child, list):
                    for item in child:
                        if isinstance(item, dict):
                            target = clean_text(item.get("@id") or item.get("id") or item.get("name") or item.get("title"))
                            if target:
                                triples.append((subject, predicate, target))
        for key, child in value.items():
            if isinstance(child, (dict, list)) and key != "@context":
                walk(child, key if re.search(r"[\u0600-\u06ff]", key) else current_section, subject)

    walk(data, section)
    if not docs:
        body = " · ".join(flatten_json(data))
        docs.extend(make_documents(Path(source.split("#", 1)[0]).stem, section, "بيانات", url, body, source=source))
    return docs, triples


def parse_markdown(raw: str, url: str, source: str) -> list[Document]:
    title = Path(source).stem
    current = title
    buffer: list[str] = []
    docs: list[Document] = []
    for line in raw.splitlines():
        match = re.match(r"^#{1,6}\s+(.+?)\s*$", line)
        if match:
            if buffer:
                docs.extend(make_documents(title, title, "مقال", url, "\n".join(buffer), heading=current, source=source))
            current = clean_text(match.group(1))
            if title == Path(source).stem:
                title = current
            buffer = []
        else:
            buffer.append(re.sub(r"[`*_>#\[\]]", " ", line))
    if buffer:
        docs.extend(make_documents(title, title, "مقال", url, "\n".join(buffer), heading=current, source=source))
    return docs


def parse_xml(raw: bytes, url: str, source: str) -> tuple[list[Document], list[tuple[str, str, str]]]:
    docs: list[Document] = []
    triples: list[tuple[str, str, str]] = []
    root = ElementTree.fromstring(raw)
    title = Path(source).stem
    body = clean_text(" ".join(text for text in root.itertext()))
    docs.extend(make_documents(title, "الأنطولوجيا والبيانات", "أنطولوجيا", url, body, source=source, rank=1.2))
    for element in root.iter():
        subject = next((clean_text(value) for key, value in element.attrib.items() if key.endswith(("about", "ID", "id"))), "")
        if not subject:
            continue
        for child in element:
            target = next((clean_text(value) for key, value in child.attrib.items() if key.endswith(("resource", "about", "ID", "id"))), "") or clean_text(child.text)
            if target:
                triples.append((subject, child.tag.rsplit("}", 1)[-1], target))
    return docs, triples


def parse_docx(path: Path, url: str) -> list[Document]:
    with zipfile.ZipFile(path) as archive:
        raw = archive.read("word/document.xml")
    root = ElementTree.fromstring(raw)
    paragraphs = []
    for paragraph in root.iter():
        if paragraph.tag.endswith("}p"):
            text = clean_text(" ".join(node.text or "" for node in paragraph.iter() if node.tag.endswith("}t")))
            if text:
                paragraphs.append(text)
    return make_documents(path.stem, "الكتب والوثائق", "وثيقة DOCX", url, "\n".join(paragraphs), source=path.relative_to(ROOT).as_posix(), rank=1.1)


def parse_pdf(path: Path, url: str) -> list[Document]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("pypdf is required to index PDF files") from exc
    reader = PdfReader(str(path))
    metadata = reader.metadata or {}
    title = clean_text(getattr(metadata, "title", "")) or path.stem
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    return make_documents(title, "الكتب والوثائق", "PDF", url, text, source=path.relative_to(ROOT).as_posix(), rank=1.1)


def parse_csv_file(path: Path, url: str) -> list[Document]:
    docs: list[Document] = []
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as stream:
        reader = csv.DictReader(stream)
        for number, row in enumerate(reader, 1):
            body = " — ".join(f"{key}: {clean_text(value)}" for key, value in row.items() if clean_text(value))
            docs.extend(make_documents(f"{path.stem} — صف {number}", path.stem, "بيانات جدولية", url, body, source=path.relative_to(ROOT).as_posix()))
    return docs


def discover_files() -> Iterable[Path]:
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED:
            continue
        relative = path.relative_to(ROOT)
        if any(part in SKIP_DIRS for part in relative.parts):
            continue
        if relative.parts[0] == "scripts":
            continue
        if path.name in GENERATED:
            continue
        yield path


def classify(document: Document, suffix: str) -> set[str]:
    haystack = " ".join((document.source, document.title, document.section, document.type, document.keywords, document.body[:1200]))
    categories = {name for name, pattern in CATEGORY_TERMS.items() if pattern.search(haystack)}
    if suffix in {".rdf", ".owl", ".xml", ".jsonld"}:
        categories.add("ontology")
    if suffix in {".pdf", ".docx"}:
        categories.add("books")
    if suffix in {".md", ".markdown"}:
        categories.add("articles")
    if "ansab" in document.source.lower():
        categories.add("genealogy")
    if not categories:
        categories.add("heritage")
    return categories


def collect() -> tuple[list[Document], list[tuple[str, str, str]], Counter]:
    documents: list[Document] = []
    triples: list[tuple[str, str, str]] = []
    stats: Counter = Counter()
    for path in discover_files():
        suffix = path.suffix.lower()
        url = public_url(path)
        source = path.relative_to(ROOT).as_posix()
        try:
            if suffix in {".html", ".htm"}:
                file_docs, file_triples = parse_html_text(path.read_text("utf-8", errors="replace"), url, source)
            elif suffix in {".json", ".jsonld"}:
                file_docs, file_triples = parse_json_data(json.loads(path.read_text("utf-8-sig")), url, source)
            elif suffix == ".pdf":
                file_docs, file_triples = parse_pdf(path, url), []
            elif suffix == ".docx":
                file_docs, file_triples = parse_docx(path, url), []
            elif suffix in {".md", ".markdown"}:
                file_docs, file_triples = parse_markdown(path.read_text("utf-8", errors="replace"), url, source), []
            elif suffix in {".xml", ".rdf", ".owl"}:
                file_docs, file_triples = parse_xml(path.read_bytes(), url, source)
            elif suffix == ".csv":
                file_docs, file_triples = parse_csv_file(path, url), []
            else:
                text = path.read_text("utf-8", errors="replace")
                file_docs, file_triples = make_documents(path.stem, path.parent.name or "الوثائق", "نص", url, text, source=source), []
        except Exception as exc:
            print(f"[search-index] skipped {source}: {exc}", file=sys.stderr)
            stats["skipped"] += 1
            continue
        for document in file_docs:
            document.categories = classify(document, suffix)
        documents.extend(file_docs)
        triples.extend(file_triples)
        stats["files"] += 1
        stats[suffix] += 1
    return deduplicate(documents), triples, stats


def deduplicate(documents: list[Document]) -> list[Document]:
    unique: dict[str, Document] = {}
    for document in documents:
        if not document.title or len(normalize(document.title + " " + document.body)) < 8:
            continue
        key = normalize(document.url + "|" + document.title + "|" + document.body[:180])
        if key not in unique:
            unique[key] = document
        else:
            unique[key].categories.update(document.categories)
    return list(unique.values())


def build_index(documents: list[Document], metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    postings: dict[str, list[float | int]] = defaultdict(list)
    stems: dict[str, list[str]] = defaultdict(list)
    sections: Counter = Counter()
    output_docs: list[dict[str, Any]] = []
    total_length = 0
    for doc_id, document in enumerate(documents):
        fields = {
            "title": document.title, "keywords": document.keywords, "section": document.section,
            "heading": document.heading, "desc": document.desc, "alt": document.alt, "body": document.body,
        }
        accumulated: dict[str, float] = defaultdict(float)
        length = 0
        for field_name, value in fields.items():
            weight = FIELD_WEIGHT[field_name]
            for token in tokenize(value):
                if token in STOP:
                    continue
                length += 1
                accumulated[token] += weight
                root = stem(token)
                if root != token and len(root) >= 3 and token not in stems[root]:
                    stems[root].append(token)
        for token, weight in accumulated.items():
            postings[token].extend((doc_id, round(weight, 2)))
        sections[document.section] += 1
        total_length += length or 1
        output_docs.append({
            "i": doc_id, "t": document.title, "s": document.section, "y": document.type, "u": document.url,
            "d": document.desc, "b": document.body[:1600], "g": document.img, "r": document.rank,
            "m": 0, "n": normalize(" ".join((document.title, document.section, document.keywords, document.heading, document.desc, document.body)))[:6000],
            "l": length or 1,
        })
    index = {
        "v": INDEX_VERSION, "built": int(time.time() * 1000), "docs": output_docs,
        "terms": sorted(postings), "postings": dict(postings), "stems": dict(stems),
        "sections": dict(sections), "avgLen": total_length / max(1, len(output_docs)),
    }
    if metadata:
        index["meta"] = metadata
    return index


def build_graph(documents: list[Document], triples: list[tuple[str, str, str]]) -> dict[str, Any]:
    nodes: dict[str, dict[str, str]] = {}
    edges: set[tuple[str, str, str]] = set()
    for document in documents:
        doc_node = "document:" + normalize(document.url + "#" + document.title)[:160]
        nodes[doc_node] = {"id": doc_node, "label": document.title, "type": document.type, "url": document.url}
        for category in document.categories:
            category_node = "category:" + category
            nodes[category_node] = {"id": category_node, "label": category, "type": "category", "url": ""}
            edges.add((doc_node, "categorizedAs", category_node))
    for subject, predicate, target in triples:
        source_id = "entity:" + normalize(subject)[:160]
        target_id = "entity:" + normalize(target)[:160]
        if not source_id.endswith(":") and not target_id.endswith(":"):
            nodes[source_id] = {"id": source_id, "label": subject, "type": "entity", "url": ""}
            nodes[target_id] = {"id": target_id, "label": target, "type": "entity", "url": ""}
            edges.add((source_id, clean_text(predicate)[:100], target_id))
    return {
        "v": 1, "built": int(time.time() * 1000), "nodes": list(nodes.values()),
        "edges": [{"source": source, "predicate": predicate, "target": target} for source, predicate, target in sorted(edges)],
    }


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def main() -> int:
    documents, triples, stats = collect()
    graph = build_graph(documents, triples)
    metadata = {
        "mode": "netlify-build", "files": stats["files"], "skipped": stats["skipped"],
        "formats": {key: value for key, value in sorted(stats.items()) if key.startswith(".")},
        "graph": {"nodes": len(graph["nodes"]), "edges": len(graph["edges"])},
    }
    write_json(OUTPUT_DIR / "search-index.json", build_index(documents, metadata))
    write_json(OUTPUT_DIR / "semantic-graph.json", graph)
    file_names = {
        "heritage": "heritage.idx", "ontology": "ontology.idx", "genealogy": "genealogy.idx",
        "books": "books.idx", "articles": "articles.idx",
    }
    for category, file_name in file_names.items():
        selected = [document for document in documents if category in document.categories]
        write_json(OUTPUT_DIR / file_name, build_index(selected, {"category": category, "documents": len(selected)}))
    print(f"[search-index] indexed {stats['files']} files into {len(documents)} passages; graph {len(graph['nodes'])} nodes/{len(graph['edges'])} edges")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
