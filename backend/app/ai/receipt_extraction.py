import os
import re
import subprocess
from datetime import datetime
from decimal import Decimal
from difflib import SequenceMatcher
from pathlib import Path
from tempfile import TemporaryDirectory

from .receipt_preview import ReceiptFields, ReceiptPreview


INR = re.compile(r'₹|\bINR\b\.?|\bRs\.?\s*(?=\d)', re.I)
FOREIGN_CODES = r'(?:USD|EUR|GBP|AED|AUD|CAD|SGD|JPY|CNY|CHF|NZD|HKD|SAR|MYR|THB|IDR)'
FOREIGN = re.compile(
    rf'[$€£¥](?=\s*(?:[1-9]|0[.,]\d*[1-9]))|'
    rf'\b{FOREIGN_CODES}\b(?=[ \t]*\.?[ \t]*\d)|'
    rf'\b(?:currency[ \t]*[:=]?[ \t]*|\d+[.,]\d{{2}}[ \t]+|'
    rf'(?:total|amount)[ \t]*[:=]?[ \t]*\d+[ \t]+){FOREIGN_CODES}\b',
    re.I,
)
TOTAL = re.compile(
    r'^(?:total amount after tax|total invoice amount|total received amount|amount paid|total paid|grand total|net payable|'
    r'net amount|amount payable|total payable|total amount|total)\b\s*[:=]?\s*(.*)$', re.I,
)
NUMBER = re.compile(r'(?:\d{1,3}(?:,\d{2})*,\d{3}|\d{1,3}(?:,\d{3})+|\d{1,9})(?:\.\d{1,2})?')
TABLE_TOTAL = re.compile(r'^(?:total qty\s+grand total|total amount)\s*$', re.I)
INCLUSIVE_TOTAL_HEADER = re.compile(r'\btotal\s*\(\s*incl\b', re.I)
TABLE_CURRENCY = re.compile(r'\bamount\s*\(\s*Rs\.?\s*\)', re.I)
INDIAN_GSTIN = re.compile(r'\bGSTIN(?:\s+no\.?)?\s*[:.]?\s*\d{2}[A-Z]{5}\d{4}[A-Z]\dZ[A-Z0-9]\b', re.I)
DATE = re.compile(
    r'\b(?:(?P<kind>invoice|receipt|transaction|bill)\s+)?date'
    r'(?:\s+and\s+time|(?P<supply>\s+of\s+supply)|(?P<issue>\s+of\s+issue))?'
    r'\b\s*[:=]?\s*(?P<value>.*)$',
    re.I,
)
INVOICE_VALUE = re.compile(r'\binvoice value\s*:\s*((?:INR\b\.?|₹|Rs\.?)\s*\d[\d,.]*)\s*$', re.I)
DATE_VALUE = re.compile(
    r'^(\d{4}-\d{2}-\d{2}|\d{1,2}[-/]\d{1,2}[-/]\d{4}|'
    r'\d{1,2}[ -][A-Za-z]{3,9}[ ,-]+\d{4}|[A-Za-z]{3,9}\s+\d{1,2}[ ,]+\d{4})\b'
)
MERCHANT = re.compile(r'(?:^|\s{2,})(?:merchant|sold by|vendor|supplier|invoice issued by)\s*:\s*(.{1,120})$', re.I)
HEADER = re.compile(r"[\w][\w &'’.,-]{1,79}")
LEGAL_HEADER = re.compile(r"[\w][\w &'’.,()-]{1,79}\s+(?:limited|ltd\.?|llp|inc\.?)(?:\s+\(trading as [\w &'’.,-]{1,60}\))?", re.I)
NON_MERCHANT = re.compile(r'\b(?:invoice|receipt|tax|date|bill|gstin|phone|address|customer|welcome|copy|original|email|booking id)\b', re.I)
WATERMARK = re.compile(r'\b(?:sample only|not valid|for software testing only|fictional merchant)\b', re.I)
RECEIPT_HEADINGS = {
    'hotel': 'Hotel', 'lodging': 'Hotel', 'accommodation': 'Hotel',
    'fuel': 'Fuel', 'petrol': 'Fuel', 'diesel': 'Fuel',
    'transport': 'Ground transport', 'taxi': 'Ground transport', 'cab': 'Ground transport',
    'rail travel': 'Rail travel', 'rail': 'Rail travel', 'train': 'Rail travel',
    'meal': 'Meals', 'restaurant': 'Meals', 'café': 'Meals', 'cafe': 'Meals', 'coffee': 'Meals',
    'airfare': 'Airfare', 'flight': 'Airfare', 'office supplies': 'Office supplies',
}
RECEIPT_HEADING = re.compile(r'^(.+?)\s+(?:receipt|invoice|ticket)$', re.I)
PRINT_HEADER = re.compile(r'^\d{1,2}/\d{1,2}/\d{2,4},\s+\d{1,2}:\d{2}\s+[AP]M\s+', re.I)
INVOICE_NUMBER = re.compile(r'^invoice\s+(?:no\.?|number)\b', re.I)
INLINE_NUMERIC_DATE = re.compile(r'\b\d{1,2}[-/]\d{1,2}[-/]\d{4}\b')


