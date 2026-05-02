from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from zipfile import ZipFile, ZIP_DEFLATED

from xml.sax.saxutils import escape


@dataclass(frozen=True)
class Section:
    heading: str
    items: list[str]


@dataclass(frozen=True)
class ManualPage:
    title: str
    subtitle: str
    revision: str
    features: list[str]
    sections: list[Section]
    note: str


def run(text: str, bold: bool = False, italic: bool = False, size: int | None = None) -> str:
    props = []
    if bold:
        props.append("<w:b/>")
    if italic:
        props.append("<w:i/>")
    if size is not None:
        props.append(f'<w:sz w:val="{size}"/>')
        props.append(f'<w:szCs w:val="{size}"/>')
    prop_xml = f"<w:rPr>{''.join(props)}</w:rPr>" if props else ""
    return f"<w:r>{prop_xml}<w:t xml:space=\"preserve\">{escape(text)}</w:t></w:r>"


def paragraph(
    text: str = "",
    *,
    bold: bool = False,
    italic: bool = False,
    size: int | None = None,
    alignment: str | None = None,
    spacing_before: int | None = None,
    spacing_after: int | None = None,
) -> str:
    ppr = []
    if alignment:
        ppr.append(f'<w:jc w:val="{alignment}"/>')
    spacing = []
    if spacing_before is not None:
        spacing.append(f'w:before="{spacing_before}"')
    if spacing_after is not None:
        spacing.append(f'w:after="{spacing_after}"')
    if spacing:
        ppr.append(f"<w:spacing {' '.join(spacing)}/>")
    ppr_xml = f"<w:pPr>{''.join(ppr)}</w:pPr>" if ppr else ""
    if not text:
        return f"<w:p>{ppr_xml}</w:p>"
    return f"<w:p>{ppr_xml}{run(text, bold=bold, italic=italic, size=size)}</w:p>"


def numbered_item(number: int, text: str) -> str:
    return (
        "<w:p>"
        '<w:pPr><w:ind w:left="360" w:hanging="360"/></w:pPr>'
        f"{run(f'{number}. ', bold=True)}"
        f"{run(text)}"
        "</w:p>"
    )


def bullet_item(text: str) -> str:
    return (
        "<w:p>"
        '<w:pPr><w:ind w:left="360" w:hanging="360"/></w:pPr>'
        f"{run('• ')}"
        f"{run(text)}"
        "</w:p>"
    )


def section_block(section: Section) -> str:
    parts = [paragraph(section.heading, bold=True, size=28, spacing_before=120, spacing_after=120)]
    for idx, item in enumerate(section.items, start=1):
        parts.append(numbered_item(idx, item))
    return "".join(parts)


def page_block(page: ManualPage, include_page_break: bool = True) -> str:
    parts = [
        paragraph(page.title, bold=True, size=36, alignment="center", spacing_after=120),
        paragraph(page.subtitle, italic=True, size=22, alignment="center", spacing_after=120),
        paragraph(f"Revision: {page.revision}", size=18, alignment="center", spacing_after=240),
        paragraph("Features", bold=True, size=28, spacing_after=120),
    ]
    parts.extend(bullet_item(item) for item in page.features)
    for section in page.sections:
        parts.append(section_block(section))
    parts.append(paragraph("NOTE", bold=True, size=24, spacing_before=220, spacing_after=80))
    parts.append(paragraph(page.note, italic=True, size=18))
    if include_page_break:
        parts.append('<w:p><w:r><w:br w:type="page"/></w:r></w:p>')
    return "".join(parts)


def build_document_xml(pages: list[ManualPage]) -> str:
    body_parts = [page_block(page, include_page_break=(idx < len(pages) - 1)) for idx, page in enumerate(pages)]
    body_parts.append(
        "<w:sectPr>"
        '<w:pgSz w:w="12240" w:h="15840"/>'
        '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" w:header="720" w:footer="720" w:gutter="0"/>'
        "</w:sectPr>"
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{''.join(body_parts)}</w:body>"
        "</w:document>"
    )


def write_docx(output_path: Path, pages: list[ManualPage]) -> None:
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>
"""
    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>
"""

    document_xml = build_document_xml(pages)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output_path, "w", ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("word/document.xml", document_xml)


