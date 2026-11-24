import asyncio
import os
from datetime import date
from math import isfinite
from urllib.parse import urljoin, urlsplit

import httpx

from .receipt_preview import ReceiptFields, ReceiptPreview
from .receipt_extraction import classify_receipt


AZURE_MODELS = {
    'azure': ('prebuilt-receipt', 'MerchantName', 'TransactionDate', 'Total'),
    'azure-invoice': ('prebuilt-invoice', 'VendorName', 'InvoiceDate', 'InvoiceTotal'),
}


def normalize_result(payload: dict, mode: str = 'azure') -> ReceiptPreview:
    analysis = payload.get('analyzeResult', {})
    documents = analysis.get('documents', [])
    if not documents:
        return ReceiptPreview(provider='azure', no_document_match=True,
                              warning='Azure found no matching receipt or invoice. Enter the details manually.')
    if len(documents) > 1:
        return ReceiptPreview(provider='azure', warning='Azure found multiple documents. Attach one receipt or invoice at a time.')
    fields = documents[0].get('fields', {})
    _, merchant_field, date_field, total_field = AZURE_MODELS[mode]

    def trusted(name, threshold=0.85):
        field = fields.get(name) or {}
        confidence = field.get('confidence')
        return field if isinstance(confidence, (int, float)) and confidence >= threshold else {}

    merchant = trusted(merchant_field).get('valueString')
    merchant = merchant.strip() if isinstance(merchant, str) else ''
    raw_date = trusted(date_field).get('valueDate')
    try:
        transaction_date = date.fromisoformat(raw_date) if isinstance(raw_date, str) else None
    except ValueError:
        transaction_date = None
    total = trusted(total_field, 0.90).get('valueCurrency') or {}
    currency = total.get('currencyCode')
    value = total.get('amount')
    amount = value if currency == 'INR' and type(value) in (float, int) and isfinite(value) and value > 0 else None
    warning = None
    if amount is None:
        warning = 'Could not verify an INR total. Enter the amount in INR manually.'
    text = analysis.get('content') or ''
    return ReceiptPreview(
        provider='azure',
        fields=ReceiptFields(merchant=merchant or None if len(merchant) <= 255 else None,
                            expense_date=transaction_date, amount=amount,
                            category=classify_receipt(text)),
        warning=warning,
    )


async def extract_azure(content: bytes, *, mode: str = 'azure', transport=None) -> ReceiptPreview:
    model_id, *_ = AZURE_MODELS[mode]
    endpoint = os.getenv('AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT', '').strip().rstrip('/')
    key = os.getenv('AZURE_DOCUMENT_INTELLIGENCE_KEY', '')
    origin = urlsplit(endpoint)
    if (not key or origin.scheme != 'https' or not origin.hostname
            or origin.path or origin.query or origin.fragment or origin.username or origin.password):
        raise ValueError('Azure receipt extraction is not configured')
    headers = {'Ocp-Apim-Subscription-Key': key}
    async with asyncio.timeout(30):
        async with httpx.AsyncClient(timeout=10, follow_redirects=False, transport=transport) as client:
            response = await client.post(
                f'{endpoint}/documentintelligence/documentModels/{model_id}:analyze',
                params={'api-version': '2024-11-30'}, content=content,
                headers={**headers, 'Content-Type': 'application/octet-stream'},
            )
            response.raise_for_status()
            operation = response.headers.get('Operation-Location')
            if response.status_code != 202 or not operation:
                raise ValueError('Azure did not return an analysis operation')
            operation = urljoin(endpoint, operation)
            target = urlsplit(operation)
            if (target.scheme, target.netloc) != (origin.scheme, origin.netloc):
                raise ValueError('Invalid Azure analysis location')
            while True:
                delay = response.headers.get('Retry-After', '')
                await asyncio.sleep(min(10, max(1, int(delay))) if delay.isascii() and delay.isdigit() else 1)
                response = await client.get(operation, headers=headers)
                response.raise_for_status()
                result = response.json()
                if result.get('status') == 'succeeded':
                    return normalize_result(result, mode)
                if result.get('status') not in ('running', 'notStarted'):
                    raise ValueError('Azure receipt analysis failed')
