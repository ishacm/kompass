"""Make machine data read like a human wrote it, before it reaches a prompt or a reviewer."""
import re

GENDER_TAGS = re.compile(
    r"\s*[\(\[]\s*(m\s*/\s*w\s*/\s*d|w\s*/\s*m\s*/\s*d|m\s*/\s*f\s*/\s*d|f\s*/\s*m\s*/\s*x|m\s*/\s*f\s*/\s*x|"
    r"all genders|d\s*/\s*f\s*/\s*m|gn\*?|w\s*/\s*m\s*/\s*x|m\s*/\s*w\s*/\s*x)\s*[\)\]]", re.I)
LEGAL = re.compile(r",?\s+\b(GmbH\s*&\s*Co\.?\s*KG|GmbH|AG|SE|KG|UG(\s*\(haftungsbeschränkt\))?|Inc\.?|Ltd\.?|"
                   r"e\.\s?K\.)$", re.I)


def clean_title(title: str) -> str:
    t = GENDER_TAGS.sub("", title or "")
    t = re.sub(r"\s*[-–|]\s*(remote|hybrid|vollzeit|full[- ]time)\s*$", "", t, flags=re.I)
    return re.sub(r"\s+", " ", t).strip()


def short_name(name: str) -> str:
    n = (name or "").strip()
    for _ in range(2):
        n = LEGAL.sub("", n).strip()
    return n
