"""
Export utilities: CSV, Excel, PDF.
"""
import csv
import io
from django.http import HttpResponse, StreamingHttpResponse
from core.utils import format_duration


def sanitize_spreadsheet_cell(val):
    """
    Sanitize cell value to prevent CSV / Spreadsheet Formula Injection (CWE-1236).
    Neutralizes DDE / formula triggers: '=', '+', '-', '@', '\t', '\r'.
    """
    if val is None:
        return ""
    str_val = str(val).strip()
    if str_val.startswith(('=', '+', '-', '@', '\t', '\r')):
        return f"'{str_val}"
    return str_val


class Echo:
    """An object that implements just the write method of the file-like interface for StreamingHttpResponse."""
    def write(self, value):
        return value


class CSVExporter:
    """Export leaderboard data as a memory-efficient streaming CSV (O(1) RAM footprint)."""

    @staticmethod
    def export(quiz, entries_iterator):
        pseudo_buffer = Echo()
        writer = csv.writer(pseudo_buffer)

        def stream_rows():
            yield writer.writerow([
                'Rank', 'Name', 'College', 'Score', 'Accuracy (%)',
                'Time Taken', 'Questions Attempted', 'Correct', 'Wrong'
            ])
            for entry in entries_iterator:
                yield writer.writerow([
                    entry['rank'],
                    sanitize_spreadsheet_cell(entry['name']),
                    sanitize_spreadsheet_cell(entry['college']),
                    entry['score'],
                    f"{entry['accuracy']}%",
                    format_duration(entry['time_taken']),
                    entry['questions_attempted'],
                    entry['correct_answers'],
                    entry['wrong_answers'],
                ])

        response = StreamingHttpResponse(stream_rows(), content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="{quiz.title}_results.csv"'
        return response


class ExcelExporter:
    """Export leaderboard data as Excel (.xlsx) using memory-efficient streaming write_only workbook."""

    @staticmethod
    def export(quiz, entries_iterator):
        from openpyxl import Workbook
        from openpyxl.styles import Font, Alignment, PatternFill
        from openpyxl.cell import WriteOnlyCell

        wb = Workbook(write_only=True)
        ws = wb.create_sheet(title="Results")

        # Header styling
        header_font = Font(bold=True, color="FFFFFF", size=12)
        header_fill = PatternFill(start_color="6C63FF", end_color="6C63FF", fill_type="solid")

        headers = [
            'Rank', 'Name', 'College', 'Score', 'Accuracy (%)',
            'Time Taken', 'Questions Attempted', 'Correct', 'Wrong'
        ]

        header_cells = []
        for header in headers:
            cell = WriteOnlyCell(ws, value=header)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal='center')
            header_cells.append(cell)
        ws.append(header_cells)

        for entry in entries_iterator:
            ws.append([
                entry['rank'],
                sanitize_spreadsheet_cell(entry['name']),
                sanitize_spreadsheet_cell(entry['college']),
                entry['score'],
                f"{entry['accuracy']}%",
                format_duration(entry['time_taken']),
                entry['questions_attempted'],
                entry['correct_answers'],
                entry['wrong_answers'],
            ])

        buffer = io.BytesIO()
        wb.save(buffer)
        buffer.seek(0)

        response = HttpResponse(
            buffer.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = f'attachment; filename="{quiz.title}_results.xlsx"'
        return response


class PDFExporter:
    """Export leaderboard data as PDF with chunk-safe table generation."""

    @staticmethod
    def export(quiz, entries_iterator):
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=landscape(A4))
        styles = getSampleStyleSheet()
        elements = []

        # Title
        elements.append(Paragraph(f"<b>{quiz.title} — Results</b>", styles['Title']))
        elements.append(Spacer(1, 15))

        # Table data
        data = [[
            'Rank', 'Name', 'College', 'Score', 'Accuracy',
            'Time', 'Attempted', 'Correct', 'Wrong'
        ]]

        cell_style = styles['Normal']
        cell_style.fontSize = 8
        cell_style.leading = 10
        cell_style.alignment = 1  # Centered

        count = 0
        is_truncated = False
        for entry in entries_iterator:
            clean_name = str(entry.get('name') or 'N/A').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            clean_college = str(entry.get('college') or 'N/A').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            data.append([
                str(entry.get('rank', '-')),
                Paragraph(clean_name[:60], cell_style),
                Paragraph(clean_college[:60], cell_style),
                str(entry.get('score', 0)),
                f"{entry.get('accuracy', 0)}%",
                format_duration(entry.get('time_taken', 0)),
                str(entry.get('questions_attempted', 0)),
                str(entry.get('correct_answers', 0)),
                str(entry.get('wrong_answers', 0)),
            ])
            count += 1
            if count >= 1000:
                is_truncated = True
                break

        table = Table(data, repeatRows=1, colWidths=[45, 160, 160, 55, 60, 60, 65, 55, 55])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#6C63FF')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.whitesmoke, colors.white]),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
        ]))

        elements.append(table)

        if is_truncated:
            elements.append(Spacer(1, 10))
            elements.append(Paragraph(
                "<i>Note: PDF report includes the top 1,000 participants for optimal rendering performance. "
                "For complete raw exports of all candidates, please download the CSV or Excel report.</i>",
                styles['Normal']
            ))

        doc.build(elements)

        buffer.seek(0)
        response = HttpResponse(buffer, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{quiz.title}_results.pdf"'
        return response