def main() -> None:
    pages = [
        ManualPage(
            title="FilCare Clinic User Guide",
            subtitle="Patient registration, login, and booking flow",
            revision="05/02/2026",
            features=[
                "Create a patient account using the registration form and verification code.",
                "Sign in with your email and password after account creation.",
                "Find a doctor by specialization and book a face-to-face appointment.",
                "Track appointment status, cancellations, and lab result requests.",
            ],
            sections=[
                Section(
                    "Patient Registration",
                    [
                        "Open Sign Up and enter your first name, middle name if needed, last name, email address, password, and confirm password.",
                        "Tap Send Verification Code, check your email, then enter the 6-digit code to finish creating the account.",
                    ],
                ),
                Section(
                    "Patient Login",
                    [
                        "Open the Login screen, enter your registered email address and password, then tap Sign In.",
                        "After login, the app opens the patient dashboard where you can see your profile and recent activity.",
                    ],
                ),
                Section(
                    "Patient Booking Flow",
                    [
                        "Open Book Appointment and choose a specialization.",
                        "Select the doctor you want to visit.",
                        "Pick an available schedule, then enter the reason for visit.",
                        "Review the summary and confirm the booking.",
                    ],
                ),
                Section(
                    "Patient Follow-Up Flow",
                    [
                        "Open My Appointments to check pending, confirmed, completed, or cancelled visits.",
                        "If the doctor requires it, upload the lab result photo and add a description.",
                        "If you need to cancel, send a cancellation request with a reason.",
                    ],
                ),
            ],
            note="If the patient registration form, login fields, or booking screens change, update this document so the steps stay accurate.",
        ),
        ManualPage(
            title="FilCare Clinic User Guide",
            subtitle="Appointment tracking, cancellation, and lab result flow",
            revision="05/02/2026",
            features=[
                "Review appointment statuses from the dashboard.",
                "See doctor notes and laboratory requirements on each appointment card.",
                "Submit lab results or request cancellation from the appointment record.",
            ],
            sections=[
                Section(
                    "Appointment Tracking",
                    [
                        "Open My Appointments and use the tabs to separate today, upcoming, confirmed, completed, and cancelled visits.",
                        "Each appointment card shows the doctor name, schedule, reason for visit, and current status.",
                    ],
                ),
                Section(
                    "Lab Result Flow",
                    [
                        "If the doctor asks for a laboratory result, open the appointment and submit a photo or a short description.",
                        "Wait for the doctor to review the submission before booking another related visit.",
                    ],
                ),
                Section(
                    "Cancellation Flow",
                    [
                        "For pending appointments, tap Request Cancellation and enter the reason.",
                        "Wait for the doctor or staff to approve or reject the request.",
                    ],
                ),
            ],
            note="This page covers patient follow-up actions after booking. Update it whenever appointment statuses or approval rules change.",
        ),
        ManualPage(
            title="FilCare Clinic User Guide",
            subtitle="Login and front-desk workflow for the clinic attendant",
            revision="05/02/2026",
            features=[
                "Log in using the clinic attendant account.",
                "Review, confirm, and search appointment records.",
                "Approve or reject cancellation requests.",
                "Check the doctor's schedule and availability.",
            ],
            sections=[
                Section(
                    "Staff Login",
                    [
                        "Open the Login screen and sign in using the clinic attendant email and password provided by the clinic.",
                        "After login, the staff dashboard opens with the assigned doctor's appointment summary.",
                    ],
                ),
                Section(
                    "Front Desk Flow",
                    [
                        "Use the tabs to separate pending, confirmed, and handled visits.",
                        "Search by patient name, doctor, date, or status when a record needs to be checked quickly.",
                        "Confirm bookings that are ready and keep the appointment queue updated.",
                        "Review cancellation requests and approve or reject them based on clinic policy.",
                    ],
                ),
                Section(
                    "Schedule Support",
                    [
                        "Open Doctor Schedule to see the assigned doctor's available dates, times, and consultation fee.",
                        "Use the schedule view to help patients and answer booking questions correctly.",
                    ],
                ),
            ],
            note="Use the staff page as the clinic support guide. If approval rights or schedule handling changes, update this document.",
        ),
        ManualPage(
            title="FilCare Clinic User Guide",
            subtitle="Login, consultation, lab review, and schedule flow for doctors",
            revision="05/02/2026",
            features=[
                "Log in using the doctor account.",
                "Review patient appointments by status.",
                "Mark consultations as done and add checkup notes.",
                "Approve or reject submitted lab results.",
                "Create and manage your own clinic schedule.",
            ],
            sections=[
                Section(
                    "Doctor Login",
                    [
                        "Open the Login screen and sign in using the doctor email and password.",
                        "After login, the doctor dashboard shows the current workload and recent activity.",
                    ],
                ),
                Section(
                    "Consultation Flow",
                    [
                        "Open My Appointments and review the patient list by status.",
                        "Check the reason for visit, appointment time, and any laboratory requirement before the consultation.",
                        "When the visit is complete, tap Mark as Done and enter the checkup result or doctor's note.",
                    ],
                ),
                Section(
                    "Lab And Schedule Flow",
                    [
                        "If a patient submits a lab result, open the review panel, inspect the image, then approve or reject it with feedback.",
                        "Open My Schedules to create, edit, or delete availability slots and keep the clinic calendar current.",
                    ],
                ),
            ],
            note="This doctor page matches the current app flow. If login, lab review, or schedule logic changes, update this document.",
        ),
    ]

    output_path = Path(__file__).resolve().parent.parent / "FilCare_Clinic_User_Guide.docx"
    write_docx(output_path, pages)
    print(f"Created {output_path}")


if __name__ == "__main__":
    main()
