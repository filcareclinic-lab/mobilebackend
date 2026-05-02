from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


PAGE_W = 612
PAGE_H = 792
MARGIN = 36
BOX_W = PAGE_W - MARGIN * 2


@dataclass(frozen=True)
class Section:
    heading: str
    items: list[str]
    ordered: bool = True


@dataclass(frozen=True)
class ManualPage:
    role_title: str
    subtitle: str
    revision: str
    features: list[str]
    sections: list[Section]
    note: list[str]


def escape_pdf_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def measure_text(text: str, size: float) -> float:
    total = 0.0
    for ch in text:
        if ch == " ":
            total += 0.28
        elif ch in "ilI.,:;!|'`":
            total += 0.22
        elif ch in "mwMW@#%&":
            total += 0.85
        elif ch.isupper():
            total += 0.62
        elif ch.isdigit():
            total += 0.55
        elif ch in "-_/\\":
            total += 0.35
        else:
            total += 0.50
    return total * size


def wrap_text(text: str, size: float, max_width: float) -> list[str]:
    words = text.split()
    if not words:
        return [""]

    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if measure_text(candidate, size) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


class PdfCanvas:
    def __init__(self) -> None:
        self.ops: list[str] = []

    def line_width(self, width: float) -> None:
        self.ops.append(f"{width:.2f} w")

    def stroke_color(self, r: int, g: int, b: int) -> None:
        self.ops.append(f"{r / 255:.3f} {g / 255:.3f} {b / 255:.3f} RG")

    def fill_color(self, r: int, g: int, b: int) -> None:
        self.ops.append(f"{r / 255:.3f} {g / 255:.3f} {b / 255:.3f} rg")

    def rect(self, x: float, y: float, w: float, h: float, mode: str = "S") -> None:
        self.ops.append(f"{x:.2f} {y:.2f} {w:.2f} {h:.2f} re {mode}")

    def line(self, x1: float, y1: float, x2: float, y2: float) -> None:
        self.ops.append(f"{x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l S")

    def text(self, x: float, y: float, text: str, size: float = 12, font: str = "F1") -> None:
        self.ops.append(
            f"BT /{font} {size:.2f} Tf 1 0 0 1 {x:.2f} {y:.2f} Tm ({escape_pdf_text(text)}) Tj ET"
        )

    def text_lines(
        self,
        x: float,
        y_top: float,
        lines: Iterable[str],
        size: float = 12,
        font: str = "F1",
        leading: float | None = None,
    ) -> float:
        if leading is None:
            leading = size * 1.3
        y = y_top
        for line in lines:
            self.text(x, y, line, size=size, font=font)
            y -= leading
        return y

    def build_stream(self) -> bytes:
        body = "\n".join(self.ops).encode("ascii")
        return body


def draw_bullets(
    canvas: PdfCanvas,
    x: float,
    y_top: float,
    bullets: list[str],
    size: float,
    max_width: float,
    bullet_indent: float = 10,
    leading: float | None = None,
) -> float:
    if leading is None:
        leading = size * 1.35
    y = y_top
    for bullet in bullets:
        wrapped = wrap_text(bullet, size, max_width - bullet_indent)
        canvas.text(x, y, "-", size=size, font="F2")
        canvas.text_lines(x + bullet_indent, y, wrapped, size=size, font="F1", leading=leading)
        y -= leading * len(wrapped)
        y -= leading * 0.20
    return y


def draw_block(
    canvas: PdfCanvas,
    x: float,
    y_top: float,
    section: Section,
    size: float,
    max_width: float,
) -> float:
    title_size = size + 1.2
    leading = size * 1.33
    bullet_indent = 14

    lines_per_item: list[list[str]] = []
    for item in section.items:
        lines_per_item.append(wrap_text(item, size, max_width - bullet_indent))

    content_height = 14  # title gap and top padding
    content_height += 5
    for lines in lines_per_item:
        content_height += len(lines) * leading + 5
    content_height += 12

    bottom = y_top - content_height
    canvas.stroke_color(0, 0, 0)
    canvas.line_width(1.8)
    canvas.rect(x, bottom, max_width + 12, content_height)

    canvas.fill_color(0, 0, 0)
    canvas.text(x + 10, y_top - 18, section.heading, size=title_size, font="F2")

    y = y_top - 36
    for idx, lines in enumerate(lines_per_item, start=1):
        prefix = f"{idx}." if section.ordered else "-"
        canvas.text(x + 12, y, prefix, size=size, font="F2")
        canvas.text_lines(
            x + 28,
            y,
            lines,
            size=size,
            font="F1",
            leading=leading,
        )
        y -= len(lines) * leading + 5
    return bottom - 10