def classify_receipt(text: str):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    categories = {
        RECEIPT_HEADINGS[heading]
        for line in lines[:10]
        if (match := RECEIPT_HEADING.fullmatch(line))
        and (heading := ' '.join(match[1].lower().split())) in RECEIPT_HEADINGS
    }
    if re.search(r'\bflight\s+(?:no\b|number\b)', text, re.I) and re.search(r'\bPNR\b', text, re.I):
        categories.add('Airfare')
    if (re.search(r'\bhotel accommodation\b', text, re.I)
            or (re.search(r'\bhotel name\b', text, re.I) and re.search(r'\baccommodation charges\b', text, re.I))):
        categories.add('Hotel')
    return next(iter(categories)) if len(categories) == 1 else None


def parse_receipt(text: str) -> ReceiptPreview:
    merchant = None
    totals = set()
    dates = {priority: set() for priority in (0, 1, 2)}
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    indian_gstin = bool(INDIAN_GSTIN.search(text))
    inr_table = bool(TABLE_CURRENCY.search(text))
    table_amounts = set()
    for index, line in enumerate(lines):
        following = lines[index + 1] if index + 1 < len(lines) else ''
        if match := MERCHANT.search(line):
            merchant = merchant or match[1].strip()
        if INVOICE_NUMBER.match(line):
            for numeric in INLINE_NUMERIC_DATE.findall(line):
                try:
                    dates[2].add(datetime.strptime(numeric.replace('/', '-'), '%d-%m-%Y').date())
                except ValueError:
                    continue
        if match := DATE.search(line):
            if not re.search(r'\b(?:order|due|expiry|delivery|check-in|check-out)\s*$', line[:match.start()], re.I):
                date_text = re.sub(r'^(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),\s+', '', match['value'] or following, flags=re.I)
                if date_match := DATE_VALUE.match(date_text):
                    value = re.sub(r'[ /,-]+', '-', date_match[1])
                    priority = 2 if match['kind'] or match['issue'] else 0 if match['supply'] else 1
                    for date_format in ('%Y-%m-%d', '%d-%m-%Y', '%d-%b-%Y', '%d-%B-%Y',
                                        '%b-%d-%Y', '%B-%d-%Y'):
                        try:
                            dates[priority].add(datetime.strptime(value, date_format).date())
                            break
                        except ValueError:
                            continue
        if match := TOTAL.fullmatch(line.lstrip("'’ ")):
            label = match[0].lower()
            terminal_total = label.startswith(('grand total', 'total amount after tax'))
            following_is_total = INR.search(following) or (terminal_total and indian_gstin)
            value = INR.sub('', match[1] or (following if following_is_total else '')).strip()
            if indian_gstin and value.startswith('%'):
                value = value[1:].strip()
            if match[0].lower().startswith('total amount') and (summary := re.fullmatch(r'\d{1,3}\s+(\d[\d,.]*)', value)):
                value = summary[1]
            table_header = any(INCLUSIVE_TOTAL_HEADER.search(header)
                               for header in lines[max(0, index - 16):index])
            if label.startswith('grand total') and table_header and re.fullmatch(r'[\d,.\s]+', value):
                columns = re.split(r'\s{2,}', value)
                if len(columns) >= 3:
                    value = columns[-1]
            if NUMBER.fullmatch(value):
                totals.add(Decimal(value.replace(',', '')))
        if TABLE_TOTAL.fullmatch(line):
            quantity_and_total = re.fullmatch(r'\d+\s{2,}(.+)', following)
            if quantity_and_total and (INR.search(following) or indian_gstin):
                value = INR.sub('', quantity_and_total[1]).strip()
                if NUMBER.fullmatch(value):
                    totals.add(Decimal(value.replace(',', '')))
        if inr_table and NUMBER.fullmatch(line) and '.' in line:
            table_amounts.add(Decimal(line.replace(',', '')))
        if match := INVOICE_VALUE.search(line):
            value = INR.sub('', match[1]).strip()
            if NUMBER.fullmatch(value):
                totals.add(Decimal(value.replace(',', '')))

    best_dates = next((dates[priority] for priority in (2, 1, 0) if dates[priority]), set())
    if not totals and len(table_amounts) == 1 and re.search(r'^total amount\s*:', text, re.I | re.M):
        totals = table_amounts
    if not merchant and (totals or best_dates):
        legal_names = {}
        for line in lines[:60]:
            name = re.split(r'\s{2,}', line, maxsplit=1)[0].rstrip(' .')
            if (LEGAL_HEADER.fullmatch(name) and not NON_MERCHANT.search(name)
                    and not re.match(r'^(?:pvt\.?|private)\s+', name, re.I)):
                legal_names.setdefault(name.casefold(), name)
        if len(legal_names) == 1:
            merchant = next(iter(legal_names.values()))
        if merchant is None:
            domains = {domain.casefold() for domain in
                       re.findall(r'(?:@\s*|www\.)([a-z][a-z0-9-]*)\.[a-z]{2,}\b', text, re.I)}
            brands = {
                line for line in lines
                if line.isalpha() and line.casefold() in domains
                and any(SequenceMatcher(None, header.casefold(), line.casefold()).ratio() >= .75
                        for header in lines[:3])
            }
            if len(brands) == 1:
                merchant = next(iter(brands))
        headers = (PRINT_HEADER.sub('', line) for line in lines[:3])
        merchant = merchant or next((line for line in headers if HEADER.fullmatch(line)
                         and line[0].isalpha() and not any(char.isdigit() for char in line)
                         and not NON_MERCHANT.search(line)
                         and not WATERMARK.search(line)), None)
    foreign = bool(FOREIGN.search(text))
    indian_tax_invoice = all(re.search(rf'\b{label}\b', text, re.I)
                             for label in ('GSTIN', 'CGST', 'SGST'))
    amount = None
    if not foreign and (INR.search(text) or indian_tax_invoice or indian_gstin or inr_table) and len(totals) == 1:
        total = next(iter(totals))
        if total > 0:
            amount = float(total)

    fields = ReceiptFields(
        merchant=merchant or None, amount=amount,
        expense_date=next(iter(best_dates)) if len(best_dates) == 1 else None,
        category=classify_receipt(text),
    )
    has_fields = any(value is not None for value in fields.model_dump().values())
    warning = None
    if foreign:
        warning = 'Foreign currency detected. Enter the amount in INR manually.'
    elif not has_fields:
        warning = ('Receipt text was found, but no supported fields could be identified. Enter the details manually.'
                   if lines else 'No readable text was found. Try a clearer image or enter the details manually.')
    return ReceiptPreview(
        provider='local',
        fields=fields if has_fields else None,
        warning=warning,
    )


