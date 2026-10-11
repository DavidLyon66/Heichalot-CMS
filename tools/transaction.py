#!/usr/bin/env python3

"""
Heichalot transaction language.

Transactions describe WHAT should happen.
Transport modules such as lan.py decide HOW they are delivered.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import socket
import uuid


CMS_CREATE = "cms.create"
CMS_RENAME = "cms.rename"
CMS_UPDATE = "cms.update"
CMS_DELETE = "cms.delete"
CMS_PUBLISH = "cms.publish"
CMS_ADD_IMAGE = "cms.add-image"
CMS_ADD_FILE = "cms.add-file"
CMS_SET_FIELD = "cms.set-field"
CMS_MOVE_STREAM = "cms.move-stream"


CMS_TRANSACTIONS = {
    CMS_CREATE,
    CMS_RENAME,
    CMS_UPDATE,
    CMS_DELETE,
    CMS_PUBLISH,
    CMS_ADD_IMAGE,
    CMS_ADD_FILE,
    CMS_SET_FIELD,
    CMS_MOVE_STREAM,
}


def make_transaction_id(node: str | None = None) -> str:
    node = node or socket.gethostname()

    timestamp = datetime.now(timezone.utc).strftime(
        "%Y%m%d-%H%M%S"
    )

    suffix = uuid.uuid4().hex[:6]

    return f"{node}-{timestamp}-{suffix}"


def make_transaction(
    transaction: str,
    *,
    transaction_id: str | None = None,
    source_transaction_id: str | None = None,
    from_node: str | None = None,
    **fields,
) -> dict:

    tx = {
        "transaction": transaction,
        "transaction_id": (
            transaction_id
            or make_transaction_id(from_node)
        ),
    }

    if from_node:
        tx["from"] = from_node

    if source_transaction_id:
        tx["source_transaction_id"] = source_transaction_id

    tx.update(fields)

    return tx


def dumps(transaction: dict) -> str:
    return json.dumps(
        transaction,
        indent=2,
        ensure_ascii=False,
    )


def loads(text: str) -> dict:
    transaction = json.loads(text)

    if not isinstance(transaction, dict):
        raise ValueError(
            "Transaction must be a JSON object"
        )

    if not transaction.get("transaction"):
        raise ValueError(
            "Transaction has no transaction type"
        )

    if not transaction.get("transaction_id"):
        raise ValueError(
            "Transaction has no transaction_id"
        )

    return transaction
    
