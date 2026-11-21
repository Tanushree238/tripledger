import os
from abc import ABC, abstractmethod
import httpx
from .contracts import AIRequest, AIResponse, Context

class AIProvider(ABC):
    @abstractmethod
    async def execute(self, request: AIRequest, context: Context) -> AIResponse: ...

class MockProvider(AIProvider):
    async def execute(self, request, context):
        if request.task == 'expense_summary':
            answer = f'Visible expenses: {context.expense_count}. Total: INR {context.total_amount:,.2f}. Policy exceptions: {context.exception_count}.'
            sources = ['TripLedger expense records']
        else:
            answer = '\n'.join(f"{p['name']}: expense limit INR {p['max_expense']:,.2f}; receipt required above INR {p['receipt_threshold']:,.2f}." for p in context.policies) or 'No applicable policy configured.'
            sources = [p['name'] for p in context.policies]
        return AIResponse(answer=answer, provider='mock', sources=sources)

class HTTPProvider(AIProvider):
    def __init__(self, mode, url, timeout=10, transport=None):
        self.mode, self.url, self.timeout, self.transport = mode, url, timeout, transport
    async def execute(self, request, context):
        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport, follow_redirects=False) as client:
            response = await client.post(self.url.rstrip('/') + '/execute', json={'request': request.model_dump(), 'context': context.model_dump(), 'mode': self.mode})
            response.raise_for_status()
            result = AIResponse.model_validate(response.json())
            if result.provider != self.mode:
                raise ValueError('Unexpected provider')
            return result

def get_provider():
    mode = os.getenv('AI_MODE', 'mock')
    if mode == 'mock': return MockProvider()
    if mode in ('baseline', 'rag') and os.getenv('AI_SERVICE_URL'):
        return HTTPProvider(mode, os.environ['AI_SERVICE_URL'], float(os.getenv('AI_TIMEOUT_SECONDS', '10')))
    raise ValueError('AI provider configuration unavailable')
