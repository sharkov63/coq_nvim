from dataclasses import dataclass
from typing import Annotated, Literal, Sequence, Tuple, Union
from uuid import UUID

UTF8 = "UTF-8"
UTF16 = "UTF-16-LE"

NvimPos = Tuple[int, Annotated[int, "In nvim, the col is a ut8 byte offset"]]
WTF8Pos = Tuple[int, Annotated[int, "Depends on `OffsetEncoding`"]]

BYTE_TRANS = {
    UTF8: 1,
    UTF16: 2,
}


@dataclass(frozen=True)
class Context:
    """
    |...                            line                            ...|
    |...        line_before           🐭          line_after        ...|
    |...   <syms_before><words_before>🐭<words_after><syms_after>   ...|
    """

    uid: UUID

    cwd: str
    filetype: str
    filename: str

    position: NvimPos

    line: str
    line_before: str
    line_after: str

    words: str
    words_before: str
    words_after: str

    syms: str
    syms_before: str
    syms_after: str


@dataclass(frozen=True)
class Edit:
    new_text: str


@dataclass(frozen=True)
class ContextualEdit(Edit):
    """
    <new_prefix>🐭<new_suffix>
    """

    old_prefix: str
    new_prefix: str
    old_suffix: str = ""


@dataclass(frozen=True)
class RangeEdit(Edit):
    """
    End exclusve, like LSP
    """

    begin: WTF8Pos
    end: WTF8Pos
    encoding: str = UTF16


@dataclass(frozen=True)
class SnippetEdit(Edit):
    grammar: Annotated[str, "ie. LSP, Texmate, Ultisnip, etc"]


ApplicableEdit = Union[Edit, RangeEdit, ContextualEdit]
PrimaryEdit = Union[ApplicableEdit, SnippetEdit]


@dataclass(frozen=True)
class Completion:
    primary_edit: PrimaryEdit
    secondary_edits: Sequence[RangeEdit] = ()
    sort_by: str = ""
    label: str = ""
    short_label: str = ""
    doc: str = ""
    doc_type: str = ""


@dataclass(frozen=True)
class EditEnv:
    linefeed: Literal["\r\n", "\n", "\r"]
    tabstop: bool
    expandtab: bool