def draw_page(canvas: PdfCanvas, page: ManualPage, page_number: int, total_pages: int) -> None:
    black = (0, 0, 0)
    gray = (245, 245, 245)
    blue = (3, 105, 161)

    # Header box.
    canvas.fill_color(*gray)
    canvas.rect(MARGIN + 1, 673, 248, 82, mode="f")
    canvas.stroke_color(*black)
    canvas.line_width(2.1)
    canvas.rect(MARGIN + 1, 673, 248, 82)
    canvas.fill_color(*black)
    canvas.text(MARGIN + 18, 729, "User Guide", size=22, font="F2")
    canvas.text(MARGIN + 18, 706, page.role_title, size=13.5, font="F2")
    canvas.text(MARGIN + 18, 690, page.subtitle, size=10.5, font="F1")
    canvas.text(MARGIN + 437, 742, f"rev {page.revision}", size=8.5, font="F1")

    y = 654
    section_width = BOX_W - 24

    # Features box sized to content.
    features = Section("Features", page.features, ordered=False)
    y = draw_block(canvas, MARGIN + 6, y, features, size=8.6, max_width=section_width)

    # Main sections sized to content.
    for section in page.sections:
        y = draw_block(canvas, MARGIN + 6, y, section, size=8.7, max_width=section_width)

    # Note box.
    note_lines = [line for line in page.note for line in wrap_text(line, 8.2, BOX_W - 28)]
    note_top = max(y - 2, 98)
    note_height = max(52, len(note_lines) * 11 + 18)
    canvas.stroke_color(*black)
    canvas.line_width(1.6)
    canvas.rect(MARGIN, note_top - note_height, BOX_W, note_height)
    canvas.text(MARGIN + 14, note_top - 14, "NOTE", size=10.2, font="F2")
    canvas.text_lines(
        MARGIN + 14,
        note_top - 28,
        note_lines,
        size=8.2,
        font="F1",
        leading=11,
    )
    canvas.text(MARGIN + 14, 56, f"Page {page_number} of {total_pages}", size=8.2, font="F1")
    canvas.stroke_color(*blue)
    canvas.line_width(0.9)
    canvas.line(MARGIN + 14, 62, MARGIN + 510, 62)


def build_pdf(pages: list[ManualPage], output_path: Path) -> None:
    font_regular = 1
    font_bold = 2
    pages_obj = 3
    catalog_obj = 4

    objects: list[bytes] = []
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")

    page_object_ids: list[int] = []
    content_object_ids: list[int] = []
    next_id = 5
    for _ in pages:
        page_object_ids.append(next_id)
        content_object_ids.append(next_id + 1)
        next_id += 2

    kids = " ".join(f"{pid} 0 R" for pid in page_object_ids)
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode("ascii"))
    objects.append(f"<< /Type /Catalog /Pages {pages_obj} 0 R >>".encode("ascii"))

    content_streams: list[bytes] = []
    for idx, page in enumerate(pages, start=1):
        canvas = PdfCanvas()
        draw_page(canvas, page, idx, len(pages))
        content_streams.append(canvas.build_stream())

    for page_id, content_id, stream in zip(page_object_ids, content_object_ids, content_streams):
        objects.append(
            (
                f"<< /Type /Page /Parent {pages_obj} 0 R /MediaBox [0 0 {PAGE_W} {PAGE_H}] "
                f"/Resources << /Font << /F1 {font_regular} 0 R /F2 {font_bold} 0 R >> >> "
                f"/Contents {content_id} 0 R >>"
            ).encode("ascii")
        )
        objects.append(
            b"<< /Length "
            + str(len(stream)).encode("ascii")
            + b" >>\nstream\n"
            + stream
            + b"\nendstream"
        )

    pdf = bytearray()
    pdf += b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    offsets = [0]
    for obj_id, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf += f"{obj_id} 0 obj\n".encode("ascii")
        pdf += obj
        if not obj.endswith(b"\n"):
            pdf += b"\n"
        pdf += b"endobj\n"

    xref_pos = len(pdf)
    pdf += f"xref\n0 {len(objects) + 1}\n".encode("ascii")
    pdf += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        pdf += f"{offset:010d} 00000 n \n".encode("ascii")
    pdf += (
        f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_obj} 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF\n"
    ).encode("ascii")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(pdf)


