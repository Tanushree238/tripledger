import argparse
import asyncio
import json
from collections import Counter
from decimal import Decimal
from pathlib import Path

from app.ai.azure_receipts import AZURE_MODELS, extract_azure
from app.ai.receipt_extraction import extract_receipt


async def benchmark(manifest: Path, provider: str):
    scores = {field: Counter(correct=0, blank=0, wrong=0)
              for field in ('merchant', 'expense_date', 'amount')}
    errors = 0
    rows = json.loads(manifest.read_text(encoding='utf-8'))
    for row in rows:
        path = (manifest.parent / row['file']).resolve()
        if not path.is_relative_to(manifest.parent.resolve()):
            raise ValueError('Receipt paths must stay within the manifest folder')
        content = path.read_bytes()
        try:
            preview = (await extract_azure(content, mode=provider) if provider in AZURE_MODELS
                       else extract_receipt(content, path.suffix.lower()))
        except Exception as error:
            errors += 1
            print(f"{row['file']}: extraction error ({type(error).__name__})")
            continue
        predicted = preview.fields.model_dump(mode='json') if preview.fields else {}
        expected = {
            'merchant': row['merchant'],
            'expense_date': row['date'],
            'amount': Decimal(str(row['total'])) if row['currency'] == 'INR' else None,
        }
        outcomes = {}
        for field, reference in expected.items():
            actual = predicted.get(field)
            if field == 'merchant' and actual and reference:
                actual, reference = (' '.join(value.casefold().split()) for value in (actual, reference))
            if field == 'amount' and actual is not None:
                actual = Decimal(str(actual))
            outcome = 'correct' if actual == reference else 'blank' if actual is None else 'wrong'
            outcomes[field] = outcome
            scores[field][outcome] += 1
        print(f"{row['file']}: {outcomes}")
    print(json.dumps({'provider': provider, 'receipts': len(rows), 'errors': errors, 'fields': scores}, indent=2))
    return errors


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('provider', choices=['local', *AZURE_MODELS])
    parser.add_argument('manifest', type=Path)
    args = parser.parse_args()
    raise SystemExit(bool(asyncio.run(benchmark(args.manifest, args.provider))))
