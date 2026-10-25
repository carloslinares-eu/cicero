"""Finding every piece of translatable text in a Word document and putting translations back."""

from __future__ import annotations

import zipfile
from collections.abc import Iterator
from pathlib import Path

import docx
import docx.opc.exceptions
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.opc.part import Part, XmlPart
from docx.oxml import parse_xml
from docx.text.run import Run
from lxml import etree

from cicero.core.blocks import TextBlock, make_block, save_atomically
from cicero.core.errors import DocumentError

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
# Runs directly in the paragraph, inside links, tracked insertions and smart tags. Deleted
# text (w:del) is left alone, and so are field codes, which aren't in w:t elements.
RUNS_XPATH = " | ".join(["./w:r", "./w:hyperlink/w:r", "./w:ins/w:r", "./w:smartTag/w:r", "./w:customXml/w:r",
                         "./w:sdt/w:sdtContent/w:r"])
# Setting Run.text replaces everything in the run, so runs that also hold pictures,
# objects or field markers are never written to.
UNSAFE_RUN_CONTENT = {f"{W}drawing", f"{W}pict", f"{W}object", f"{W}fldChar", f"{W}footnoteReference",
                      f"{W}endnoteReference", f"{W}commentReference", f"{W}sym"}
# Parts other than the main body that hold text, in the order they are read.
STORY_PARTS = [(RT.HEADER, "Header"), (RT.FOOTER, "Footer"), (RT.FOOTNOTES, "Footnotes"),
               (RT.ENDNOTES, "Endnotes"), (RT.COMMENTS, "Comments")]


class DocxDocument:
    """An open Word document, the paragraphs found in it, and how to save it."""

    kind = "Word document"
    unit = None  # Word lays pages out when it opens the file; the file itself has no page numbers
    page_count = 0

    def __init__(self, path: str | Path) -> None:
        self.document = open_word_document(path)
        self.warnings: list[str] = []
        self._xml_parts: list[_StoryXml] = []
        self.blocks = self._collect()

    def save(self, path: str | Path) -> None:
        for part in self._xml_parts:
            part.write_back()
        save_atomically(self.document.save, path)

    def _collect(self) -> list[TextBlock]:
        blocks = []
        for name, story in self._iter_stories():
            for paragraph in story.iter(f"{W}p"):
                runs = [Run(r, None) for r in paragraph.xpath(RUNS_XPATH)]
                safe = [run for run in runs if not any(child.tag in UNSAFE_RUN_CONTENT for child in run._r)]
                block = make_block(0, _location(name, paragraph), safe, "".join(run.text for run in runs))
                if block is not None:
                    blocks.append(block)
        return blocks

    def _iter_stories(self) -> Iterator[tuple[str, etree._Element]]:
        yield "Body", self.document.element.body
        seen: set[str] = set()
        for reltype, name in STORY_PARTS:
            for relationship in self.document.part.rels.values():
                if relationship.reltype != reltype or relationship.is_external:
                    continue
                part = relationship.target_part
                if str(part.partname) in seen:
                    continue
                seen.add(str(part.partname))
                story = _StoryXml(part)
                self._xml_parts.append(story)
                yield name, story.element


def _location(story: str, paragraph: etree._Element) -> str:
    """"Body", "Body › Table", "Header › Text box"…"""
    for ancestor in paragraph.iterancestors():
        if ancestor.tag == f"{W}txbxContent":
            return f"{story} › Text box"
        if ancestor.tag == f"{W}tbl":
            return f"{story} › Table"
    return story


class _StoryXml:
    """Gives access to the XML of a header, footer, notes or comments part, whatever python-docx loaded it as."""

    def __init__(self, part: Part) -> None:
        self.part = part
        self.element = part.element if isinstance(part, XmlPart) else parse_xml(part.blob)

    def write_back(self) -> None:
        if not isinstance(self.part, XmlPart):
            self.part._blob = etree.tostring(self.element, xml_declaration=True, encoding="UTF-8", standalone=True)


def open_word_document(path: str | Path):
    try:
        return docx.Document(str(path))
    except FileNotFoundError:
        raise DocumentError(f"File not found:\n{path}") from None
    except PermissionError:
        raise DocumentError(f"Can't open the file. Is it open in another program?\n{path}") from None
    except (docx.opc.exceptions.PackageNotFoundError, zipfile.BadZipFile, KeyError, ValueError) as exc:
        raise DocumentError(
            f"This isn't a Word .docx file, or it is damaged.\n{path}\n\n"
            "Older .doc files must first be saved as .docx from Word.\n\n"
            f"Details: {exc}"
        ) from None
