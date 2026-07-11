from __future__ import annotations

_VECTOR_DIMS = 3072

_SEMANTIC_CONFIG = {
    "defaultConfiguration": "default",
    "configurations": [
        {
            "name": "default",
            "prioritizedFields": {
                "titleField": {"fieldName": "title"},
                "prioritizedContentFields": [
                    {"fieldName": "raw_text"},
                ],
            },
        }
    ],
}

_VECTOR_SEARCH_CONFIG = {
    "algorithms": [
        {
            "name": "hnsw-config",
            "kind": "hnsw",
            "hnswParameters": {
                "metric": "cosine",
                "m": 4,
                "efConstruction": 400,
                "efSearch": 500,
            },
        }
    ],
    "profiles": [
        {
            "name": "vector-profile",
            "algorithm": "hnsw-config",
        }
    ],
}


def get_index_definition(index_name: str) -> dict:
    """Return a full Azure AI Search index definition compatible with the REST API."""
    return {
        "name": index_name,
        "fields": [
            {
                "name": "chunk_id",
                "type": "Edm.String",
                "key": True,
                "filterable": True,
                "retrievable": True,
                "searchable": False,
            },
            {
                "name": "document_id",
                "type": "Edm.String",
                "filterable": True,
                "facetable": True,
                "retrievable": True,
                "searchable": False,
            },
            {
                "name": "course_id",
                "type": "Edm.String",
                "filterable": True,
                "facetable": True,
                "retrievable": True,
                "searchable": False,
            },
            {
                "name": "jurisdiction",
                "type": "Edm.String",
                "filterable": True,
                "facetable": True,
                "retrievable": True,
                "searchable": False,
            },
            {
                "name": "source_type",
                "type": "Edm.String",
                "filterable": True,
                "facetable": True,
                "retrievable": True,
                "searchable": False,
            },
            {
                "name": "source_priority",
                "type": "Edm.String",
                "filterable": True,
                "facetable": True,
                "retrievable": True,
                "searchable": False,
                "sortable": True,
            },
            {
                "name": "source_intent",
                "type": "Edm.String",
                "filterable": False,
                "retrievable": True,
                "searchable": True,
                "analyzer": "en.microsoft",
            },
            {
                "name": "section_id",
                "type": "Edm.String",
                "filterable": True,
                "retrievable": True,
                "searchable": False,
            },
            {
                "name": "source_file",
                "type": "Edm.String",
                "filterable": True,
                "facetable": True,
                "retrievable": True,
                "searchable": False,
            },
            {
                "name": "page_num",
                "type": "Edm.Int32",
                "filterable": True,
                "retrievable": True,
                "searchable": False,
                "sortable": True,
            },
            {
                "name": "title",
                "type": "Edm.String",
                "filterable": False,
                "retrievable": True,
                "searchable": True,
                "analyzer": "en.microsoft",
            },
            {
                "name": "section_title",
                "type": "Edm.String",
                "filterable": False,
                "retrievable": True,
                "searchable": True,
                "analyzer": "en.microsoft",
            },
            {
                "name": "chunk_title",
                "type": "Edm.String",
                "filterable": False,
                "retrievable": True,
                "searchable": True,
                "analyzer": "en.microsoft",
            },
            {
                "name": "chunk_index",
                "type": "Edm.Int32",
                "filterable": True,
                "retrievable": True,
                "searchable": False,
                "sortable": True,
            },
            {
                "name": "raw_text",
                "type": "Edm.String",
                "filterable": False,
                "retrievable": True,
                "searchable": True,
                "analyzer": "en.microsoft",
            },
            {
                "name": "token_count",
                "type": "Edm.Int32",
                "filterable": True,
                "retrievable": True,
                "searchable": False,
                "sortable": True,
            },
            {
                "name": "estimated_read_min",
                "type": "Edm.Double",
                "filterable": False,
                "retrievable": True,
                "searchable": False,
                "sortable": True,
            },
            {
                "name": "upload_date",
                "type": "Edm.DateTimeOffset",
                "filterable": True,
                "retrievable": True,
                "searchable": False,
                "sortable": True,
            },
            {
                "name": "searchable_text",
                "type": "Edm.String",
                "filterable": False,
                "retrievable": False,
                "searchable": True,
                "analyzer": "en.microsoft",
            },
            {
                "name": "embedding_content",
                "type": "Collection(Edm.Single)",
                "searchable": True,
                "retrievable": False,
                "dimensions": _VECTOR_DIMS,
                "vectorSearchProfile": "vector-profile",
            },
        ],
        "vectorSearch": _VECTOR_SEARCH_CONFIG,
        "semantic": _SEMANTIC_CONFIG,
    }