def run_text(*command: str) -> str:
    result = subprocess.run(command, check=True, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, timeout=8,
                            env={**os.environ, 'OMP_THREAD_LIMIT': '1'})
    return result.stdout.decode('utf-8', errors='replace')


CORE_FIELDS = ('merchant', 'amount', 'expense_date')


def readable_fields(preview: ReceiptPreview) -> int:
    return sum(getattr(preview.fields, field, None) is not None for field in CORE_FIELDS)


def combine_previews(primary: ReceiptPreview, alternate: ReceiptPreview) -> ReceiptPreview:
    if alternate.warning and alternate.warning.startswith('Foreign currency'):
        return alternate
    if not primary.fields or not alternate.fields:
        return primary if primary.fields else alternate
    for name in ('amount', 'expense_date'):
        original, detected = getattr(primary.fields, name), getattr(alternate.fields, name)
        if original is not None and detected is not None and original != detected:
            return primary
    combined = primary.fields.model_dump()
    for name, value in alternate.fields.model_dump().items():
        if combined[name] is None:
            combined[name] = value
    return ReceiptPreview(provider='local', fields=ReceiptFields(**combined))


def extract_receipt(content: bytes, extension: str) -> ReceiptPreview:
    with TemporaryDirectory(prefix='tripledger-receipt-') as directory:
        source = Path(directory) / f'receipt{extension}'
        source.write_bytes(content)
        if extension == '.pdf':
            text = run_text('pdftotext', '-f', '1', '-l', '2', '-layout', str(source), '-')
            preview = parse_receipt(text)
            if readable_fields(preview) == len(CORE_FIELDS) or FOREIGN.search(text):
                return preview
            rendered = Path(directory) / 'page'
            run_text('pdftoppm', '-f', '1', '-l', '2', '-scale-to', '2200', '-png',
                     str(source), str(rendered))
            pages = sorted(Path(directory).glob('page-*.png'))
            ocr_text = '\n'.join(run_text('tesseract', str(page), 'stdout', '-l', 'eng', '--psm', '6')
                                 for page in pages)
            preview = combine_previews(preview, parse_receipt(ocr_text.strip() or text))
            if readable_fields(preview) < len(CORE_FIELDS) and pages and not FOREIGN.search(ocr_text):
                alternate = run_text('tesseract', str(pages[0]), 'stdout', '-l', 'eng', '--psm', '3')
                preview = combine_previews(preview, parse_receipt(alternate))
            return preview
        text = run_text('tesseract', str(source), 'stdout', '-l', 'eng')
        preview = parse_receipt(text)
        if (preview.fields is None or preview.fields.amount is None or preview.fields.expense_date is None
                or preview.fields.category is None) and not FOREIGN.search(text):
            fallback = run_text('tesseract', str(source), 'stdout', '-l', 'eng', '--psm', '6')
            alternate = parse_receipt(fallback)
            if FOREIGN.search(fallback):
                return alternate
            if readable_fields(alternate) > readable_fields(preview):
                return alternate
            if preview.fields and alternate.fields and preview.fields.category is None:
                preview.fields.category = alternate.fields.category
        return preview
