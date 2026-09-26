"""Read a named published worksheet without executing workbook content."""
import io
import posixpath
import re
import zipfile
import xml.etree.ElementTree as ET


def sheet_rows(raw, name):
    ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main", "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        def xml(path):
            if z.getinfo(path).file_size > 20000000:
                raise ValueError("XLSX sheet exceeds size limit")
            body = z.read(path)
            if b"<!ENTITY" in body or b"<!DOCTYPE" in body:
                raise ValueError("XML entity declarations are not accepted")
            return ET.fromstring(body)
        sheets = xml("xl/workbook.xml").findall("s:sheets/s:sheet", ns)
        wanted = next((x for x in sheets if x.get("name") == name), None)
        if wanted is None:
            raise ValueError("Published worksheet not found: " + name)
        rels = {x.get("Id"): x.get("Target") for x in xml("xl/_rels/workbook.xml.rels")}
        target = rels[wanted.get("{" + ns["r"] + "}id")]
        path = target.lstrip("/") if target.startswith("/") else posixpath.normpath("xl/" + target)
        if not path.startswith("xl/"):
            raise ValueError("Unexpected worksheet path")
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            shared = ["".join(x.itertext()) for x in xml("xl/sharedStrings.xml").findall("s:si", ns)]
        output = []
        for row in xml(path).findall(".//s:sheetData/s:row", ns):
            result = {}
            for c in row.findall("s:c", ns):
                column = re.sub(r"\d", "", c.get("r", "A1"))
                v = c.find("s:v", ns)
                text = v.text if v is not None else ""
                if c.get("t") == "s" and text:
                    text = shared[int(text)]
                elif c.get("t") == "inlineStr":
                    text = "".join(c.itertext())
                result[column] = text or ""
            output.append(result)
        return output