def main() -> None:
    pages = [
        ManualPage(
            role_title="Patient",
            subtitle="Registration, login, and booking flow for patients",
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
                    ordered=True,
                ),
                Section(
                    "Patient Login",
                    [
                        "Open the Login screen, enter your registered email address and password, then tap Sign In.",
                        "After login, the app opens the patient dashboard where you can see your profile and recent activity.",
                    ],
                    ordered=True,
                ),
                Section(
                    "Patient Booking Flow",
                    [
                        "Open Book Appointment and choose a specialization.",
                        "Select the doctor you want to visit.",
                        "Pick an available schedule, then enter the reason for visit.",
                        "Review the summary and confirm the booking.",
                    ],
                    ordered=True,
                ),
                Section(
                    "Patient Follow-Up Flow",
                    [
                        "Open My Appointments to check pending, confirmed, completed, or cancelled visits.",
                        "If the doctor requires it, upload the lab result photo and add a description.",
                        "If you need to cancel, send a cancellation request with a reason.",
                    ],
                    ordered=True,
                ),
            ],
            note=[
                "If the patient registration form, login fields, or booking screens change, regenerate this PDF so the steps stay accurate.",
            ],
        ),
        ManualPage(
            role_title="Patient",
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
                    ordered=True,
                ),
                Section(
                    "Lab Result Flow",
                    [
                        "If the doctor asks for a laboratory result, open the appointment and submit a photo or a short description.",
                        "Wait for the doctor to review the submission before booking another related visit.",
                    ],
                    ordered=True,
                ),
                Section(
                    "Cancellation Flow",
                    [
                        "For pending appointments, tap Request Cancellation and enter the reason.",
                        "Wait for the doctor or staff to approve or reject the request.",
                    ],
                    ordered=True,
                ),
            ],
            note=[
                "This page covers patient follow-up actions after booking. Update it whenever appointment statuses or approval rules change.",
            ],
        ),
        ManualPage(
            role_title="Clinic Attendant / Staff",
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
                    ordered=True,
                ),
                Section(
                    "Front Desk Flow",
                    [
                        "Use the tabs to separate pending, confirmed, and handled visits.",
                        "Search by patient name, doctor, date, or status when a record needs to be checked quickly.",
                        "Confirm bookings that are ready and keep the appointment queue updated.",
                        "Review cancellation requests and approve or reject them based on clinic policy.",
                    ],
                    ordered=True,
                ),
                Section(
                    "Schedule Support",
                    [
                        "Open Doctor Schedule to see the assigned doctor's available dates, times, and consultation fee.",
                        "Use the schedule view to help patients and answer booking questions correctly.",
                    ],
                    ordered=True,
                ),
            ],
            note=[
                "Use the staff page as the clinic support guide. If approval rights or schedule handling changes, update this PDF.",
            ],
        ),
        ManualPage(
            role_title="Doctor",
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
                    ordered=True,
                ),
                Section(
                    "Consultation Flow",
                    [
                        "Open My Appointments and review the patient list by status.",
                        "Check the reason for visit, appointment time, and any laboratory requirement before the consultation.",
                        "When the visit is complete, tap Mark as Done and enter the checkup result or doctor's note.",
                    ],
                    ordered=True,
                ),
                Section(
                    "Lab And Schedule Flow",
                    [
                        "If a patient submits a lab result, open the review panel, inspect the image, then approve or reject it with feedback.",
                        "Open My Schedules to create, edit, or delete availability slots and keep the clinic calendar current.",
                    ],
                    ordered=True,
                ),
            ],
            note=[
                "This doctor page matches the current app flow. If login, lab review, or schedule logic changes, regenerate the PDF.",
            ],
        ),
    ]

    output_path = Path(__file__).resolve().parent.parent / "FilCare_Clinic_User_Guide.pdf"
    build_pdf(pages, output_path)
    print(f"Created {output_path}")


if __name__ == "__main__":
    main()
