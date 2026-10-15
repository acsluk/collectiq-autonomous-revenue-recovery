"""Customer isolation uses separate Cognee datasets and sessions, never prompt-only filters."""
import copy
from .integrations import Cognee
from .policy import digest, require
from .store import now


class CustomerMemory:
    def __init__(self, cognee, customer_id):
        require(type(customer_id) is str and 3 <= len(customer_id) <= 150, 'A stable customer_id is required')
        self.customer_id = customer_id
        settings = copy.copy(cognee.settings)
        settings.dataset = settings.dataset + '_customer_' + digest(customer_id)[:20]
        self.client = Cognee(settings, cognee.transport)
        self.client.schema = cognee.schema

    @property
    def dataset(self):
        return self.client.settings.dataset

    def store(self, kind, content, reference):
        require(kind in ('contract', 'policy', 'promise', 'dispute', 'decision', 'execution', 'audit'), 'Unsupported memory kind')
        document = {'customer_id': self.customer_id, 'kind': kind, 'reference': reference,
                    'content_hash': digest(content), 'content': content}
        receipt = self.client.add(document)
        return {'customer_id': self.customer_id, 'dataset': self.dataset, 'document_hash': digest(document), **receipt}

    def store_contract(self, contract, reference):
        return self.store('contract', contract, reference)

    def store_policy(self, policy, reference):
        return self.store('policy', policy, reference)

    def store_promise(self, promise, reference):
        return self.store('promise', promise, reference)

    def store_dispute(self, dispute, reference):
        return self.store('dispute', dispute, reference)

    def store_decision(self, decision, explanation, reference):
        require(bool(explanation), 'Decision requires an explanation')
        return self.store('decision', {'decision': decision, 'explanation': explanation}, reference)

    def retrieve(self, query, mode='CHUNKS', **kwargs):
        result = self.client.search(query, mode, **kwargs)
        require(type(result['results']) is list, 'Unexpected Cognee search result envelope')
        # Check dataset envelopes if returned. A response from any other dataset is rejected wholesale.
        for row in result['results']:
            if isinstance(row, dict):
                returned_dataset=row.get('dataset_name',row.get('datasetName'))
                if returned_dataset is not None:
                    require(returned_dataset == self.dataset, 'Cognee returned another customer dataset')
        return {'customer_id': self.customer_id, 'dataset': self.dataset, **result}

    def retrieve_evidence(self):
        return self.retrieve(f'For customer {self.customer_id}, retrieve the contract, financial policy, incomplete deliverable dispute and historical payment promises.', 'CHUNKS')

    def index(self):
        return self.client.cognify()
